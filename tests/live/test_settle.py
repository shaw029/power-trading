"""Tests for the pure single-day settlement module.

Synthetic in-memory price frames drive the real BESS engine end to end, so no
network or file IO happens beyond loading the shared example config.
"""

import datetime as dt

import pandas as pd
import pytest

from live import settle
from live.assets import REFERENCE_DURATIONS, bess_config, build_assets

_DAY = dt.date(2024, 6, 1)


def _prices(n_periods: int, *, low: float = 20.0, high: float = 80.0) -> pd.DataFrame:
    """Cheap-first-half / expensive-second-half day giving clear arbitrage.

    The MID carries a small positive basis over the DA price so the intraday
    session has something to act on.
    """
    times = pd.date_range("2024-06-01T00:00:00Z", periods=n_periods, freq="60min")
    da = [low if i < n_periods // 2 else high for i in range(n_periods)]
    mid = [p + 1.0 for p in da]
    return pd.DataFrame({"day_ahead_price": da, "mid_price": mid}, index=times)


def _flat_prices(n_periods: int = 24, *, level: float = 50.0) -> pd.DataFrame:
    times = pd.date_range("2024-06-01T00:00:00Z", periods=n_periods, freq="60min")
    return pd.DataFrame(
        {"day_ahead_price": [level] * n_periods, "mid_price": [level] * n_periods},
        index=times,
    )


def _start_soc() -> dict[str, float]:
    return {duration: 0.5 for duration in REFERENCE_DURATIONS}


def test_one_result_per_duration():
    cfg = bess_config()
    assets = build_assets()
    result = settle.settle_day(_DAY, _prices(24), cfg, assets, _start_soc())

    assert result is not None
    assert result.date == _DAY
    assert set(result.durations) == set(REFERENCE_DURATIONS)
    assert len(result.durations) == len(REFERENCE_DURATIONS)


def test_pnl_buckets_sum_to_net_pnl():
    cfg = bess_config()
    assets = build_assets()
    result = settle.settle_day(_DAY, _prices(24), cfg, assets, _start_soc())

    assert result is not None
    for dur in result.durations.values():
        reconstructed = (
            dur.benchmark_da_revenue
            + dur.intraday_da_improvement
            - dur.execution_costs_paid
            - dur.degradation_cost
        )
        assert reconstructed == pytest.approx(dur.net_pnl, abs=1e-6)


def test_soc_stays_within_band():
    cfg = bess_config()
    assets = build_assets()
    min_pct = cfg["min_soc_pct"]
    max_pct = cfg["max_soc_pct"]
    result = settle.settle_day(_DAY, _prices(24), cfg, assets, _start_soc())

    assert result is not None
    tol = 1e-6
    for dur in result.durations.values():
        assert min_pct - tol <= dur.end_soc <= max_pct + tol
        for entry in dur.dispatch_log:
            assert min_pct - tol <= entry["soc_before"] <= max_pct + tol
            assert min_pct - tol <= entry["soc_after"] <= max_pct + tol


@pytest.mark.parametrize("n_periods", [23, 25])
def test_dst_days_are_handled(n_periods: int):
    cfg = bess_config()
    assets = build_assets()
    result = settle.settle_day(_DAY, _prices(n_periods), cfg, assets, _start_soc())

    assert result is not None
    assert set(result.durations) == set(REFERENCE_DURATIONS)
    for dur in result.durations.values():
        assert len(dur.da_schedule) == n_periods
        assert len(dur.dispatch_log) == n_periods


@pytest.mark.parametrize("n_periods", [0, 22, 26, 48])
def test_invalid_period_count_returns_none(n_periods: int):
    cfg = bess_config()
    assets = build_assets()
    result = settle.settle_day(
        _DAY, _prices(max(n_periods, 1))[:n_periods], cfg, assets, _start_soc()
    )

    assert result is None


def test_capture_equals_net_pnl_over_arbitrage_bound():
    # Capture must be exactly realised net PnL divided by the perfect-foresight
    # day-ahead arbitrage ceiling, recomputed from the same starting SOC.
    cfg = bess_config()
    assets = build_assets()
    prices = _prices(24)
    start = _start_soc()
    result = settle.settle_day(_DAY, prices, cfg, assets, start)

    assert result is not None
    day_ahead_prices = prices["day_ahead_price"].tolist()
    duration_h = cfg.get("resolution_h", 1.0)
    for name, dur in result.durations.items():
        asset = assets[name]
        asset.reset(start[name])
        upper_bound = settle._arbitrage_upper_bound(day_ahead_prices, asset, duration_h)
        assert upper_bound > settle._CAPTURE_EPS
        assert dur.capture == pytest.approx(dur.net_pnl / upper_bound)


def test_flat_prices_give_near_zero_pnl():
    cfg = bess_config()
    assets = build_assets()
    # Start at the SOC floor so there is no stored inventory to liquidate at the
    # (positive) flat price; with no price spread either, the battery has no
    # arbitrage to act on and should book essentially nothing.
    start = {duration: cfg["min_soc_pct"] for duration in REFERENCE_DURATIONS}
    result = settle.settle_day(_DAY, _flat_prices(), cfg, assets, start)

    assert result is not None
    for dur in result.durations.values():
        assert dur.net_pnl == pytest.approx(0.0, abs=1.0)
        assert dur.capture == 0.0
