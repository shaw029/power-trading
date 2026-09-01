"""How much of the GB battery fleet the curated registry actually represents.

:mod:`fleet.curated` is a hand-researched table of sites. :mod:`fleet.research.census`
reconstructs the population those sites are drawn from. This module is the arithmetic between them,
and it exists to replace an assumption with a measurement.

**It measures the curated registry specifically**, which is no longer a
reported population — it is the metadata table behind :mod:`fleet.registry`, the
superset the live dashboard renders. Notebook 06 marks ``in_dashboard`` on
:func:`coverage_table` and reports that instead; the functions here stay
hardwired to ``in_registry`` on purpose, because widening them would put a
population argument on a module the dashboard must not import.

The structure follows the four-tier method the analysis brief sets out:

**Tier 1 — coverage assessment.** :func:`coverage_table` returns one row per
known battery site, whether the registry contains it, and if not, *why*. The
reason matters more than the count: a site missing because it is 12 MW is a
deliberate scope decision, while a site missing because nobody added it is an
oversight, and the two support very different claims.

**Tier 2 — representativeness.** :func:`representativeness` measures coverage
three ways — by site count, by MW and by MWh. MW is the headline. Site count
flatters any sample that picked large assets, which this one did by design.
MWh is the most useful and the least available: durations are published only
through Capacity Market agreements, and those link to a BM Unit for a minority
of sites, so MWh coverage is reported over the subset where duration is known
and labelled as such rather than extrapolated.

**Tier 3 — characterising the gap.** :func:`gap_characterisation` compares
included against excluded sites by size, owner, region and connection level.
This is what converts a bare percentage into a defensible statement about
*direction* of bias — which is the difference between "the registry contains 23
sites" and "the registry captures X% of GB BM-registered battery MW but
under-represents sub-50 MW and distribution-connected assets".

**Scope, stated once.** The denominator is *BM-registered* batteries. Assets
traded behind an aggregator, VLP or supplier portfolio are physically real but
have no per-unit Elexon feed, so they can be neither dispatch-analysed nor
counted here — they are outside both numerator and denominator, and every
percentage below is a share of the BM-registered fleet, not of GB storage.
:func:`headline_claim` says so in the sentence it produces.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from fleet.research import census

logger = logging.getLogger(__name__)

#: Hand-researched energy capacities, built by ``scripts/build_mwh_worksheet.py``
#: and filled from what operators publish. Optional — everything works without
#: it, with fewer sites priced.
ENERGY_WORKSHEET = (
    Path(__file__).resolve().parents[1] / "data" / "reference" / "battery_energy_capacity.xlsx"
)

#: Accepted values of the worksheet's ``source_type``. A figure's standing
#: travels with it rather than being asserted once in a caption.
WORKSHEET_SOURCE_TYPES = (
    "operator", "corporate", "press_release", "planning", "other"
)

#: How far a worksheet row's implied duration (MWh ÷ declared MW) may sit from
#: the duration the researcher recorded before the row is rejected.
#:
#: This is the check that makes operator-published capacity usable rather than
#: merely plausible. Declared MW comes from Elexon and the MWh from the
#: operator, so agreement between them is genuine corroboration from
#: independent places. Disagreement is almost always a boundary problem: the
#: operator quotes a project, a portfolio or a phase, and the BM Unit is only
#: part of it. Wolverhampton West publishes 310 MWh at 2.4 hours, implying a
#: 129 MW project, against a 56 MW BM Unit — believed, it would make the site a
#: five-and-a-half-hour battery.
DURATION_AGREEMENT = 0.25

#: Implied duration above which a row is loaded but flagged for review.
#:
#: The agreement check above compares a row's implied duration against the one
#: the researcher recorded, which catches a figure describing a different asset
#: — but only while the two are derived independently. Record the duration *from*
#: the MWh and the comparison becomes circular and always passes. Wolverhampton
#: West did exactly that between two revisions: 310 MWh first recorded at 2.4 h
#: (rejected), then at 5.5 h (accepted), with the same figure underneath.
#:
#: So a second check is needed that does not consult the researcher at all, and
#: asks instead whether GB batteries have this duration. Every priced census
#: site sits at or below 2.48 h and none exceeds 3. Four hours is set well clear
#: of that, since genuinely longer batteries are being built and this must flag
#: rather than reject: NESO's register does list units at 5.5 h. A flag says
#: "cite this one precisely", not "this is wrong".
DURATION_REVIEW_H = 4.0

#: A curated-registry inclusion criterion: sites below this are out of scope by
#: design, not by accident. Mirrors ``fleet.registry``'s stated ~35 MW floor
#: (its smallest member, Contego, is 34 MW).
REGISTRY_SIZE_FLOOR_MW = 34.0

#: A Capacity Market match is only believed when its stated MW is in this
#: multiple of the BM Unit's declared export. CM connection capacity and Elexon
#: declared capability differ legitimately — observed matches run from about
#: 0.6x to 1.1x — but a name-token match to a wholly different site does not
#: land anywhere near. "The Drove" (6 MW) matching "GR - Hightown Drove" (90 MW,
#: 360 MWh) is the case this rejects: believed, it implies a 60-hour battery.
CM_MW_AGREEMENT = (0.4, 2.5)

#: Size bands for the Tier 3 comparison, in MW.
SIZE_BANDS = [(0, 20), (20, 50), (50, 100), (100, 200), (200, 10_000)]


def _size_band(mw: float) -> str:
    for low, high in SIZE_BANDS:
        if low <= mw < high:
            return f"{low}-{high} MW" if high < 10_000 else f"{low}+ MW"
    return "unknown"


def _cm_lookup(cm: pd.DataFrame) -> tuple[dict, dict]:
    """Index Capacity Market storage units by BMU root and distinctive token.

    Two paths, because CM unit names are inconsistent: some *are* the BM Unit
    root ("COALB1" for ``COALB-1``), most are project names ("Little Raith
    ESS"). A token is only used for matching when it is distinctive — present
    in at most three CM units — so a common word cannot marry two unrelated
    sites. The most recent delivery year wins, so a site's duration reflects
    its current agreement rather than a superseded one.
    """
    usable = cm[cm["cm_power_mw"].notna() & cm["duration_h"].notna()].copy()
    usable = usable.sort_values("delivery_year")  # later rows overwrite earlier

    token_counts: Counter = Counter()
    tokens = [census.normalise_name(n) for n in usable["cm_unit_name"].fillna("")]
    for tok in tokens:
        token_counts.update(tok)

    by_root: dict[str, dict] = {}
    by_token: dict[str, dict] = {}
    for (_, row), tok in zip(usable.iterrows(), tokens):
        record = {
            "cm_unit_name": row["cm_unit_name"],
            "cm_power_mw": row["cm_power_mw"],
            "duration_h": row["duration_h"],
            "cm_capacity_mwh": row["cm_capacity_mwh"],
            "registered_holder": row.get("registered_holder"),
            "connection_level": row.get("connection_level"),
            "delivery_year": row.get("delivery_year"),
        }
        normalised = re.sub(r"[^A-Z0-9]", "", str(row["cm_unit_name"]).upper())
        for key in (normalised, re.sub(r"\d+$", "", normalised)):
            if len(key) >= 4:
                by_root[key] = record
        for t in tok:
            if len(t) >= 5 and token_counts[t] <= 3:
                by_token[t] = record
    return by_root, by_token


def enrich_with_capacity_market(sites: pd.DataFrame, cm: pd.DataFrame) -> pd.DataFrame:
    """Attach Capacity Market duration/MWh to census sites where it can be matched.

    Adds ``capacity_mwh`` and ``mwh_source``. The curated registry's own
    hand-verified MWh takes precedence where it exists, because it was checked
    against the site rather than inferred from an agreement; the Capacity
    Market fills in what it can behind that; the rest stay null and are counted
    as unknown rather than guessed.
    """
    by_root, by_token = _cm_lookup(cm)
    sites = sites.copy()

    matched: list[dict | None] = []
    for row in sites.itertuples():
        root = row.asset_id.removeprefix("GB-BESS-")
        record = by_root.get(root)
        if record is None:
            for token in census.normalise_name(row.site_name):
                record = by_token.get(token)
                if record is not None:
                    break
        matched.append(record)

    # Reject a match whose stated power disagrees with the BM Unit's, and any
    # that implies a duration no battery has. Both are name-collision symptoms,
    # and an unmatched site is far less damaging than a wrong denominator.
    low, high = CM_MW_AGREEMENT
    checked: list[dict | None] = []
    for record, declared in zip(matched, sites["declared_export_mw"]):
        if record is None or not declared:
            checked.append(None)
            continue
        ratio = record["cm_power_mw"] / declared
        implied_h = record["cm_capacity_mwh"] / declared
        if not (low <= ratio <= high) or implied_h > census.MAX_BATTERY_DURATION_H:
            checked.append(None)
            continue
        checked.append(record)
    matched = checked

    sites["cm_unit_name"] = [m["cm_unit_name"] if m else None for m in matched]
    sites["cm_power_mw"] = [m["cm_power_mw"] if m else float("nan") for m in matched]
    sites["cm_duration_h"] = [m["duration_h"] if m else float("nan") for m in matched]
    cm_mwh = pd.Series([m["cm_capacity_mwh"] if m else float("nan") for m in matched])

    sites["capacity_mwh"] = sites["registry_capacity_mwh"].astype(float)
    sites["mwh_source"] = pd.Series(
        ["registry" if pd.notna(v) else None for v in sites["registry_capacity_mwh"]],
        index=sites.index,
    )
    fill = sites["capacity_mwh"].isna() & cm_mwh.notna()
    sites.loc[fill, "capacity_mwh"] = cm_mwh[fill].to_numpy()
    sites.loc[fill, "mwh_source"] = "capacity_market"
    return sites


def load_energy_worksheet(path: Path | None = None) -> pd.DataFrame:
    """Hand-researched energy capacities, with the provenance of each.

    Returns an empty frame when the worksheet is absent, so the census works
    unchanged without it — the sheet adds sites that can be priced, it is never
    load-bearing.

    Rows are validated rather than trusted. A figure needs a positive MWh, a
    recognised ``source_type`` and a ``source_url``, and must imply a duration a
    battery could actually have; anything failing is dropped with a warning. The
    citation requirement is the point of the exercise. A number read off a
    developer's page and a number settled through a capacity agreement are
    different kinds of claim, and the analysis is allowed to say which it has
    only if the sheet records it.
    """
    path = path or ENERGY_WORKSHEET
    if not path.exists():
        return pd.DataFrame(columns=["asset_id", "capacity_mwh", "source_type", "source_url"])

    sheet = pd.read_excel(path)
    sheet["capacity_mwh"] = pd.to_numeric(sheet.get("capacity_mwh"), errors="coerce")
    filled = sheet[sheet["capacity_mwh"].notna()].copy()
    if filled.empty:
        return filled

    ok = filled["capacity_mwh"] > 0
    ok &= filled.get("source_type", pd.Series(dtype=object)).isin(WORKSHEET_SOURCE_TYPES)
    ok &= filled.get("source_url", pd.Series(dtype=object)).astype(str).str.strip().ne("")
    ok &= filled.get("source_url", pd.Series(dtype=object)).notna()

    declared = pd.to_numeric(filled.get("declared_export_mw"), errors="coerce")
    implied = filled["capacity_mwh"] / declared.replace(0, pd.NA)
    ok &= implied.isna() | (implied <= census.MAX_BATTERY_DURATION_H)

    # The published MWh must agree with the duration the researcher recorded,
    # given Elexon's declared MW. Two independent sources agreeing is what makes
    # the figure evidence; disagreeing, one of them is describing a different
    # asset boundary and neither can be attributed to this BM Unit.
    stated = pd.to_numeric(filled.get("duration_h"), errors="coerce")
    disagreement = (implied - stated).abs() / stated.replace(0, pd.NA)
    ok &= disagreement.isna() | (disagreement <= DURATION_AGREEMENT)

    flagged = implied > DURATION_REVIEW_H
    for row in filled[ok & flagged].itertuples():
        logger.warning(
            "Worksheet row for %s (%s) needs review: %.0f MWh over %.1f MW declared "
            "implies %.1f h, longer than any priced census site. Self-consistent with "
            "the duration recorded, so the agreement check cannot judge it — confirm "
            "the figure covers this BM Unit and not the wider project.",
            row.asset_id, getattr(row, "site_name", "?"),
            getattr(row, "capacity_mwh", float("nan")),
            getattr(row, "declared_export_mw", float("nan")),
            getattr(row, "capacity_mwh", float("nan"))
            / (getattr(row, "declared_export_mw", float("nan")) or float("nan")),
        )

    for row in filled[~ok].itertuples():
        imp = getattr(row, "capacity_mwh", float("nan")) / (
            getattr(row, "declared_export_mw", float("nan")) or float("nan")
        )
        logger.warning(
            "Worksheet row rejected for %s (%s): %.0f MWh over %.1f MW declared implies "
            "%.2f h against %s h recorded — check whether the published figure covers "
            "the whole project rather than this BM Unit",
            row.asset_id, getattr(row, "site_name", "?"),
            getattr(row, "capacity_mwh", float("nan")),
            getattr(row, "declared_export_mw", float("nan")),
            imp, getattr(row, "duration_h", "?"),
        )
    out = filled[ok].copy()
    out["mwh_needs_review"] = (out["capacity_mwh"] / declared[ok]) > DURATION_REVIEW_H
    return out


def apply_energy_worksheet(sites: pd.DataFrame, path: Path | None = None) -> pd.DataFrame:
    """Fill energy capacity from the worksheet, recording where each came from.

    Precedence is registry, then worksheet, then Capacity Market. The registry's
    figures were checked against the site itself. A worksheet figure carries a
    citation and a read date, and is usually the operator's own nameplate. The
    Capacity Market's duration is a contractual band — 1h, 1.5h, 2h — so it is
    the coarsest of the three and yields to a specific published figure.
    """
    worksheet = load_energy_worksheet(path)
    if worksheet.empty:
        return sites

    sites = sites.copy()
    by_asset = worksheet.set_index("asset_id")
    for column in ("capacity_mwh", "mwh_source"):
        if column not in sites:
            sites[column] = None

    for i, asset in sites["asset_id"].items():
        if asset not in by_asset.index:
            continue
        if sites.at[i, "mwh_source"] == "registry":
            continue
        row = by_asset.loc[asset]
        sites.at[i, "capacity_mwh"] = float(row["capacity_mwh"])
        sites.at[i, "mwh_source"] = str(row["source_type"])
        sites.at[i, "mwh_source_url"] = row.get("source_url")
        sites.at[i, "mwh_needs_review"] = bool(row.get("mwh_needs_review", False))
    return sites


def coverage_table(refresh: bool = False) -> pd.DataFrame:
    """Tier 1 — one row per known battery site, with the reason it is missing.

    ``missing_reason`` is null for sites the registry contains. For the rest it
    separates a scope decision from an omission:

    ``below size floor``
        Smaller than the registry's stated ~35 MW threshold, so excluded by
        design.
    ``not curated``
        Meets every stated inclusion criterion and is simply absent — the
        genuine gap, and the honest count of what the registry is missing.
    """
    sites = census.census_sites(refresh)
    sites = enrich_with_capacity_market(sites, census.fetch_cm_storage(refresh))
    sites = apply_energy_worksheet(sites)

    sites["size_band"] = sites["declared_export_mw"].map(_size_band)
    sites["missing_reason"] = None
    absent = ~sites["in_registry"]
    sites.loc[absent & (sites["declared_export_mw"] < REGISTRY_SIZE_FLOOR_MW), "missing_reason"] = (
        "below size floor"
    )
    sites.loc[absent & (sites["declared_export_mw"] >= REGISTRY_SIZE_FLOOR_MW), "missing_reason"] = (
        "not curated"
    )
    return sites


def representativeness(table: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tier 2 — registry coverage of the census by site count, MW and MWh.

    Returns one row per basis with the numerator, denominator and percentage.
    The MWh row is computed only over sites whose energy capacity is known from
    a source, and reports that subset size, so it can never be mistaken for a
    complete figure.
    """
    table = coverage_table() if table is None else table
    included = table[table["in_registry"]]

    known_mwh = table[table["capacity_mwh"].notna()]
    known_mwh_included = known_mwh[known_mwh["in_registry"]]

    rows = [
        {
            "basis": "sites",
            "registry": float(len(included)),
            "census": float(len(table)),
            "coverage_pct": round(100.0 * len(included) / len(table), 1) if len(table) else 0.0,
            "note": "every BM-registered battery site",
        },
        {
            "basis": "MW (declared export)",
            "registry": round(included["declared_export_mw"].sum(), 1),
            "census": round(table["declared_export_mw"].sum(), 1),
            "coverage_pct": round(
                100.0 * included["declared_export_mw"].sum() / table["declared_export_mw"].sum(), 1
            ),
            "note": "the headline figure",
        },
        {
            "basis": "MWh (where known)",
            "registry": round(known_mwh_included["capacity_mwh"].sum(), 1),
            "census": round(known_mwh["capacity_mwh"].sum(), 1),
            "coverage_pct": round(
                100.0 * known_mwh_included["capacity_mwh"].sum() / known_mwh["capacity_mwh"].sum(),
                1,
            )
            if len(known_mwh)
            else 0.0,
            "note": (
                f"duration known for {len(known_mwh_included)}/{len(included)} registry "
                f"vs {len(known_mwh) - len(known_mwh_included)}/{len(table) - len(included)} "
                f"other sites — biased upward, treat as a ceiling"
            ),
        },
    ]
    return pd.DataFrame(rows).set_index("basis")


def gap_characterisation(table: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Tier 3 — how included sites differ from excluded ones.

    Returns a breakdown per dimension (size band, connection level, region,
    owner), each showing site count and MW split between in-registry and out.
    The ``coverage_pct`` column within each dimension is what supports a claim
    about the *direction* of the registry's bias rather than only its size.
    """
    table = coverage_table() if table is None else table
    out: dict[str, pd.DataFrame] = {}

    dimensions = {
        "size_band": "size_band",
        "connection_level": "connection_level",
        "region": "gsp_group",
        "owner": "lead_party",
    }
    for label, column in dimensions.items():
        grouped = table.groupby(table[column].fillna("unknown"), dropna=False)
        frame = pd.DataFrame(
            {
                "sites": grouped.size(),
                "sites_in_registry": grouped["in_registry"].sum(),
                "mw": grouped["declared_export_mw"].sum().round(1),
                "mw_in_registry": grouped.apply(
                    lambda g: g.loc[g["in_registry"], "declared_export_mw"].sum(),
                    include_groups=False,
                ).round(1),
            }
        )
        frame["coverage_pct"] = (100.0 * frame["mw_in_registry"] / frame["mw"]).round(1)
        out[label] = frame.sort_values("mw", ascending=False)

    return out


def headline_claim(table: pd.DataFrame | None = None) -> str:
    """The single defensible sentence the coverage work exists to produce.

    Stated as a share of the BM-registered fleet, with the direction of the
    residual bias attached, because a percentage without a direction invites
    exactly the criticism the analysis is trying to answer.
    """
    table = coverage_table() if table is None else table
    stats = representativeness(table)
    mw_pct = stats.loc["MW (declared export)", "coverage_pct"]

    by_band = gap_characterisation(table)["size_band"]
    weakest = by_band[by_band["mw"] > 0].sort_values("coverage_pct").head(2)
    bands = " and ".join(str(i) for i in weakest.index)

    n_sites = int(stats.loc["sites", "registry"])
    n_census = int(stats.loc["sites", "census"])
    return (
        f"The registry's {n_sites} sites capture {mw_pct}% of GB BM-registered "
        f"operational battery MW ({n_census} sites in total), and "
        f"under-represent {bands} assets. Batteries traded behind aggregator, "
        f"VLP or supplier portfolios have no per-unit settlement data and are "
        f"outside this denominator entirely."
    )
