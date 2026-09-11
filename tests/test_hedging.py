import numpy as np
import pandas as pd
import pytest

from src.evaluation.hedging import fixed_volume_hedges, summarise_hedges


def prices():
    return pd.DataFrame(
        {
            "time": pd.date_range("2018-08-20 16:00", periods=3, freq="30min", tz="UTC"),
            "signal": [1, -1, 0],
            "day_ahead_price": [50.0, 90.0, 10.0],
            "system_sell_price": [70.0, 42.0, 20.0],
            "system_buy_price": [75.0, 42.0, 20.0],
            "mid_price": [60.0, 160.0, 100.0],
            "predicted_spread": [20.0, -20.0, 0.0],
        }
    )


def test_long_short_endpoints_and_no_trade_costs():
    ledger, _ = fixed_volume_hedges(prices())
    np.testing.assert_allclose(ledger["pnl_0"], [19, 47, 0])
    np.testing.assert_allclose(ledger["pnl_1"], [7, -73, 0])
    np.testing.assert_allclose(ledger["pnl_0.5"], [13, -13, 0])


def test_shared_mask_does_not_give_cashout_extra_observations():
    frame = prices()
    frame.loc[1, "mid_price"] = np.nan
    frame.loc[2, "day_ahead_price"] = np.inf
    ledger, daily = fixed_volume_hedges(frame)
    assert ledger["entry_mwh"].tolist() == [1, 0, 0]
    assert daily[0.0].iloc[0] == 19
    assert ledger.filter(like="pnl_").notna().all().all()


def test_unpriced_day_is_missing_but_priced_no_signal_day_is_zero():
    frame = prices()
    frame["time"] = pd.date_range("2018-08-20", periods=3, freq="D", tz="UTC")
    frame.loc[1, "mid_price"] = np.nan
    _, daily = fixed_volume_hedges(frame)
    assert daily.iloc[1].isna().all()
    assert daily.iloc[2].eq(0).all()


def test_negative_prices_linear_quantity_and_additive_cost_attribution():
    frame = prices()
    frame.loc[0, "day_ahead_price"] = -10
    one, _ = fixed_volume_hedges(frame)
    two, _ = fixed_volume_hedges(frame, quantity_mwh=2)
    np.testing.assert_allclose(two.filter(like="pnl_"), 2 * one.filter(like="pnl_"))
    effect = 0.5 * (one.intraday_gross - one.imbalance_gross) - one.entry_mwh
    np.testing.assert_allclose(one["pnl_0.5"] - one["pnl_0"], effect)


@pytest.mark.parametrize("h", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_payoffs_match_engine_for_one_fixed_volume_auction(h):
    from src.backtest.engine import run_backtest_from_dataframe

    frame = prices()
    ledger, _ = fixed_volume_hedges(frame, hedge_ratios=(h,))
    result, _ = run_backtest_from_dataframe(
        frame,
        starting_capital=50000,
        risk_pct=0.001,
        cost_per_trade=1,
        mid_price_col="mid_price",
        predicted_spread_col="predicted_spread",
        baseline_hedge_ratio=h,
        take_profit_pct=float("inf"),
        stop_loss_price_delta=float("inf"),
        slippage=2,
    )
    np.testing.assert_allclose(result["pnl"], ledger[f"pnl_{h:g}"], atol=1e-12)


def test_drawdown_starts_at_zero_and_tail_uses_priced_dates():
    daily = pd.DataFrame({0.0: [-10, -20, np.nan, 5, 40]})
    result = summarise_hedges(daily).loc[0.0]
    assert result.net_pnl == 15
    assert result.max_drawdown == -30
    assert result.tail_mean_5pct == -20
    assert result.priced_days == 4


def test_london_market_date_across_midnight():
    frame = prices()
    frame["time"] = pd.date_range("2018-07-22 23:00", periods=3, freq="30min", tz="UTC")
    _, daily = fixed_volume_hedges(frame)
    assert str(daily.index[0].date()) == "2018-07-23"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quantity_mwh": 0},
        {"hedge_ratios": (1.1,)},
        {"hedge_ratios": (0, 0)},
        {"crossing_per_mwh": -1},
    ],
)
def test_invalid_assumptions_rejected(kwargs):
    with pytest.raises(ValueError):
        fixed_volume_hedges(prices(), **kwargs)


def test_duplicate_delivery_period_rejected():
    with pytest.raises(ValueError, match="unique"):
        fixed_volume_hedges(pd.concat([prices(), prices()]))
