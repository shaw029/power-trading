"""Pure single-day settlement for the live GB BESS benchmark.

This module runs the existing day-ahead optimisation followed by the rolling
intraday session for all three reference-asset durations (1h/2h/4h) on a single
delivery day's prices. It is deliberately pure and deterministic: it takes
already-fetched in-memory price data plus pre-built assets and config, and does
no file or network IO — fetching lives in :mod:`live.fetch_live` (A2) and
persistence in the A5 module.

For each duration the engine is driven exactly as the production pipeline drives
it (see ``pipeline._run_bess_pipeline``): reset the asset to the carried-over
end-of-day SOC, solve the day-ahead schedule, reset again, then settle the
schedule against the actual day-ahead and observed MID prices.
"""

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from src.bess.bess_asset import BESSAsset
from src.bess.da_optimizer import optimize_da_schedule
from src.bess.intraday_manager import run_intraday_session

# The live benchmark runs the hourly engine, so a normal day has 24 periods and
# the two DST changeover days have 23 (spring) and 25 (autumn). Any other count
# signals malformed/incomplete price data and is refused. Mirrors the
# ``valid_period_counts`` guard in ``pipeline._run_bess_pipeline``.
VALID_PERIOD_COUNTS: frozenset[int] = frozenset({23, 24, 25})

# Below this arbitrage ceiling the day has no meaningful spread to capture, so
# the capture ratio is reported as zero rather than dividing by ~0.
_CAPTURE_EPS = 1e-9


@dataclass
class DurationResult:
    """Settlement outcome for one reference duration on one day.

    The PnL buckets obey the engine's ledger invariant::

        benchmark_da_revenue + intraday_da_improvement
            - execution_costs_paid - degradation_cost == net_pnl
    """

    da_schedule: list[float]
    dispatch_log: list[dict]
    end_soc: float
    # PnL buckets (£), summing to net_pnl per the invariant above.
    benchmark_da_revenue: float
    intraday_da_improvement: float
    execution_costs_paid: float
    degradation_cost: float
    net_pnl: float
    # Metrics.
    cycles: float
    capture: float


@dataclass
class DayResult:
    """All-duration settlement for a single delivery day."""

    date: dt.date
    durations: dict[str, DurationResult]


def _arbitrage_upper_bound(
    day_ahead_prices: list[float],
    asset: BESSAsset,
    duration_h: float,
) -> float:
    """Perfect-foresight day-ahead arbitrage value (£) for the day.

    Solves the day-ahead schedule against the *actual* cleared day-ahead prices
    (perfect foresight) with the cycling cap removed, then values that schedule
    at those same prices: ``Σ mw_h · price_h · duration_h``. This is the ceiling
    a price-taking battery could have extracted from pure day-ahead arbitrage on
    this day given its power, SOC band and round-trip efficiency. The asset must
    already be reset to the day's starting SOC by the caller.
    """
    schedule = optimize_da_schedule(
        da_price_forecast=day_ahead_prices,
        asset=asset,
        duration_h=duration_h,
        target_daily_cycles=None,
    )
    return sum(mw * price * duration_h for mw, price in zip(schedule, day_ahead_prices))


def _settle_duration(
    day_ahead_prices: list[float],
    mid_prices: list[float],
    asset: BESSAsset,
    bess_cfg: dict,
    start_soc_pct: float,
) -> DurationResult:
    """Run the DA optimisation + intraday session for one duration's asset.

    ``capture`` = realised ``net_pnl`` ÷ the perfect-foresight day-ahead
    arbitrage upper bound (see :func:`_arbitrage_upper_bound`). On days whose
    upper bound is at or below ``_CAPTURE_EPS`` (e.g. flat prices, no spread)
    capture is reported as ``0.0`` rather than dividing by ~0.
    """
    duration_h = bess_cfg.get("resolution_h", 1.0)
    target_daily_cycles = bess_cfg.get("target_daily_cycles")

    # Day-ahead: schedule against the actual cleared DA prices from the day's
    # starting SOC, then reset and settle that locked schedule intraday.
    asset.reset(start_soc_pct)
    schedule = optimize_da_schedule(
        da_price_forecast=day_ahead_prices,
        asset=asset,
        duration_h=duration_h,
        target_daily_cycles=target_daily_cycles,
    )

    asset.reset(start_soc_pct)
    # The live benchmark settles on realised prices, so it optimises intraday with
    # perfect foresight of the MID curve (an idealised upper bound), consistent
    # with its perfect-foresight DA schedule. The Phase-3 backtest keeps the
    # default rolling/proxy (no-lookahead) engine.
    result = run_intraday_session(
        da_schedule=schedule,
        da_price_actual=day_ahead_prices,
        mid_prices=mid_prices,
        asset=asset,
        config=bess_cfg,
        perfect_foresight=True,
    )
    end_soc = asset.soc_pct
    net_pnl = result["net_pnl"]

    # Energy throughput (gross charge + discharge) over the day; one full cycle
    # equals 2 × capacity of throughput.
    throughput_mwh = sum(abs(entry["final_mw"]) for entry in result["dispatch_log"]) * duration_h
    cycles = throughput_mwh / (2.0 * asset.capacity_mwh) if asset.capacity_mwh > 0 else 0.0

    # Capture vs the perfect-foresight DA arbitrage ceiling (recomputed from the
    # day's starting SOC).
    asset.reset(start_soc_pct)
    upper_bound = _arbitrage_upper_bound(day_ahead_prices, asset, duration_h)
    capture = net_pnl / upper_bound if upper_bound > _CAPTURE_EPS else 0.0

    return DurationResult(
        da_schedule=schedule,
        dispatch_log=result["dispatch_log"],
        end_soc=end_soc,
        benchmark_da_revenue=result["benchmark_da_revenue"],
        intraday_da_improvement=result["intraday_da_improvement"],
        execution_costs_paid=result["execution_costs_paid"],
        degradation_cost=result["total_degradation_cost"],
        net_pnl=net_pnl,
        cycles=cycles,
        capture=capture,
    )


def settle_day(
    date: dt.date,
    prices: pd.DataFrame,
    bess_cfg: dict,
    assets: dict[str, BESSAsset],
    prev_end_soc: dict[str, float],
) -> DayResult | None:
    """Settle one delivery day across all reference durations.

    ``prices`` is a single day's price frame with ``day_ahead_price`` and
    ``mid_price`` columns (as produced by :func:`live.fetch_live.get_day_prices`).
    ``assets`` maps each duration key to its :class:`BESSAsset`, and
    ``prev_end_soc`` maps each duration key to the SOC fraction carried over from
    the previous day's close.

    Returns a :class:`DayResult` with one :class:`DurationResult` per duration,
    or ``None`` if the day's period count is not in :data:`VALID_PERIOD_COUNTS`
    (the DST / malformed-data guard) or a required price column is absent —
    mirroring the pipeline's behaviour of skipping such days rather than
    attempting settlement.

    A duration missing from ``prev_end_soc`` falls back to its asset's
    ``initial_soc_pct`` rather than failing the whole day.
    """
    if len(prices) not in VALID_PERIOD_COUNTS:
        return None
    if "day_ahead_price" not in prices.columns or "mid_price" not in prices.columns:
        return None

    day_ahead_prices = prices["day_ahead_price"].tolist()
    mid_prices = prices["mid_price"].tolist()

    durations: dict[str, DurationResult] = {}
    for duration, asset in assets.items():
        durations[duration] = _settle_duration(
            day_ahead_prices=day_ahead_prices,
            mid_prices=mid_prices,
            asset=asset,
            bess_cfg=bess_cfg,
            start_soc_pct=prev_end_soc.get(duration, asset.initial_soc_pct),
        )

    return DayResult(date=date, durations=durations)
