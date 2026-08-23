"""Per-unit ancillary service revenue for the GB battery fleet.

The project prices two revenue streams: the wholesale position at MID, and
Balancing Mechanism cashflows through ``EBOCF``. For a GB battery that is an
incomplete picture and known to be so — frequency response and reserve have
historically been the *dominant* stream, and a site that looks unprofitable on
wholesale plus BM alone may simply be earning elsewhere. This module adds that
third stream at site level, so a revenue stack can be stated rather than
assumed.

**It joins cleanly, which is the reason this is possible at all.** NESO's
auction results identify the winning unit by its National Grid BM Unit name —
``KILSB-5``, ``CLAYB-1``, ``THURB-3`` — which is exactly what
:func:`fleet.census.asset_id` is keyed on. Ancillary revenue therefore attaches
to the same persistent asset ID as dispatch and BM cashflow, with no fuzzy
matching anywhere in the path. Aggregator-run units use house codes instead
(``AG-GBL0EN``, ``HAB-15``, ``ANSC-001``); those cannot resolve to a site and
are reported as an unmatched total rather than silently dropped or force-fitted.

**The history is fragmented, and the fragmentation is the headline caveat.**
NESO replaced its auction platform twice over the analysis window and published
per-unit results under three different schemas, with real gaps between them:

======================================  =========================  ===================
Source                                  Period                     Services
======================================  =========================  ===================
DC, DR & DM Results By Unit             2021-09-16 → 2023-11-02    Response (DC/DR/DM)
NESO Balancing-Reserve Results By Unit  2024-03-12 → 2025-10-29    Balancing Reserve
NESO Response-Reserve Results By Unit   2026-03-31 → present       Response, Quick and
(Enduring Auction Capability)                                      Slow Reserve
======================================  =========================  ===================

Nothing recovers the intervening months — NESO did not publish per-unit results
for them. :func:`coverage_by_month` therefore accompanies every revenue figure,
and no total is annualised or averaged across a gap. A stack quoted over a
window the feed does not cover is worse than no stack at all, because it looks
authoritative.

**Revenue arithmetic.** Clearing prices are £/MW/h and volumes are MW, but the
delivery block is four hours under the EFA-based schema and half an hour under
the auction platforms. Block length is therefore computed from each record's
own start and end timestamps rather than assumed, so the two eras are directly
comparable.

Nothing here is imported by the live dashboard — this is full-profile only.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from dataclasses import dataclass

import pandas as pd
import requests

from fleet import census
from src.utils.config import RAW_DATA_DIR

logger = logging.getLogger(__name__)

_CKAN_SQL = "https://api.neso.energy/api/3/action/datastore_search_sql"
_CACHE_DIR = os.path.join(RAW_DATA_DIR, "ANCILLARY")
_PAGE = 32000
_TIMEOUT_S = 180


@dataclass(frozen=True)
class AncillarySource:
    """One NESO per-unit auction results table and how to read it."""

    name: str
    resource_id: str
    #: Column names in this table's own schema: unit, service, volume, price,
    #: block start, block end.
    columns: tuple[str, str, str, str, str, str]
    era: str
    #: Column carrying a technology label, where the table has one. Sources
    #: without it cannot be filtered to batteries server-side, so their rows are
    #: kept only where the unit resolves to a census site — see
    #: :data:`SITE_ATTRIBUTED_ONLY`.
    technology: str | None = None
    #: Column carrying settled revenue directly. NESO states it for the
    #: Dynamic Containment masterdata, and a published figure beats
    #: reconstructing one from volume, price and block length.
    revenue: str | None = None
    #: Restrict to accepted bids, for tables that also list rejected ones.
    accepted_filter: str | None = None


#: Sources with no technology column contribute only revenue that resolves to a
#: census site. Their fleet-wide totals would otherwise include gas, DSR and
#: everything else in the same auction, which would corrupt the unattributed
#: buckets rather than fill them.
SITE_ATTRIBUTED_ONLY = "site-attributed only (source has no technology label)"


#: The three per-unit tables, oldest first. Their periods do not overlap and do
#: not join up; see the module docstring.
SOURCES: tuple[AncillarySource, ...] = (
    AncillarySource(
        name="response_dc_dr_dm",
        resource_id="ddc4afde-d2bd-424d-891c-56ad49c13d1a",
        columns=(
            "Unit Name",
            "Service",
            "Cleared Volume",
            "Clearing Price",
            "Delivery Start",
            "Delivery End",
        ),
        era="DC/DR/DM (2021-09 → 2023-11)",
        technology="Technology Type",
    ),
    AncillarySource(
        name="ffr_phase2",
        resource_id="15d7fa42-1c8d-4a79-86f8-890cf9228794",
        columns=(
            "Unit Name",
            "Service",
            "Cleared Volume",
            "Clearing Price",
            "Delivery Start",
            "Delivery End",
        ),
        era="FFR Phase 2 (2019-12 → 2020-04)",
    ),
    AncillarySource(
        name="dc_masterdata",
        resource_id="0b8dbc3c-e05e-44a4-b855-7dd1aa079c68",
        columns=(
            "Response Unit",
            "Market Name",
            "Volume Accepted",
            "Availability Fee",
            "Delivery Start UTC",
            "Delivery End UTC",
        ),
        era="Dynamic Containment masterdata (2020-10 → 2021-09)",
        revenue="Total Cost",
        accepted_filter="Accepted/Rejected",
    ),
    AncillarySource(
        name="balancing_reserve",
        resource_id="5d8e47be-e262-4398-89b0-6f93f636faf6",
        columns=(
            "auctionUnit",
            "serviceType",
            "executedQuantity",
            "clearingPrice",
            "deliveryStart",
            "deliveryEnd",
        ),
        era="Balancing Reserve (2024-03 → 2025-10)",
        technology="technologyType",
    ),
    AncillarySource(
        name="eac_response_reserve",
        resource_id="a63ab354-7e68-44c2-ad96-c6f920c30e85",
        columns=(
            "auctionUnit",
            "serviceType",
            "executedQuantity",
            "clearingPrice",
            "deliveryStart",
            "deliveryEnd",
        ),
        era="EAC Response/Reserve (2026-03 → present)",
        technology="technologyType",
    ),
)

#: The technology label is inconsistent across eras — "Batteries", "Battery",
#: "BATTERY", "BESS" and "BM (SVA/VLP/Battery)" all appear — so the filter
#: matches the stem rather than any exact spelling.
_BATTERY_PREDICATE = "(\"{col}\" ILIKE '%batter%' OR \"{col}\" ILIKE '%bess%')"

#: Aggregator and portfolio house codes, which name a trading unit rather than
#: a site and therefore cannot resolve to an asset.
_HOUSE_CODE_RE = re.compile(r"^(AG-|HAB-|ANSC-|FLEX|VLP|POR-)", re.I)


def _sql_paged(sql_without_limit: str) -> list[dict]:
    """Run a fixed CKAN SQL query, paging until it stops returning rows."""
    records: list[dict] = []
    offset = 0
    while True:
        sql = f"{sql_without_limit} LIMIT {_PAGE} OFFSET {offset}"
        response = requests.get(_CKAN_SQL, params={"sql": sql}, timeout=_TIMEOUT_S)
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            raise ValueError(f"CKAN SQL error: {str(body.get('error'))[:200]}")
        page = body["result"]["records"]
        records.extend(page)
        if len(page) < _PAGE:
            return records
        offset += len(page)


def _cached_json(name: str, builder, refresh: bool = False):
    """Fetch ``name`` at most once per day, alongside the ancillary parquet."""
    path = os.path.join(_CACHE_DIR, f"{name}_{dt.date.today().isoformat()}.json")
    if not refresh and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    payload = builder()
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp)
    return payload


#: Unit names that say battery outright, for tables that carry no technology
#: label. ``DBESS-22`` is unmistakable and appears in no labelled table.
_BATTERY_UNIT_RE = re.compile(r"BESS|BATT", re.I)


def battery_units(refresh: bool = False) -> set[str]:
    """Every auction unit known to be a battery, however that is known.

    NESO labels technology in its newer results tables and not in its older
    ones, so the older eras cannot be filtered server-side. This assembles the
    answer from the tables that *do* label it, and is the reason FFR Phase 2 and
    the Dynamic Containment masterdata can contribute battery revenue rather
    than the whole auction's.

    Three signals, unioned:

    * the unit is labelled ``Batteries`` in a technology-labelled table — NESO's
      own word, and the strongest;
    * its name says so (``DBESS-22``), which catches units that never appear in
      a labelled table;
    * it resolves to a site in the census, which catches BM-named units whose
      auction alias never carried a label.

    Anything outside the union is left out. The cost is under-counting a
    battery that never identified itself anywhere; the alternative is counting
    gas and DSR as battery revenue, which is worse in a study about batteries.
    """

    def build() -> list[str]:
        names: set[str] = set()
        for source in SOURCES:
            if not source.technology:
                continue
            unit = source.columns[0]
            sql = (
                f'SELECT DISTINCT "{unit}" AS u FROM "{source.resource_id}" '
                f"WHERE {_BATTERY_PREDICATE.format(col=source.technology)}"
            )
            names.update(str(r.get("u", "")).strip() for r in _sql_paged(sql))
        names.discard("")
        return sorted(names)

    labelled = set(_cached_json("battery_units", build, refresh))
    census_roots = {
        a.removeprefix("GB-BESS-") for a in census.census_sites(refresh)["asset_id"]
    }
    return labelled | {r for r in census_roots}


def _is_battery(units: pd.Series, known: set[str]) -> pd.Series:
    """Battery test for a table with no technology column."""
    text = units.astype(str).str.strip()
    return (
        text.isin(known)
        | text.str.contains(_BATTERY_UNIT_RE)
        | text.map(lambda u: census.bmu_root(u) in known)
    )


def _fetch_source(source: AncillarySource) -> pd.DataFrame:
    """Battery rows of one source, normalised to the common schema.

    Only the columns the analysis needs are selected, and where the table
    carries a technology label the battery filter runs server-side, so a table
    of a million rows transfers as the hundred thousand that matter.

    The older tables — FFR Phase 2 and the Dynamic Containment masterdata —
    have no technology column. They are fetched whole and marked
    ``site_attributed_only``, because their fleet-wide totals would otherwise
    fold in gas, DSR and every other technology bidding into the same auction.
    """
    unit, service, volume, price, start, end = source.columns
    wanted = list(source.columns)
    for extra in (source.technology, source.revenue, source.accepted_filter):
        if extra:
            wanted.append(extra)

    projection = ", ".join(f'"{c}"' for c in dict.fromkeys(wanted))
    where = []
    if source.technology:
        where.append(_BATTERY_PREDICATE.format(col=source.technology))
    if source.accepted_filter:
        where.append(f"\"{source.accepted_filter}\" ILIKE 'accepted'")
    clause = f" WHERE {' AND '.join(where)}" if where else ""

    frame = pd.DataFrame(_sql_paged(f'SELECT {projection} FROM "{source.resource_id}"{clause}'))
    if frame.empty:
        return frame

    # A table with no technology column arrives carrying every technology in its
    # auction, so the battery test is applied here instead of in the query.
    if source.technology is None:
        frame = frame[_is_battery(frame[unit], battery_units())]
        if frame.empty:
            return frame

    out = pd.DataFrame(
        {
            "unit": frame[unit].astype(str).str.strip(),
            "service": frame[service].astype(str).str.strip(),
            "volume_mw": pd.to_numeric(frame[volume], errors="coerce"),
            "price_gbp_mw_h": pd.to_numeric(frame[price], errors="coerce"),
            "block_start": pd.to_datetime(frame[start], utc=True, errors="coerce"),
            "block_end": pd.to_datetime(frame[end], utc=True, errors="coerce"),
        }
    )
    out["stated_revenue_gbp"] = (
        pd.to_numeric(frame[source.revenue], errors="coerce")
        if source.revenue
        else float("nan")
    )
    out["source"] = source.name
    out["era"] = source.era
    out["site_attributed_only"] = source.technology is None
    return out.dropna(subset=["block_start", "block_end"])


def _cache_path(name: str, date: dt.date) -> str:
    return os.path.join(_CACHE_DIR, f"{name}_{date.isoformat()}.parquet")


def fetch_all(refresh: bool = False) -> pd.DataFrame:
    """Every battery ancillary result across all three eras, one row per block.

    Cached as parquet once per fetch date. The raw tables total roughly two
    million rows; only the battery subset is transferred and it is stored in a
    columnar format, so the cache stays a few tens of megabytes rather than the
    hundreds a raw JSON copy would take.
    """
    path = _cache_path("battery_ancillary", dt.date.today())
    if not refresh and os.path.exists(path):
        return pd.read_parquet(path)

    frames = []
    for source in SOURCES:
        frame = _fetch_source(source)
        logger.info("%s: %d battery rows", source.name, len(frame))
        if not frame.empty:
            frames.append(frame)

    combined = (
        pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    )
    if not combined.empty:
        # Block length varies by era (4h EFA blocks vs 30-minute auction
        # blocks), so it is read off each record rather than assumed.
        hours = (combined["block_end"] - combined["block_start"]).dt.total_seconds() / 3600.0
        combined["block_hours"] = hours
        # NESO states settled revenue outright for the Dynamic Containment
        # masterdata. A published figure beats one reconstructed from volume,
        # price and block length, so it is preferred where it exists.
        derived = combined["volume_mw"] * combined["price_gbp_mw_h"] * hours
        combined["revenue_gbp"] = combined["stated_revenue_gbp"].fillna(derived)
        combined["date"] = combined["block_start"].dt.date
        combined["asset_id"] = [
            None if _HOUSE_CODE_RE.match(u) else census.asset_id(u)
            for u in combined["unit"]
        ]

    os.makedirs(_CACHE_DIR, exist_ok=True)
    combined.to_parquet(path, index=False)
    logger.info("Cached %s (%d rows)", path, len(combined))
    return combined


def site_daily_revenue(
    start: dt.date | None = None,
    end: dt.date | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """Ancillary revenue per asset per day per service.

    One row per unit per day per service, with a ``unit_class`` saying whether
    that unit is a site at all. Rows whose unit is an aggregator house code or a
    VLP/supplier route carry a null or unmatched ``asset_id`` and are retained —
    :func:`unmatched_summary` sizes them — so the fleet total and the sum of the
    sites it resolves never silently disagree.
    """
    frame = fetch_all(refresh)
    if frame.empty:
        return frame
    if start is not None:
        frame = frame[frame["date"] >= start]
    if end is not None:
        frame = frame[frame["date"] <= end]

    grouped = (
        frame.groupby(
            ["asset_id", "unit", "date", "service", "source", "era",
             "site_attributed_only"],
            dropna=False,
        )
        .agg(
            revenue_gbp=("revenue_gbp", "sum"),
            mean_price_gbp_mw_h=("price_gbp_mw_h", "mean"),
            mw_hours=("volume_mw", "sum"),
            blocks=("revenue_gbp", "size"),
        )
        .reset_index()
    )
    # Carried on the frame so no caller has to remember that half of ancillary
    # revenue is earned by units which are not sites.
    grouped["unit_class"] = classify_units(grouped["unit"], refresh=refresh)

    # Sources with no technology label cover every technology in their auction,
    # so only their census-site rows are meaningful; anything else they carry is
    # some other plant and must not land in the unattributed buckets.
    drop = grouped["site_attributed_only"] & (grouped["unit_class"] != "census site")
    if drop.any():
        grouped = grouped[~drop]
    return grouped.sort_values(["date", "revenue_gbp"], ascending=[True, False])


def coverage_by_month(
    start: dt.date, end: dt.date, refresh: bool = False
) -> pd.DataFrame:
    """Which months have per-unit ancillary data at all, and from which era.

    This is the table that must sit beside any revenue figure, and it carries
    two distinct warnings rather than one.

    A month absent here is a month NESO never published per-unit results for —
    not a month in which batteries earned nothing.

    More subtly, a month *present* is not necessarily comparable to another
    present month, because the eras cover different **services**. The
    2024-03 → 2025-10 stretch has only Balancing Reserve, a minor product;
    reading its £0.3M/month against the £7.8M/month of the DC/DR/DM era would
    show a 96% collapse that is entirely an artefact of which auction NESO
    happened to publish. ``services`` and ``comparable_group`` exist so that
    comparison can be refused explicitly: only rows sharing a
    ``comparable_group`` are like-for-like.
    """
    frame = fetch_all(refresh)
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    out = pd.DataFrame(index=months.astype(str))
    out.index.name = "month"

    if frame.empty:
        out["days_with_data"] = 0
        out["era"] = None
        return out

    stamped = frame.copy()
    # Months are attributed in UTC, consistently with ``date`` above. Made
    # explicit because to_period would otherwise drop the timezone silently.
    stamped["month"] = (
        stamped["block_start"].dt.tz_convert("UTC").dt.tz_localize(None)
        .dt.to_period("M").astype(str)
    )
    by_month = stamped.groupby("month").agg(
        days_with_data=("date", "nunique"),
        revenue_gbp=("revenue_gbp", "sum"),
        units=("unit", "nunique"),
    )
    eras = stamped.groupby("month")["era"].agg(lambda s: ", ".join(sorted(set(s))))
    services = stamped.groupby("month")["service"].agg(
        lambda s: ", ".join(sorted(set(s)))
    )

    out = out.join(by_month).join(eras).join(services.rename("services"))
    out["days_with_data"] = out["days_with_data"].fillna(0).astype(int)
    out["days_in_month"] = [pd.Period(m).days_in_month for m in out.index]
    out["covered"] = out["days_with_data"] > 0
    # Months sharing a service set are like-for-like; months that do not are
    # not, however complete each looks on its own.
    out["comparable_group"] = out["services"].fillna("none")
    return out


def comparable_windows(coverage: pd.DataFrame) -> pd.DataFrame:
    """Contiguous month runs that share a service set, with their totals.

    The unit of legitimate comparison. A trend drawn across two of these runs
    is measuring NESO's publishing history, not the market.
    """
    covered = coverage[coverage["covered"]].copy()
    if covered.empty:
        return covered
    block = (covered["comparable_group"] != covered["comparable_group"].shift()).cumsum()
    return (
        covered.assign(block=block)
        .groupby("block")
        .agg(
            first_month=("services", lambda s: s.index[0]),
            last_month=("services", lambda s: s.index[-1]),
            months=("services", "size"),
            services=("services", "first"),
            revenue_gbp=("revenue_gbp", "sum"),
            era=("era", "first"),
        )
        .reset_index(drop=True)
    )


def unmatched_summary(daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """Revenue that cannot be attributed to a site, by era.

    Aggregator and portfolio units trade real batteries but name a commercial
    unit, not an asset. Quantifying them is the honest alternative to dropping
    them: it states how much of the fleet's ancillary earnings the site-level
    view cannot see.
    """
    daily = site_daily_revenue() if daily is None else daily
    if daily.empty:
        return daily
    flagged = daily.assign(attributed=daily["asset_id"].notna())
    summary = flagged.groupby(["era", "attributed"])["revenue_gbp"].sum().unstack(
        fill_value=0.0
    )
    summary.columns = ["unattributed_gbp", "attributed_gbp"][: len(summary.columns)]
    total = summary.sum(axis=1)
    summary["attributed_pct"] = (
        100.0 * summary.get("attributed_gbp", 0.0) / total.replace(0, pd.NA)
    ).round(1)
    return summary


def with_census(daily: pd.DataFrame | None = None, refresh: bool = False) -> pd.DataFrame:
    """Attach census site identity to per-asset ancillary revenue.

    Only assets the census recognises are joined; ancillary revenue from a unit
    that is not a BM-registered battery site stays unattributed rather than
    inventing a site for it.
    """
    daily = site_daily_revenue(refresh=refresh) if daily is None else daily
    sites = census.census_sites(refresh)[
        ["asset_id", "site_name", "lead_party", "declared_export_mw", "in_registry"]
    ]
    return daily.merge(sites, on="asset_id", how="left")


#: How a winning auction unit relates to a physical site. Ancillary revenue is
#: earned by whatever unit is registered to the service, and only one of these
#: categories is an asset.
UNIT_CLASSES = (
    "census site",            # a BM-registered physical battery site
    "VLP / supplier unit",    # a trading route registered to a lead party
    "aggregator portfolio",   # a house code naming no BM Unit at all
    "unknown",                # a BM-style name Elexon does not list
)


def classify_units(units: pd.Series, refresh: bool = False) -> pd.Series:
    """Label each auction unit by what it actually is.

    This distinction matters more than it first appears. NESO tags roughly half
    of recent battery ancillary revenue to units that are *not* sites: Virtual
    Lead Party and supplier units (Elexon ``bmUnitType`` V and S) are routes to
    market registered to a trading party, and aggregator house codes name no BM
    Unit whatsoever. Attributing their earnings to a site would invent an asset;
    calling them a gap in the census would be equally wrong, because the census
    is a register of physical sites and correctly excludes them.

    Returns a Series aligned to ``units`` drawn from :data:`UNIT_CLASSES`.
    """
    site_roots = {
        a.removeprefix("GB-BESS-") for a in census.census_sites(refresh)["asset_id"]
    }
    reference = census.fetch_bmu_reference(refresh)
    type_by_root: dict[str, str] = {}
    for row in reference.itertuples():
        root = census.bmu_root(row.nationalGridBmUnit, row.elexonBmUnit)
        type_by_root.setdefault(root, str(row.bmUnitType))

    labels = []
    for unit in units:
        text = str(unit)
        if _HOUSE_CODE_RE.match(text):
            labels.append("aggregator portfolio")
            continue
        root = census.bmu_root(text)
        if root in site_roots:
            labels.append("census site")
        elif type_by_root.get(root) in {"V", "S"}:
            labels.append("VLP / supplier unit")
        else:
            labels.append("unknown")
    return pd.Series(labels, index=units.index, name="unit_class")
