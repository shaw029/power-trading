"""Master asset registry: every BM-registered GB grid-scale battery.

:mod:`fleet.curated` is a hand-researched metadata table — sites chosen to span
optimisers and regions, and honest about being a sample. That is the right
input for the live dashboard, which needs a stable, hand-verified list it can
render fast. It is the wrong input for a claim about the GB fleet: "the
registry contains 23 sites" says nothing about what fraction of the market
those sites are, so no result computed on them can be generalised.

This module builds the census the registry is a sample *of*, and it exists
because no such list is published. Elexon's BMU reference carries no battery
fuel type at all — 2,470 of 3,055 units have ``fuelType: null`` and not one row
says "battery" — so a battery population cannot be downloaded, only
constructed. It is constructed here by cross-referencing five public sources
and scoring the agreement between them:

===================  ==========================================================
Source               What it contributes
===================  ==========================================================
Elexon BMU reference The BM Unit universe: IDs, lead party, declared import and
                     export capability, GSP group. The population being
                     classified.
NESO CM Register     Explicit ``Storage`` technology *with duration*
                     ("Storage (Duration 2h)"), so it is the only free source
                     that yields **MWh** rather than MW alone. Also the
                     registered holder and transmission/distribution split.
NESO TEC Register    Transmission-connected projects: ``Plant Type`` =
                     "Energy Storage System", ``Project Status`` = "Built",
                     connected MW and the connection date.
NESO Embedded Reg.   The same for distribution-connected projects — the
                     sub-20 MW tail the BM-only view under-represents.
NESO EAC results     Response/reserve auction results carry an explicit
                     ``technologyType`` of "Batteries" per participant, which
                     independently corroborates a lead party as a battery
                     operator.
===================  ==========================================================

**Why evidence scoring rather than one filter.** Every single signal is wrong
somewhere. Bidirectional capability catches pumped storage and any site with a
site load. Name matching misses units named for their substation. The CM
register lists units that never got built. The curated registry itself is
ground truth but covers only part of the fleet. A unit is therefore classified
as a battery when independent sources agree, and every signal is kept as its
own column so a downstream coverage claim can be re-derived under a stricter
or looser rule instead of trusting one threshold baked in here.

**Persistent asset ID (the point of the exercise).** Sites change owner,
change name and change BM Unit registration, so keying analysis on any of
those silently splits one asset into two across a multi-year window. The
stable key is the *National Grid BMU root* — ``COALB`` from ``COALB-1``,
``COALB-2``… — because it is tied to the physical connection point rather than
to the commercial arrangement around it. ``asset_id`` is ``GB-BESS-<root>``.
Known re-registrations, where even the root moved, are listed in
:data:`ASSET_ID_ALIASES` so history stitches back together.

Registers are not day-partitioned, so each is cached once per *fetch* date
under ``RAW_DATA_DIR/REGISTERS/`` — at most one network round per source per
day, mirroring how the Capacity Market Notice register is already cached.

Nothing here is imported by the live dashboard — the census pulls whole
registers and is barred from that process by ``tests/test_profile_boundary.py``.
The dashboard renders :mod:`fleet.registry`, a static module *generated* from
this census by ``scripts/build_registry.py``, so it gets the population
without ever building it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from typing import Any, cast

import pandas as pd
import requests

from fleet.curated import CURATED_SITES, bmu_to_site
from src.utils.config import ELEXON_BASE_URL, RAW_DATA_DIR

logger = logging.getLogger(__name__)

_CACHE_DIR = "REGISTERS"
_TIMEOUT_S = 120
_CKAN_SEARCH = "https://api.neso.energy/api/3/action/datastore_search"
_CKAN_SQL = "https://api.neso.energy/api/3/action/datastore_search_sql"

#: NESO CKAN resource IDs. Fixed constants — never built from user input.
CM_CMU_RESOURCE = "25a5fa2e-873d-41c5-8aaf-fbc2b06d79e6"
TEC_RESOURCE = "17becbab-e3e8-473f-b303-3806f43a6a10"
EMBEDDED_RESOURCE = "68b6f3a1-e1bf-403b-9062-0269fc758d77"
EAC_UNIT_RESOURCE = "a63ab354-7e68-44c2-ad96-c6f920c30e85"

#: Durations above this are pumped hydro, not batteries. GB's CM register puts
#: Dinorwig and Cruachan in the same ``Storage`` technology family as a 2-hour
#: lithium site; the 9.5h and 12h bands are entirely pumped storage.
MAX_BATTERY_DURATION_H = 8.0

#: Declared import / export ratio accepted as a battery. All 47 BM Units of
#: the curated registry fall in [0.96, 1.14]; generators with a site load sit
#: two orders of magnitude below. The band is deliberately wider than the
#: observed range because the result is insensitive to it.
SYMMETRY_BAND = (0.75, 1.35)

#: Sites whose National Grid BMU root changed on re-registration. Maps the
#: superseded root to the surviving one so a window spanning the change reads
#: as one asset rather than two.
ASSET_ID_ALIASES: dict[str, str] = {}

#: Optional freeze for the live feeds this module and :mod:`fleet.ancillary`
#: read. ``None`` — the default — means "use today", which is the live behaviour
#: every library caller and the dashboard rely on. **Nothing in the repo pins
#: this.**
#:
#: The research notebooks set it, each in its own setup cell, because a
#: reproducible result needs a fixed vintage: the five registers and NESO's
#: auction results are all live, so two runs on different days return a
#: different population and different revenue, and every figure quoting either
#: disagrees with the next run. Notebooks 04, 05 and 06 each set a date, and
#: state it there rather than here — a vintage copied into library code is one
#: more place to forget to update.
#:
#: To move a notebook's analysis forward, change the date in that notebook's
#: setup cell and re-run it. If its figures are quoted in ``README.md``,
#: ``DATA_ARCHITECTURE.md`` or ``reports/poster/poster.typ``, update those too —
#: and regenerate ``fleet/registry.py`` if the population changed, since the
#: dashboard's list is derived from this census.
SNAPSHOT: dt.date | None = None

_BATTERY_NAME_RE = re.compile(r"\b(?:BESS|BATTER\w*|ENERGY STORAGE|STORAGE)\b", re.I)
_BMU_BATTERY_ID_RE = re.compile(r"B-?\d+$")
_DURATION_RE = re.compile(r"Duration\s*([\d.]+)\s*h", re.I)

# Words that carry no identity when matching a project name to a BM Unit name.
_NOISE_TOKENS = {
    "BESS", "BATTERY", "ENERGY", "STORAGE", "SYSTEM", "FACILITY", "PROJECT",
    "LIMITED", "LTD", "UK", "PHASE", "SITE", "POWER", "SUBSTATION", "GRID",
    "THE", "AND", "OF", "MW", "SOLAR", "FARM", "STATION", "DEVELOPMENTS",
}


# ---------------------------------------------------------------------------
# Fetching and caching
# ---------------------------------------------------------------------------


def _cache_path(name: str, date: dt.date) -> str:
    return os.path.join(RAW_DATA_DIR, _CACHE_DIR, f"{name}_{date.isoformat()}.json")


def snapshot_date(probe: str | None = None) -> dt.date:
    """The date a cached feed is read at, and whether a pin is being honoured.

    Returns :data:`SNAPSHOT` when a caller has set one and it is on disk, and
    today otherwise. ``probe`` is the cache file the caller needs; each feed
    passes its own, because the pin is only meaningful per feed.

    The fallback is deliberate and noisy: a pinned date whose file is missing
    must not cause today's data to be written under the pinned name, because
    that would label live data as the snapshot and make the pin worse than
    useless. ``data/`` is gitignored, so a fresh clone hits this path.
    """
    if SNAPSHOT is None:
        return dt.date.today()
    probe = _cache_path("BMU_REFERENCE", SNAPSHOT) if probe is None else probe
    if os.path.exists(probe):
        return SNAPSHOT
    logger.warning(
        "SNAPSHOT is pinned to %s but %s does not exist; fetching live instead. "
        "Results will differ from the figures this notebook's outputs, and any "
        "document quoting them, were computed on.",
        SNAPSHOT.isoformat(), os.path.basename(probe),
    )
    return dt.date.today()


def _cached(name: str, builder, refresh: bool = False) -> Any:
    """Fetch ``name`` once per snapshot date, reusing that cache otherwise."""
    path = _cache_path(name, snapshot_date())
    if not refresh and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)

    payload = builder()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp)
    logger.info("Cached %s (%d records)", path, len(payload))
    return payload


def _ckan_records(resource_id: str, page_size: int = 10000) -> list[dict]:
    """Every record of a CKAN datastore resource, paged to exhaustion."""
    records: list[dict] = []
    offset = 0
    while True:
        params: list[tuple[str, str]] = [
            ("resource_id", resource_id),
            ("limit", str(page_size)),
            ("offset", str(offset)),
        ]
        response = requests.get(_CKAN_SEARCH, params=params, timeout=_TIMEOUT_S)
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            raise ValueError(f"CKAN error for {resource_id}: {body.get('error')}")
        page = body["result"]["records"]
        if not page:
            break
        records.extend(page)
        offset += len(page)
        if len(page) < page_size:
            break
    return records


def _ckan_sql(sql: str) -> list[dict]:
    """Run a *fixed* CKAN SQL query. Callers pass constants, never user input."""
    response = requests.get(_CKAN_SQL, params={"sql": sql}, timeout=_TIMEOUT_S)
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise ValueError(f"CKAN SQL error: {body.get('error')}")
    return cast(list[dict], body["result"]["records"])


def fetch_bmu_reference(refresh: bool = False) -> pd.DataFrame:
    """Elexon's full BM Unit reference list — the population to be classified.

    Keyless and un-paged: the endpoint returns all ~3,000 units in one body.
    """

    def build() -> list[dict]:
        response = requests.get(
            f"{ELEXON_BASE_URL.rstrip('/')}/reference/bmunits/all",
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT_S,
        )
        response.raise_for_status()
        return cast(list[dict], response.json())

    frame = pd.DataFrame(_cached("BMU_REFERENCE", build, refresh))
    for col in ("demandCapacity", "generationCapacity"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def fetch_cm_storage(refresh: bool = False) -> pd.DataFrame:
    """Capacity Market units whose technology is ``Storage``, with duration.

    Returns one row per CMU per delivery year. ``duration_h`` is parsed from
    the technology string, which is the only free source of GB battery **MWh**;
    rows above :data:`MAX_BATTERY_DURATION_H` are pumped storage and are
    dropped.
    """

    def build() -> list[dict]:
        return _ckan_records(CM_CMU_RESOURCE)

    frame = pd.DataFrame(_cached("CM_CMU", build, refresh))
    frame = frame[frame["CMU Technology"].astype(str).str.startswith("Storage")].copy()

    frame["duration_h"] = (
        frame["CMU Technology"]
        .astype(str)
        .str.extract(_DURATION_RE, expand=False)
        .astype(float)
    )
    for col in ("Connection / DSR Capacity", "De-Rated Capacity", "Delivery Year"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    # A CMU with no stated duration is kept (many are 1-2h and simply unlabelled);
    # only an explicitly long duration is excluded as pumped hydro.
    frame = frame[~(frame["duration_h"] > MAX_BATTERY_DURATION_H)]

    frame = frame.rename(
        columns={
            "CM Unit Name": "cm_unit_name",
            "Registered Holder": "registered_holder",
            "Parent Company": "parent_company",
            "Connection / DSR Capacity": "cm_power_mw",
            "De-Rated Capacity": "cm_derated_mw",
            "Transmission / Distribution": "connection_level",
            "Delivery Year": "delivery_year",
            "Capacity Agreement Awarded": "agreement_awarded",
        }
    )
    frame["cm_capacity_mwh"] = frame["cm_power_mw"] * frame["duration_h"]
    return frame


def _fetch_connection_register(
    resource_id: str, cache_name: str, refresh: bool
) -> pd.DataFrame:
    """Shared shape of the TEC and Embedded registers, filtered to storage."""

    def build() -> list[dict]:
        return _ckan_records(resource_id)

    frame = pd.DataFrame(_cached(cache_name, build, refresh))
    frame = frame[
        frame["Plant Type"].astype(str).str.contains("Energy Storage", case=False, na=False)
    ].copy()
    for col in ("MW Connected", "MW Increase / Decrease", "Cumulative Total Capacity (MW)"):
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.rename(
        columns={
            "Project Name": "project_name",
            "Customer Name": "customer_name",
            "Connection Site": "connection_site",
            "MW Connected": "connected_mw",
            "MW Effective From": "effective_from",
            "Project Status": "project_status",
            "Plant Type": "plant_type",
        }
    )


def fetch_tec_storage(refresh: bool = False) -> pd.DataFrame:
    """Transmission Entry Capacity register rows that include energy storage."""
    return _fetch_connection_register(TEC_RESOURCE, "TEC_REGISTER", refresh)


def fetch_embedded_storage(refresh: bool = False) -> pd.DataFrame:
    """Embedded (distribution) connection register rows that include storage."""
    return _fetch_connection_register(EMBEDDED_RESOURCE, "EMBEDDED_REGISTER", refresh)


def fetch_eac_battery_participants(refresh: bool = False) -> pd.DataFrame:
    """Distinct response/reserve auction participants declared as batteries.

    The EAC results table is over a million rows, so only the distinct
    participant/unit pairs with ``technologyType = 'Batteries'`` are pulled.
    A lead party appearing here is independent corroboration that it operates
    batteries — it does not, on its own, identify *which* of its BM Units are.
    """

    def build() -> list[dict]:
        return _ckan_sql(
            f'SELECT DISTINCT "registeredAuctionParticipant", "auctionUnit" '
            f'FROM "{EAC_UNIT_RESOURCE}" WHERE "technologyType" = \'Batteries\''
        )

    frame = pd.DataFrame(_cached("EAC_BATTERY_UNITS", build, refresh))
    return frame.rename(
        columns={
            "registeredAuctionParticipant": "participant",
            "auctionUnit": "auction_unit",
        }
    )


# ---------------------------------------------------------------------------
# Name normalisation and identity
# ---------------------------------------------------------------------------


def normalise_name(name: str | None) -> frozenset[str]:
    """Reduce a project or unit name to its identifying tokens.

    "Coalburn Battery Energy Storage Facility" and "Coalburn 1" both reduce to
    ``{"COALBURN"}``; the words that appear in every battery's name carry no
    identity and are dropped.
    """
    if not name:
        return frozenset()
    tokens = re.split(r"[^A-Za-z0-9]+", str(name).upper())
    return frozenset(t for t in tokens if t and t not in _NOISE_TOKENS and not t.isdigit())


def bmu_root(national_grid_bmu: str | None, elexon_bmu: str | None = None) -> str:
    """The stable identity of a BM Unit's physical connection point.

    ``COALB-1`` … ``COALB-5`` all share the root ``COALB``, which is what makes
    the root — not the unit ID, the site name or the owner — the right key for
    an asset that re-registers or changes hands mid-window.
    """
    raw = national_grid_bmu or elexon_bmu or ""
    raw = re.sub(r"^[TEMV]_", "", str(raw).strip().upper())
    root = re.sub(r"-\d+$", "", raw)
    return ASSET_ID_ALIASES.get(root, root)


def asset_id(national_grid_bmu: str | None, elexon_bmu: str | None = None) -> str:
    """Persistent asset identifier, stable across owner/name/BMU changes."""
    return f"GB-BESS-{bmu_root(national_grid_bmu, elexon_bmu)}"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def battery_bmus(refresh: bool = False) -> pd.DataFrame:
    """Every BM Unit, scored for the evidence that it is a grid-scale battery.

    Returns the whole BMU population — nothing is dropped — with one column per
    signal, an ``is_battery`` verdict and a ``confidence`` grade. A coverage
    claim should be able to show what it excluded and why, and a caller wanting
    a different rule can re-derive it from these columns without re-fetching.

    **The identifying rule.** Four necessary conditions, all read off Elexon's
    own reference data:

    1. *Physical unit* — ``bmUnitType`` T or E, not an interconnector. Supplier
       and VLP portfolio units (``2__A…``) are real battery routes to market
       but are not sites, and counting them as sites would double-count the
       physical assets trading behind them.
    2. *No conflicting fuel type* — null or ``OTHER``. Elexon labels no unit as
       a battery, but it does label wind, CCGT, nuclear and pumped storage, and
       a unit that carries one of those labels is not a battery.
    3. *Bidirectional* — declares both export capability and import capability.
    4. *Symmetric* — declared import and export are within
       :data:`SYMMETRY_BAND` of each other.

    Condition 4 is what makes the rule precise rather than merely plausible. A
    battery's charge and discharge ratings are near-symmetric by construction:
    all 47 BM Units of the curated registry fall between 0.96 and 1.14. A
    generator with a modest site load looks bidirectional but is nowhere near
    symmetric — Derwent Cogeneration declares 0.01, Cleve Hill Solar 0.01,
    Thurrock Power 0.02, the Kilgallioch wind BMU 0.23 — so the ratio separates
    the two populations cleanly with a wide gap and no tuning. Widening the
    band from [0.90, 1.20] to [0.50, 2.00] moves the count from 126 units to
    133, which is the property to want: the answer does not hinge on the
    threshold.

    The curated registry is treated as ground truth and always qualifies, and
    the rule recovers all 47 of its units independently.

    **Corroboration, not identification.** The Capacity Market, connection
    register and response-auction signals are recorded per unit but do not
    decide the verdict — their name matching is too loose to carry a headline
    number. They grade ``confidence`` instead, so a result can be quoted for
    the corroborated subset alone if a reviewer wants only cross-referenced
    assets.
    """
    ref = fetch_bmu_reference(refresh).copy()
    cm = fetch_cm_storage(refresh)
    tec = fetch_tec_storage(refresh)
    embedded = fetch_embedded_storage(refresh)
    eac = fetch_eac_battery_participants(refresh)

    ref["asset_id"] = [
        asset_id(row.nationalGridBmUnit, row.elexonBmUnit) for row in ref.itertuples()
    ]
    ref["root"] = ref["asset_id"].str.removeprefix("GB-BESS-")

    # --- the identifying conditions ---------------------------------------
    ref["is_physical"] = ref["bmUnitType"].isin(["T", "E"]) & ref["interconnectorId"].isna()
    ref["fuel_permits_battery"] = ref["fuelType"].isna() | ref["fuelType"].eq("OTHER")
    ref["is_bidirectional"] = (ref["demandCapacity"] < 0) & (ref["generationCapacity"] > 0)
    ref["capability_ratio"] = (-ref["demandCapacity"]) / ref["generationCapacity"]
    ref["is_symmetric"] = ref["capability_ratio"].between(*SYMMETRY_BAND)

    # --- corroborating evidence -------------------------------------------
    ref["sig_name"] = ref["bmUnitName"].fillna("").str.contains(_BATTERY_NAME_RE) | ref[
        "elexonBmUnit"
    ].fillna("").str.contains(_BMU_BATTERY_ID_RE)

    cm_roots = {
        re.sub(r"[^A-Z0-9]", "", str(n).upper()) for n in cm["cm_unit_name"].dropna()
    }
    cm_roots |= {re.sub(r"\d+$", "", c) for c in cm_roots}
    ref["sig_cm"] = ref["root"].isin(cm_roots)

    connection_tokens: set[str] = set()
    for frame in (tec, embedded):
        for name in frame["project_name"].dropna():
            connection_tokens |= normalise_name(name)
    ref["sig_connection"] = [
        bool(normalise_name(name) & connection_tokens) for name in ref["bmUnitName"].fillna("")
    ]

    eac_parties = {p.strip().upper() for p in eac["participant"].dropna()} if len(eac) else set()
    ref["sig_eac"] = ref["leadPartyName"].fillna("").str.upper().str.strip().isin(eac_parties)

    ref["sig_registry"] = ref["elexonBmUnit"].isin(set(bmu_to_site()))

    # --- verdict -----------------------------------------------------------
    signature = (
        ref["is_physical"]
        & ref["fuel_permits_battery"]
        & ref["is_bidirectional"]
        & ref["is_symmetric"]
    )
    # The identifying rule and nothing else. The curated list used to be OR'd in
    # here, which made the population partly an assertion rather than a
    # measurement. It was also doing nothing: the signature recovers every unit
    # on that list unaided, so removing it leaves the census byte-identical.
    # `tests/test_census.py` holds that to be true.
    ref["is_battery"] = signature

    corroborated = ref[["sig_name", "sig_cm", "sig_connection", "sig_eac"]].any(axis=1)
    ref["corroborations"] = ref[["sig_name", "sig_cm", "sig_connection", "sig_eac"]].sum(axis=1)
    ref["confidence"] = "not_battery"
    ref.loc[ref["is_battery"] & ~corroborated, "confidence"] = "signature_only"
    ref.loc[ref["is_battery"] & corroborated, "confidence"] = "corroborated"
    ref.loc[ref["sig_registry"], "confidence"] = "registry"
    return ref


#: Confidence grades accepted into the analysis population by default.
#: ``signature_only`` is excluded: those units pass the physical test with no
#: independent source agreeing, and every one of them so far has been a false
#: positive — the Isle of Man interconnector (symmetric by construction, as any
#: interconnector is), a hydro station's demand unit, and a gas site. The grade
#: was built so a result could be quoted for cross-referenced assets alone; this
#: makes that the default rather than an option nobody takes.
ANALYSIS_CONFIDENCE = ("registry", "corroborated")


def census_sites(
    refresh: bool = False, confidence: tuple[str, ...] = ANALYSIS_CONFIDENCE
) -> pd.DataFrame:
    """The census, aggregated from BM Units to physical sites.

    One row per ``asset_id`` — the persistent key — carrying the site's BM
    Units, declared MW, owner, region, confidence grade and whether the curated
    registry covers it. This is the frame every statistic in
    :mod:`fleet.coverage` is computed from.

    ``confidence`` selects which grades qualify, defaulting to
    :data:`ANALYSIS_CONFIDENCE`. Pass ``None`` to keep every unit the physical
    rule accepted, including the uncorroborated ones — useful for auditing the
    rule itself, and wrong for anything quoted.

    Declared export MW is summed across the site's units because a multi-unit
    site splits its nameplate between them; declared import is summed the same
    way and kept, since the asymmetry between them is itself diagnostic.
    """
    units = battery_bmus(refresh)
    units = units[units["is_battery"]].copy()
    if confidence is not None:
        units = units[units["confidence"].isin(confidence)]

    grouped = units.groupby("asset_id", sort=False)
    sites = pd.DataFrame(
        {
            "bmu_ids": grouped["elexonBmUnit"].apply(tuple),
            "n_bmus": grouped.size(),
            "site_name": grouped["bmUnitName"].first(),
            "lead_party": grouped["leadPartyName"].first(),
            "bmu_type": grouped["bmUnitType"].first(),
            "declared_export_mw": grouped["generationCapacity"].sum(),
            "declared_import_mw": grouped["demandCapacity"].sum(),
            "gsp_group": grouped["gspGroupName"].first(),
            "corroborations": grouped["corroborations"].max(),
            "in_registry": grouped["sig_registry"].any(),
        }
    ).reset_index()

    # A site inherits the strongest grade any of its units earned.
    order = {"registry": 3, "corroborated": 2, "signature_only": 1}
    best = grouped["confidence"].apply(lambda s: max(s, key=lambda c: order.get(c, 0)))
    sites["confidence"] = sites["asset_id"].map(best)

    sites["connection_level"] = sites["bmu_type"].map(
        {"T": "Transmission", "E": "Distribution"}
    )

    curated = bmu_to_site()
    for column, attribute in (
        ("registry_site", "site"),
        ("registry_power_mw", "power_mw"),
        ("registry_capacity_mwh", "capacity_mwh"),
        ("registry_optimiser", "optimiser"),
        ("registry_region", "region"),
    ):
        sites[column] = [
            next((getattr(curated[b], attribute) for b in bmus if b in curated), None)
            for bmus in sites["bmu_ids"]
        ]

    return sites.sort_values("declared_export_mw", ascending=False).reset_index(drop=True)


def registry_totals() -> dict[str, float]:
    """Headline totals for the curated registry — the coverage numerator."""
    return {
        "sites": float(len(CURATED_SITES)),
        "bmus": float(sum(len(s.bmu_ids) for s in CURATED_SITES)),
        "power_mw": float(sum(s.power_mw for s in CURATED_SITES)),
        "capacity_mwh": float(sum(s.capacity_mwh for s in CURATED_SITES)),
    }
