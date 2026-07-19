"""Single-day live data adapter for the live GB BESS benchmark.

This module is a thin convenience layer over the repo's existing data-fetch and
preprocess functions. It exposes just what the live benchmark needs for one
delivery day:

  * :func:`get_day_prices`  — hourly day-ahead and market-index prices.
  * :func:`get_day_context` — tier-2 generation/demand aggregates for the day.

No new HTTP/API code lives here: every number ultimately comes from the
``fetch_*`` functions in :mod:`src.data.download` and the ``process_*``
functions in :mod:`src.data.preprocess`.
"""

import datetime as dt
import logging

import pandas as pd

from src.data.download import (
    fetch_day_ahead_price,
    fetch_demand_actual,
    fetch_generation_actual,
    fetch_market_index_price,
    fetch_solar_actual,
)
from src.data.preprocess import (
    process_day_ahead_price,
    process_demand_actual,
    process_generation_mix,
    process_market_index_price,
    process_solar_actual,
)

logger = logging.getLogger(__name__)

# The live benchmark runs the hourly engine (resolution_h = 1.0), so prices are
# resampled from their 30-min native grid onto a 60-min grid.
_RESAMPLE_RULE = "60min"

# Live day-ahead price provider. ENTSO-E stopped publishing GB day-ahead prices,
# so the live path defaults to Nord Pool's GB (N2EX) feed.
_DA_SOURCE = "NORDPOOL"

# Native generation/demand data is half-hourly, so each period covers 0.5 h.
_PERIOD_HOURS = 0.5
# Megawatt-hours to gigawatt-hours.
_MWH_TO_GWH = 1.0 / 1000.0


def _day_window(date: dt.date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """UTC half-open window ``[date, date + 1 day)`` for the delivery day."""
    start = pd.Timestamp(date, tz="UTC")
    return start, start + pd.Timedelta(days=1)


def get_day_prices(date: dt.date, da_source: str = _DA_SOURCE) -> pd.DataFrame:
    """Return hourly day-ahead and market-index prices for a single delivery day.

    The frame is UTC-indexed, resampled to ``"60min"`` (matching the engine's
    ``resolution_h = 1.0``), and covers exactly ``[date, date + 1 day)`` with
    columns ``day_ahead_price`` and ``mid_price``. Rows missing a day-ahead
    price are dropped; a missing ``mid_price`` falls back to that row's
    day-ahead price.

    ``da_source`` selects the day-ahead price provider; it defaults to
    ``"NORDPOOL"`` (live GB N2EX prices) since ENTSO-E no longer publishes GB
    day-ahead prices. Pass ``"ENTSOE"`` to read the historical/cached archive.
    """
    start, end = _day_window(date)
    date_str = date.isoformat()
    next_str = (date + dt.timedelta(days=1)).isoformat()

    # Day-ahead price. Nord Pool (live GB) days are CET-labelled, so the fetcher
    # pulls [date, next] inclusive; the window slice below trims to the UTC day.
    day_ahead = process_day_ahead_price(
        fetch_day_ahead_price(source=da_source, start_date=date_str, end_date=next_str)
    )
    # Market index (MID) goes through the Elexon path, which reads the inclusive
    # [start_date, end_date] day(s).
    mid = process_market_index_price(
        fetch_market_index_price(start_date=date_str, end_date=date_str)
    )

    prices = day_ahead.join(mid, how="outer")
    prices = prices[(prices.index >= start) & (prices.index < end)]
    prices = prices.resample(_RESAMPLE_RULE).mean()
    # Only the day-ahead price is essential; a missing mid_price must not throw
    # away an otherwise valid day-ahead row, so drop on that column alone.
    prices = prices[["day_ahead_price", "mid_price"]].dropna(
        subset=["day_ahead_price"]
    )
    # A missing intraday MID for an otherwise valid period falls back to that
    # period's day-ahead price (MID == DA → zero intraday spread, so the engine
    # simply won't deviate). Leaving it NaN would crash the intraday LP
    # ("Cannot multiply variables with NaN/inf") and, if it ever survived,
    # serialise to an invalid JSON NaN token that blanks the dashboard.
    prices["mid_price"] = prices["mid_price"].fillna(prices["day_ahead_price"])
    prices.index.name = "time"
    return prices


def _generation_aggregates(date: dt.date) -> tuple[float, float]:
    """Wind GWh and wind share of transmission-metered generation (FUELHH).

    FUELHH carries no solar (solar is distribution-connected and invisible to
    transmission metering) — solar comes from :func:`_solar_aggregate` instead.
    A missing wind column raises rather than reporting a silent 0.0, so the
    caller degrades the field to ``None`` and the windy tag is suppressed, not
    faked.
    """
    start, end = _day_window(date)
    date_str = date.isoformat()

    gen = process_generation_mix(
        fetch_generation_actual(start_date=date_str, end_date=date_str)
    )
    gen = gen[(gen.index >= start) & (gen.index < end)]
    if gen.empty:
        raise ValueError("no generation data for the requested day")

    gen_cols = [c for c in gen.columns if c.startswith("gen_")]
    if "gen_WIND" not in gen_cols:
        raise ValueError("no wind column in generation mix")

    wind_gwh = float(gen["gen_WIND"].sum() * _PERIOD_HOURS * _MWH_TO_GWH)
    total_gwh = float(gen[gen_cols].sum().sum() * _PERIOD_HOURS * _MWH_TO_GWH)
    wind_share = wind_gwh / total_gwh if total_gwh > 0 else 0.0
    return wind_gwh, wind_share


def _solar_aggregate(date: dt.date) -> float:
    """Total GB embedded solar GWh for the day, from Sheffield Solar PV_Live."""
    start, end = _day_window(date)
    date_str = date.isoformat()

    solar = process_solar_actual(
        fetch_solar_actual(start_date=date_str, end_date=date_str)
    )
    solar = solar[(solar.index >= start) & (solar.index < end)]
    if solar.empty:
        raise ValueError("no PV_Live solar data for the requested day")
    return float(solar["solar_mw"].sum() * _PERIOD_HOURS * _MWH_TO_GWH)


def _demand_aggregate(date: dt.date) -> float:
    """Total demand GWh for the day from the actual-demand outturn."""
    start, end = _day_window(date)
    date_str = date.isoformat()

    demand = process_demand_actual(
        fetch_demand_actual(start_date=date_str, end_date=date_str)
    )
    demand = demand[(demand.index >= start) & (demand.index < end)]
    if demand.empty:
        raise ValueError("no demand data for the requested day")
    return float(demand["demand_actual"].sum() * _PERIOD_HOURS * _MWH_TO_GWH)


def get_day_context(date: dt.date) -> dict[str, float | None]:
    """Return tier-2 generation/demand context aggregates for the day.

    Keys: ``wind_gwh``, ``solar_gwh``, ``demand_gwh`` and ``wind_share`` (wind
    divided by total transmission-metered generation). Wind and demand come
    from Elexon (FUELHH / ITSDO); solar comes from Sheffield Solar's PV_Live,
    because embedded solar is invisible to Elexon. This never raises: if an
    underlying fetch fails or yields nothing usable, the affected field(s) are
    ``None`` and the failure is logged.
    """
    context: dict[str, float | None] = {
        "wind_gwh": None,
        "solar_gwh": None,
        "demand_gwh": None,
        "wind_share": None,
    }

    try:
        wind_gwh, wind_share = _generation_aggregates(date)
        context["wind_gwh"] = wind_gwh
        context["wind_share"] = wind_share
    except Exception as exc:
        logger.warning("Generation context unavailable for %s: %s", date, exc)

    try:
        context["solar_gwh"] = _solar_aggregate(date)
    except Exception as exc:
        logger.warning("Solar context unavailable for %s: %s", date, exc)

    try:
        context["demand_gwh"] = _demand_aggregate(date)
    except Exception as exc:
        logger.warning("Demand context unavailable for %s: %s", date, exc)

    return context


# --------------------------------------------------------------------------- #
# Whole-system snapshot (for the System overview page)
# --------------------------------------------------------------------------- #
# FUELHH fuels collapsed into presentation groups. Interconnectors are matched
# by the ``gen_INT`` prefix (there are ~10 of them) and everything left over —
# coal, oil, unclassified — folds into "Other", so no fuel is ever dropped.
_NAMED_FUEL_GROUPS: dict[str, tuple[str, ...]] = {
    "Wind": ("gen_WIND",),
    "Nuclear": ("gen_NUCLEAR",),
    "Gas": ("gen_CCGT", "gen_OCGT"),
    "Biomass": ("gen_BIOMASS",),
    "Hydro & storage": ("gen_NPSHYD", "gen_PS"),
}
# Fixed display/stack order; each group keeps its colour across the app.
GENERATION_GROUP_ORDER: tuple[str, ...] = (
    "Wind",
    "Solar",
    "Nuclear",
    "Gas",
    "Biomass",
    "Hydro & storage",
    "Interconnectors",
    "Other",
)
# Groups counted as low-carbon for the System page headline share.
LOW_CARBON_GROUPS: frozenset[str] = frozenset(
    {"Wind", "Solar", "Nuclear", "Hydro & storage", "Biomass"}
)


def group_generation(system: pd.DataFrame) -> pd.DataFrame:
    """Collapse raw fuel columns into presentation groups (MW).

    Takes the wide frame from :func:`get_day_system` (``gen_*`` columns plus
    ``solar_mw``) and returns one column per group in
    :data:`GENERATION_GROUP_ORDER` that has data. Interconnectors are summed to
    a single net band (negative when GB is exporting); every ``gen_*`` column
    not otherwise mapped lands in "Other", so total generation is conserved.
    """
    assigned: set[str] = set()
    groups: dict[str, pd.Series] = {}

    if "solar_mw" in system.columns:
        groups["Solar"] = system["solar_mw"]
        assigned.add("solar_mw")

    for name, cols in _NAMED_FUEL_GROUPS.items():
        present = [c for c in cols if c in system.columns]
        if present:
            groups[name] = system[present].sum(axis=1)
            assigned.update(present)

    int_cols = [c for c in system.columns if c.startswith("gen_INT")]
    if int_cols:
        groups["Interconnectors"] = system[int_cols].sum(axis=1)
        assigned.update(int_cols)

    other_cols = [
        c for c in system.columns if c.startswith("gen_") and c not in assigned
    ]
    if other_cols:
        groups["Other"] = system[other_cols].sum(axis=1)

    out = pd.DataFrame(groups, index=system.index)
    ordered = [g for g in GENERATION_GROUP_ORDER if g in out.columns]
    return out[ordered]


def get_day_system(date: dt.date) -> pd.DataFrame:
    """Half-hourly whole-system snapshot for one delivery day.

    Merges every FUELHH fuel (``gen_*`` MW), embedded solar from PV_Live
    (``solar_mw``) and actual demand (``demand_actual``) on the shared UTC
    half-hourly grid, covering ``[date, date + 1 day)``. Each source is fetched
    independently; one that fails or is empty simply contributes no columns
    rather than raising, so a partial snapshot still renders.
    """
    start, end = _day_window(date)
    date_str = date.isoformat()

    def _windowed(frame: pd.DataFrame) -> pd.DataFrame:
        return frame[(frame.index >= start) & (frame.index < end)]

    frames: list[pd.DataFrame] = []
    try:
        gen = process_generation_mix(
            fetch_generation_actual(start_date=date_str, end_date=date_str)
        )
        frames.append(_windowed(gen))
    except Exception as exc:
        logger.warning("System generation unavailable for %s: %s", date, exc)

    try:
        solar = process_solar_actual(
            fetch_solar_actual(start_date=date_str, end_date=date_str)
        )
        frames.append(_windowed(solar))
    except Exception as exc:
        logger.warning("System solar unavailable for %s: %s", date, exc)

    try:
        demand = process_demand_actual(
            fetch_demand_actual(start_date=date_str, end_date=date_str)
        )
        frames.append(_windowed(demand[["demand_actual"]]))
    except Exception as exc:
        logger.warning("System demand unavailable for %s: %s", date, exc)

    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    system = pd.concat(frames, axis=1).sort_index()
    # FUELHH publishes with a short lag, so the latest day's tail periods can
    # arrive with every fuel missing. Those are unpublished periods, not zero
    # generation — drop them rather than fabricate zeros, which would crash
    # the mix stack to zero and inflate residual load (demand minus nothing).
    gen_cols = [c for c in system.columns if c.startswith("gen_")]
    if gen_cols:
        system = system[system[gen_cols].notna().any(axis=1)]
    system.index.name = "time"
    return system
