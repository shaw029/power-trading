"""Regenerate ``fleet/extended.py`` — the dashboard's population.

The dashboard cannot build a census. ``fleet.census`` and ``fleet.coverage``
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

    python scripts/build_extended_fleet.py
"""

from __future__ import annotations

import datetime as dt
import math
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TARGET = REPO_ROOT / "fleet" / "extended.py"

HEADER = '''"""The live dashboard's battery population — generated, do not hand-edit.

Every BM-registered GB battery the census can identify **whose energy capacity
is known**, which is what makes every dashboard metric computable for every site
shown: cycles per day and the duration bucket both divide by MWh, and a site
without one would render blank cells rather than a smaller number.

{sites} sites / {bmus} BM Units / {mw:,.0f} MW, against the curated registry's
{reg_sites} / {reg_bmus} / {reg_mw:,.0f} MW. Every registry site is included —
this is a superset, so nothing the dashboard showed before it can show less of.

Metadata provenance differs across the two groups and the difference matters:

* For the {reg_sites} curated sites, ``optimiser``, ``region`` and
  ``capacity_mwh`` are hand-verified (see :mod:`fleet.registry`).
* For the rest, ``power_mw`` is Elexon's declared export capability and
  ``capacity_mwh`` comes from a matched Capacity Market agreement — both
  published figures. ``optimiser`` falls back to the BM Unit's lead party, which
  is the trading party rather than the optimiser proper, and ``region`` to the
  GSP group. Read the *By optimiser* cut with that in mind.

Generated {stamp} from census snapshot by ``scripts/build_extended_fleet.py``.
Regenerate when the fleet moves on; this file is data, not logic.
"""

from fleet.population import Population
from fleet.registry import FleetSite

EXTENDED_FLEET: tuple[FleetSite, ...] = (
'''


def main() -> int:
    from fleet import population as pop_mod

    census = pop_mod.census_population()
    registry = pop_mod.REGISTRY
    keep = [
        s for s in census.sites
        if s.capacity_mwh and not math.isnan(s.capacity_mwh) and s.power_mw > 0
    ]
    keep.sort(key=lambda s: s.site)

    reg_names = {s.site for s in registry.sites}
    missing = sorted(reg_names - {s.site for s in keep})
    if missing:
        raise SystemExit(
            "refusing to write: these curated sites would be dropped, so the "
            f"file would not be a superset of the registry — {missing}"
        )

    lines = [
        HEADER.format(
            sites=len(keep),
            bmus=sum(len(s.bmu_ids) for s in keep),
            mw=sum(s.power_mw for s in keep),
            reg_sites=len(registry.sites),
            reg_bmus=len(registry.bmu_ids()),
            reg_mw=sum(s.power_mw for s in registry.sites),
            stamp=dt.date.today().isoformat(),
        )
    ]
    for s in keep:
        ids = ", ".join(f'"{b}"' for b in s.bmu_ids)
        lines.append(
            f"    FleetSite(\n"
            f'        site={s.site!r},\n'
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
        'EXTENDED = Population(\n'
        '    name="extended", sites=EXTENDED_FLEET, cache_suffix="_EXT"\n'
        ')\n'
    )
    TARGET.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO_ROOT)}: {len(keep)} sites, "
          f"{sum(len(s.bmu_ids) for s in keep)} BM Units, "
          f"{sum(s.power_mw for s in keep):,.0f} MW")
    subprocess.run([sys.executable, "-m", "flake8", str(TARGET)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
