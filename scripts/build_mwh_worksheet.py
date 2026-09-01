"""Build the research worksheet for the census's missing energy capacities.

Energy capacity is the one field the free feeds will not give up. Elexon
publishes declared power and no duration; NESO's Capacity Market register
carries duration, but its unit names link to a BM Unit for only a minority of
sites; and the Renewable Energy Planning Database — despite listing 2,678
battery projects — has no MWh or duration column at all. It was checked rather
than assumed.

So the remaining sites can only be filled by reading what their operators
publish. That is legitimate evidence and a different kind of evidence, and the
difference has to survive contact with the analysis: a figure taken from a
developer's project page is not the same object as one settled by NESO, and a
notebook that mixes them without saying so is worse than one that leaves the
cell empty.

This script writes the worksheet that keeps them apart. One row per site the
census cannot price, pre-filled with everything already known — the BM Units,
declared MW, and whatever REPD offers by way of operator, commissioning date
and postcode, which is what makes the site findable — and blank columns for the
figure, its source and the date it was read. `fleet.research.coverage` reads the sheet
back and records the provenance beside every value, so the notebooks can report
"published by the operator" and "settled through a capacity agreement" as the
distinct claims they are.

Re-running never overwrites: existing rows keep their filled values and only
newly-missing sites are appended.

CLI::

    python scripts/build_mwh_worksheet.py
"""

from __future__ import annotations

import io
import logging
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fleet.research import census, coverage  # noqa: E402

logger = logging.getLogger(__name__)

WORKSHEET = REPO_ROOT / "data" / "reference" / "battery_energy_capacity.xlsx"

#: DESNZ Renewable Energy Planning Database, quarterly extract. Carries no MWh,
#: but its operator names, commissioning dates and postcodes are the fastest
#: route to the operator page that does.
REPD_CSV = (
    "https://assets.publishing.service.gov.uk/media/"
    "6a6cbdc00c36759b5ccaa305/REPD_Publication_Q2_2026.csv"
)

#: Columns the researcher fills. Everything else is pre-filled context.
ENTRY_COLUMNS = [
    "capacity_mwh",
    "duration_h",
    "source_type",
    "source_url",
    "read_on",
    "notes",
]

#: What may appear in ``source_type``. Recorded per row so a figure's standing
#: travels with it rather than being asserted once in a caption.
SOURCE_TYPES = (
    "operator",       # the operator's own project page or portfolio
    "press_release",  # EPC contractor, supplier or developer announcement
    "planning",       # a local authority planning portal document
    "other",
)


def fetch_repd_batteries() -> pd.DataFrame:
    """Battery projects from REPD, as research leads rather than as capacity.

    REPD has no MWh column — that is checked here, not assumed — so this
    contributes identity and location only.
    """
    response = requests.get(REPD_CSV, timeout=180, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    frame = pd.read_csv(io.BytesIO(response.content), encoding="cp1252", low_memory=False)

    if any("mwh" in c.lower() for c in frame.columns):
        logger.warning("REPD now has an MWh column — this script should use it")

    batteries = frame[
        frame["Technology Type"].astype(str).str.contains("Batter", case=False, na=False)
    ].copy()
    batteries["mw"] = pd.to_numeric(
        batteries["Installed Capacity (MWelec)"], errors="coerce"
    )
    keep = {
        "Site Name": "repd_site",
        "Operator (or Applicant)": "repd_operator",
        "Development Status (short)": "repd_status",
        "Operational": "repd_operational",
        "Post Code": "repd_postcode",
        "County": "repd_county",
    }
    available = {k: v for k, v in keep.items() if k in batteries.columns}
    out = batteries[list(available)].rename(columns=available)
    out["repd_mw"] = batteries["mw"]
    return out


def _distinctive_tokens(repd: pd.DataFrame, max_sites: int = 3) -> set[str]:
    """REPD name tokens rare enough to identify a site.

    "LANE" and "HILL" appear across hundreds of project names and match
    anything; a token carrying identity appears in a handful. Without this,
    "Tye Lane BESS" leads to "Tofts Lane" and "Ocker Hill" to "Sundridge Hill",
    which is worse than no lead because it looks like an answer.
    """
    counts: Counter = Counter()
    for name in repd["repd_site"].dropna():
        counts.update({t for t in census.normalise_name(name) if len(t) >= 4})
    return {token for token, n in counts.items() if n <= max_sites}


def _match_repd(
    site_name: str, declared_mw: float, repd: pd.DataFrame, distinctive: set[str]
) -> dict:
    """Best REPD lead for a census site: shared distinctive token, similar MW.

    Deliberately loose — the output is a starting point for a human, not a
    join. A wrong lead costs a moment; a missing one costs a search. But a lead
    matched on a word every third project shares is not loose, it is noise, so
    only tokens rare across REPD count.
    """
    tokens = {t for t in census.normalise_name(site_name) if t in distinctive}
    if not tokens or repd.empty:
        return {}

    best, best_score = None, 0.0
    for row in repd.itertuples():
        shared = tokens & census.normalise_name(row.repd_site)
        if not shared:
            continue
        score = len(shared)
        if pd.notna(row.repd_mw) and declared_mw:
            ratio = row.repd_mw / declared_mw
            if 0.5 <= ratio <= 2.0:
                score += 1
        if score > best_score:
            best, best_score = row, score

    if best is None:
        return {}
    return {
        "repd_site": best.repd_site,
        "repd_operator": getattr(best, "repd_operator", None),
        "repd_mw": best.repd_mw,
        "repd_status": getattr(best, "repd_status", None),
        "repd_operational": getattr(best, "repd_operational", None),
        "repd_postcode": getattr(best, "repd_postcode", None),
    }


def build(path: Path = WORKSHEET, refresh: bool = False) -> pd.DataFrame:
    """Write (or extend) the worksheet. Filled rows are never overwritten.

    Two kinds of row. **fill** — the site has no energy capacity from any
    source. **verify** — it has one from the Capacity Market, which is worth
    replacing where an operator publishes a physical figure.

    That second kind exists because the Capacity Market number answers a
    different question. Its MW is what the operator entered into the auction,
    averaging 86% of Elexon's declared capability and as little as half of it;
    its duration is a band the operator chose to bid into, and bidding a longer
    band means a firmer obligation under stress, so there is a standing reason
    to bid short. Both effects push the same way. Across the census, Capacity
    Market sites imply a median 1.32 hours where hand-verified and
    operator-published sites both imply about 2.

    The cost is not abstract: Lakeside's capacity agreement gives 149.85 MWh
    against the operator's 200, which overstates its cycling by a third — and
    cycles per day is what decides whether a site's inferred state of charge is
    usable at all. Registry rows are never listed, being hand-checked against
    the site and already the highest precedence.
    """
    table = coverage.coverage_table(refresh)
    needs_work = table[table["mwh_source"].isna() | table["mwh_source"].eq("capacity_market")]
    missing = needs_work.copy()

    try:
        repd = fetch_repd_batteries()
        logger.info("REPD: %d battery projects as leads", len(repd))
    except Exception as exc:  # noqa: BLE001 - leads are optional, the sheet is not
        logger.warning("REPD unavailable (%s) — writing the sheet without leads", exc)
        repd = pd.DataFrame()

    distinctive = _distinctive_tokens(repd) if not repd.empty else set()
    logger.info("%d REPD tokens are distinctive enough to match on", len(distinctive))

    rows = []
    for site in missing.itertuples():
        has_cm = site.mwh_source == "capacity_market"
        row = {
            "task": "verify" if has_cm else "fill",
            "asset_id": site.asset_id,
            "site_name": site.site_name,
            "lead_party": site.lead_party,
            "bmu_ids": ", ".join(site.bmu_ids),
            "declared_export_mw": round(float(site.declared_export_mw), 1),
            "connection_level": site.connection_level,
            "in_registry": bool(site.in_registry),
            # What is already held, so a researcher can see what they are
            # checking against rather than filling blind.
            "current_mwh": round(float(site.capacity_mwh), 1) if has_cm else None,
            "current_source": site.mwh_source if has_cm else None,
            "current_implied_h": (
                round(float(site.capacity_mwh) / float(site.declared_export_mw), 2)
                if has_cm and site.declared_export_mw else None
            ),
        }
        row.update(_match_repd(site.site_name, site.declared_export_mw, repd, distinctive))
        row.update({c: None for c in ENTRY_COLUMNS})
        rows.append(row)
    sheet = pd.DataFrame(rows)

    if path.exists():
        existing = pd.read_excel(path)
        filled = existing[existing["capacity_mwh"].notna()]
        if len(filled):
            sheet = sheet[~sheet["asset_id"].isin(filled["asset_id"])]
            sheet = pd.concat([filled, sheet], ignore_index=True)
            logger.info("Kept %d already-filled row(s)", len(filled))

    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.to_excel(path, index=False)
    logger.info("Wrote %s (%d rows)", path, len(sheet))
    return sheet


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sheet = build()
    todo = int(sheet["capacity_mwh"].isna().sum())
    with_lead = int(sheet.get("repd_site", pd.Series(dtype=object)).notna().sum())
    tasks = sheet["task"].value_counts().to_dict() if "task" in sheet else {}
    print(f"\n{WORKSHEET}")
    print(f"  {len(sheet)} sites, {todo} still to do "
          f"({tasks.get('fill', 0)} fill, {tasks.get('verify', 0)} verify a Capacity Market figure)")
    print(f"  {with_lead} have a REPD lead (operator, MW, commissioning date, postcode)")
    print(f"  fill: {', '.join(ENTRY_COLUMNS)}")
    print(f"  source_type must be one of: {', '.join(SOURCE_TYPES)}")


if __name__ == "__main__":
    main()
