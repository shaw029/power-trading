"""Regenerate ``fleet/registry.py`` — the fleet this project analyses.

The dashboard cannot build a census. ``fleet.research.census`` and ``fleet.research.coverage``
pull whole registers and are barred from its process by
``tests/test_profile_boundary.py``, so the population it runs on has to be a
plain static list, exactly as ``fleet.registry`` is.

This script is the research-tier half of that split: it builds the census here,
where the heavy modules are allowed, keeps every site whose **energy capacity is
known**, and writes the result out as a data module the dashboard can import for
free.

The known-MWh filter is the whole point. Across the full census about a quarter
of sites have no published duration, and every metric that divides by energy
capacity — cycles per day, the duration bucket the benchmark is compared
against — is undefined for them. Including them would put ragged rows in front
of a reader; excluding them keeps every dashboard metric computable for every
site on screen, at the cost of the MW they carry.

Run after the census moves (new units commissioning, new Capacity Market
agreements)::

    python scripts/build_registry.py
"""

from __future__ import annotations

import datetime as dt
import math
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TARGET = REPO_ROOT / "fleet" / "registry.py"

HEADER = '''"""The battery fleet this project analyses — generated, do not hand-edit.

Every BM-registered GB battery the census can identify **whose energy capacity
is known**, which is what makes every dashboard metric computable for every site
shown: cycles per day and the duration bucket both divide by MWh, and a site
without one would render blank cells rather than a smaller number.

Every site in the curated registry is included: this is a superset of it, so the
dashboard can never show less than it did before. The generator refuses to write
a file that is not. Sizes are deliberately not written here — count the tuple
below, which is the only copy that cannot go stale.

Metadata provenance differs across the two groups and the difference matters:

* For the curated sites, ``optimiser``, ``region`` and
  ``capacity_mwh`` are hand-verified (see :mod:`fleet.registry`).
* For the rest, ``power_mw`` is Elexon's declared export capability and
  ``capacity_mwh`` comes from a matched Capacity Market agreement — both
  published figures. ``optimiser`` falls back to the BM Unit's lead party, which
  is the trading party rather than the optimiser proper, and ``region`` to the
  GSP group. Read the *By optimiser* cut with that in mind.

**Sites cycling below {threshold} cycles/day are left out**, measured over
{window}. That criterion is behaviour rather than identity, so this list moves
with market conditions as well as with the fleet — which is why the window is
recorded here. Left out on that basis:{quiet}

Generated {stamp} from a census snapshot by ``scripts/build_registry.py``.
Regenerate when the fleet moves on; this file is data, not logic.
"""

from fleet.population import FleetSite, Population

REGISTRY_SITES: tuple[FleetSite, ...] = (
'''


#: Days of dispatch used to measure how hard a site cycles.
MEASURE_DAYS = 60

#: Sites cycling below :data:`fleet.performance.ANCILLARY_CYCLES_THRESHOLD` are
#: left out of the registry entirely.
#:
#: **This is the one criterion here that is not a fact about an asset.** BM
#: registration and a published MWh are static; cycling is behaviour over a
#: window, so a list filtered on it moves with market conditions and not only
#: with which batteries exist. That cost is accepted deliberately, because a
#: site cycling this little is almost certainly earning in ancillary markets the
#: settlement model cannot see — while it *can* see the energy bought to hold
#: state of charge for those contracts. Its £ figures are therefore not merely
#: uncertain, they are systematically negative, and showing them as performance
#: misleads more than leaving the site out does.
#:
#: The threshold and the measurement both live in :mod:`fleet.performance`, not
#: here — the same rule decides what the dashboard flags and how notebook 04
#: splits its sites, and three copies of it is how a project ends up quoting
#: three different fleet sizes. The window and every excluded site's measured
#: rate are written into the generated file, so a reader can see why a battery
#: is absent rather than guess.


def main() -> int:
    from fleet.research import census as census_mod
    from fleet import curated as curated_mod
    from fleet import performance as fleet_perf
    from fleet import population as pop_mod

    THRESHOLD = fleet_perf.ANCILLARY_CYCLES_THRESHOLD

    census = pop_mod.census_population()
    keep = [
        s
        for s in census.sites
        if s.capacity_mwh and not math.isnan(s.capacity_mwh) and s.power_mw > 0
    ]
    keep.sort(key=lambda s: s.site)

    # A site dropped here loses its hand-researched optimiser, region and MWh,
    # which nothing else supplies. Refusing is the whole safety property.
    curated_names = {s.site for s in curated_mod.CURATED_SITES}
    missing = sorted(curated_names - {s.site for s in keep})
    if missing:
        raise SystemExit(
            "refusing to write: these curated sites would be dropped, so the "
            f"file would not be a superset of the metadata table — {missing}"
        )

    end = census_mod.snapshot_date()
    days = [end - dt.timedelta(days=i) for i in range(MEASURE_DAYS - 1, -1, -1)]
    rates = fleet_perf.cycles_per_day(census, keep, days)
    quiet = sorted((name, rate) for name, rate in rates.items() if rate < THRESHOLD)
    quiet_names = {name for name, _ in quiet}
    keep = [s for s in keep if s.site not in quiet_names]
    print(
        f"cycling measured over {days[0]} → {days[-1]} ({MEASURE_DAYS} days); "
        f"{len(quiet)} site(s) below {THRESHOLD} cycles/day removed:"
    )
    for name, rate in quiet:
        print(f"    {name:<38} {rate:.3f} cycles/day")

    lines = [
        HEADER.format(
            stamp=dt.date.today().isoformat(),
            window=f"{days[0]} → {days[-1]}",
            threshold=THRESHOLD,
            quiet="".join(f"\n  {n} ({r:.2f}/day)" for n, r in quiet) or " none",
        )
    ]
    for s in keep:
        ids = ", ".join(f'"{b}"' for b in s.bmu_ids)
        lines.append(
            f"    FleetSite(\n"
            f"        site={s.site!r},\n"
            f"        bmu_ids=({ids}{',' if len(s.bmu_ids) == 1 else ''}),\n"
            f"        power_mw={s.power_mw:.1f},\n"
            f"        capacity_mwh={s.capacity_mwh:.1f},\n"
            f"        optimiser={s.optimiser!r},\n"
            f"        region={s.region!r},\n"
            f"    ),\n"
        )
    lines.append(")\n\n")
    lines.append(
        "#: The dashboard's population. Its own cache suffix, because a day-file\n"
        "#: holds exactly the BM Units it was fetched for — reusing the curated\n"
        "#: cache would silently serve a 47-unit day as if it were the whole fleet.\n"
        "REGISTRY = Population(\n"
        '    name="registry", sites=REGISTRY_SITES, cache_suffix="_REGISTRY"\n'
        ")\n"
    )
    TARGET.write_text("".join(lines), encoding="utf-8")
    print(
        f"wrote {TARGET.relative_to(REPO_ROOT)}: {len(keep)} sites, "
        f"{sum(len(s.bmu_ids) for s in keep)} BM Units, "
        f"{sum(s.power_mw for s in keep):,.0f} MW"
    )
    subprocess.run([sys.executable, "-m", "flake8", str(TARGET)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
