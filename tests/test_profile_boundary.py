"""The dashboard must never import the research-profile data layer.

The live dashboard runs on Streamlit's free tier: roughly a gigabyte of RAM,
one container, and a cold start on every redeploy. The research modules are
built on the opposite assumption — the whole battery census, a three-year
window, registers pulled in full — and a single stray import is enough to drag
that into the dashboard's process, where it would not fail loudly but would
quietly push a working app over its memory limit.

`DATA_ARCHITECTURE.md` states the rule; these tests are what keep it true.
They read the source rather than importing it, so a forbidden import fails here
even when the module it points at would work fine locally on a warm cache.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Modules that assume the full profile — a large population, a long window, or
#: a register pulled in its entirety. None may be reachable from the dashboard.
FULL_PROFILE_MODULES = {
    "fleet.ancillary",
    "fleet.census",
    "fleet.coverage",
    "src.data.coverage",
    "build_stress_store",
    "scripts.build_stress_store",
    "scripts.backfill_market_data",
}

#: Everything the live dashboard loads at import time.
LITE_SURFACE = [
    "dashboard/live_app.py",
    "dashboard/app.py",
    "dashboard/charts.py",
    # Generated from the census by scripts/build_extended_fleet.py, but it is
    # the dashboard's population and therefore part of its import surface: it
    # must stay a plain data module.
    "fleet/extended.py",
] + [
    str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "live").glob("*.py")
]


def _imported_modules(path: Path) -> set[str]:
    """Every module named by an import statement anywhere in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


@pytest.mark.parametrize("relative_path", LITE_SURFACE)
def test_dashboard_does_not_import_the_full_profile(relative_path):
    path = REPO_ROOT / relative_path
    if not path.exists():
        pytest.skip(f"{relative_path} not present")
    leaked = _imported_modules(path) & FULL_PROFILE_MODULES
    assert not leaked, (
        f"{relative_path} imports full-profile module(s) {sorted(leaked)}. "
        "The dashboard runs on Streamlit's free tier — see DATA_ARCHITECTURE.md."
    )


def test_dashboard_population_is_static_and_fully_measurable():
    """The dashboard runs on the generated extended population, not the census.

    Two properties matter and neither is about size. Every site must have an
    energy capacity, because cycles per day and the duration bucket divide by
    it and a site without one renders blank cells rather than a smaller number.
    And the curated registry must remain a subset, so switching population can
    only ever add sites to a page, never drop one.
    """
    import math

    from fleet import registry
    from fleet.extended import EXTENDED

    assert len(registry.FLEET) == 23, "the curated registry itself is unchanged"

    assert EXTENDED.sites, "generated population must not be empty"
    for site in EXTENDED.sites:
        assert site.capacity_mwh and not math.isnan(site.capacity_mwh), site.site
        assert site.power_mw > 0, site.site

    assert {s.site for s in registry.FLEET} <= {s.site for s in EXTENDED.sites}
    assert len(EXTENDED.bmu_ids()) == len(set(EXTENDED.bmu_ids())), "duplicate BM Unit"
    # Its own cache suffix: a day-file holds exactly the units it was fetched
    # for, so sharing the curated cache would serve a 47-unit day as the fleet.
    assert EXTENDED.cache_suffix and EXTENDED.cache_suffix != registry_suffix()


def registry_suffix() -> str:
    from fleet.population import REGISTRY

    return REGISTRY.cache_suffix


def test_dashboard_window_stays_bounded():
    """A rolling window is what keeps the dashboard's memory independent of history."""
    source = (REPO_ROOT / "dashboard" / "live_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    limits = [
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "_MAX_HISTORY_DAYS" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    assert limits, "_MAX_HISTORY_DAYS is gone — the dashboard window is unbounded"
    assert limits[0] <= 90, f"window grew to {limits[0]} days; free-tier memory is ~1 GB"


def test_cached_reads_are_scoped_to_the_requested_window():
    """The dashboard's hot path must not scale with how much history is on disk.

    ``read_elexon_dataset`` is called once per rendered day. If it parses the
    whole cache each time, cost grows as O(days cached x days shown) and a
    long-running deployment gets slower at rendering the same 60 days.
    """
    from src.data.download import _files_in_range

    days = ("20240101", "20240215", "20240531", "20240601", "20240602", "20250101")
    files = [f"/cache/MID/MID_{d}_page_1.json" for d in days]

    selected = _files_in_range(files, "MID", "2024-06-01", "2024-06-01")

    # The requested day, plus one day either side: a UTC-stamped chunk can hold
    # the start of the neighbouring settlement day.
    assert [f.split("_")[-3] for f in selected] == ["20240531", "20240601", "20240602"]
    assert len(selected) < len(files), "the far-off days must not be read"


def test_unparseable_filenames_fall_back_to_reading_everything():
    """A cache whose names changed must degrade to correct-but-slow, never wrong."""
    from src.data.download import _files_in_range

    assert _files_in_range(["/cache/MID/MID_page_1.json"], "MID", "2024-06-01", "2024-06-01") == []
