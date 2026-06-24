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
)
from src.data.preprocess import (
    process_day_ahead_price,
    process_demand_actual,
    process_generation_mix,
    process_market_index_price,
)

logger = logging.getLogger(__name__)

# The live benchmark runs the hourly engine (resolution_h = 1.0), so prices are
# resampled from their 30-min native grid onto a 60-min grid.
_RESAMPLE_RULE = "60min"

# Native generation/demand data is half-hourly, so each period covers 0.5 h.
_PERIOD_HOURS = 0.5
# Megawatt-hours to gigawatt-hours.
_MWH_TO_GWH = 1.0 / 1000.0


def _day_window(date: dt.date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """UTC half-open window ``[date, date + 1 day)`` for the delivery day."""
    start = pd.Timestamp(date, tz="UTC")
    return start, start + pd.Timedelta(days=1)


def get_day_prices(date: dt.date) -> pd.DataFrame:
    """Return hourly day-ahead and market-index prices for a single delivery day.

    The frame is UTC-indexed, resampled to ``"60min"`` (matching the engine's
    ``resolution_h = 1.0``), and covers exactly ``[date, date + 1 day)`` with
    columns ``day_ahead_price`` and ``mid_price``. Rows missing a day-ahead
    price are dropped; a missing ``mid_price`` is left as NaN.
    """
    start, end = _day_window(date)
    date_str = date.isoformat()
    next_str = (date + dt.timedelta(days=1)).isoformat()

    # Day-ahead price: loop is `current < end`, so end is the next day.
    day_ahead = process_day_ahead_price(
        fetch_day_ahead_price(start_date=date_str, end_date=next_str)
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
    prices.index.name = "time"
    return prices


def _generation_aggregates(date: dt.date) -> tuple[float, float, float]:
    """Wind GWh, solar GWh and wind share for the day from the generation mix."""
    start, end = _day_window(date)
    date_str = date.isoformat()

    gen = process_generation_mix(
        fetch_generation_actual(start_date=date_str, end_date=date_str)
    )
    gen = gen[(gen.index >= start) & (gen.index < end)]
    if gen.empty:
        raise ValueError("no generation data for the requested day")

    gen_cols = [c for c in gen.columns if c.startswith("gen_")]
    if not gen_cols:
        raise ValueError("no gen_ columns in generation mix")

    def _gwh(column: str) -> float:
        if column not in gen.columns:
            return 0.0
        return float(gen[column].sum() * _PERIOD_HOURS * _MWH_TO_GWH)

    wind_gwh = _gwh("gen_WIND")
    solar_gwh = _gwh("gen_SOLAR")
    total_gwh = float(gen[gen_cols].sum().sum() * _PERIOD_HOURS * _MWH_TO_GWH)
    wind_share = wind_gwh / total_gwh if total_gwh > 0 else 0.0
    return wind_gwh, solar_gwh, wind_share


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
    divided by total generation). This never raises: if an underlying fetch
    fails or yields nothing usable, the affected field(s) are ``None`` and the
    failure is logged.
    """
    context: dict[str, float | None] = {
        "wind_gwh": None,
        "solar_gwh": None,
        "demand_gwh": None,
        "wind_share": None,
    }

    try:
        wind_gwh, solar_gwh, wind_share = _generation_aggregates(date)
        context["wind_gwh"] = wind_gwh
        context["solar_gwh"] = solar_gwh
        context["wind_share"] = wind_share
    except Exception as exc:
        logger.warning("Generation context unavailable for %s: %s", date, exc)

    try:
        context["demand_gwh"] = _demand_aggregate(date)
    except Exception as exc:
        logger.warning("Demand context unavailable for %s: %s", date, exc)

    return context
