"""Book budgets must act on commitments and information available at auction."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import run_backtest_from_dataframe
from src.backtest.risk import BookRiskPolicy


def frame(prices):
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01T12:00:00Z", periods=len(prices), freq="D"),
            "signal": 1,
            "day_ahead_price": 50.0,
            "system_sell_price": prices,
            "system_buy_price": 50.0,
        }
    )


def test_total_book_quantity_respects_gross_stress_budget():
    data = frame([60.0] * 30)
    data["time"] = pd.date_range("2024-01-01T00:00:00Z", periods=30, freq="30min")
    _, m = run_backtest_from_dataframe(data, book_risk_policy=BookRiskPolicy())
    assert m["total_position_mwh"] == pytest.approx(500 / 52.1)
    assert m["risk_book_ledger"][0]["new_book_stress"] == pytest.approx(500)


def test_pending_budget_is_reserved_until_publication_and_then_released():
    policy = BookRiskPolicy(outstanding_loss_budget_pct=0.015)
    _, m = run_backtest_from_dataframe(
        frame([50.0] * 6),
        starting_capital=1000,
        cost_per_trade=0,
        slippage=0,
        risk_pct=1,
        book_risk_policy=policy,
        settlement_publication_lag_h=72,
    )
    ledger = m["risk_book_ledger"]
    np.testing.assert_allclose([r["new_book_stress"] for r in ledger], [10, 5, 0, 0, 0, 10])
    assert m["halted_at_period"] is None
    assert m["n_trades"] == 3


def test_future_book_pnl_cannot_change_available_equity_or_risk_allocation():
    results = []
    for future_price in [-1000.0, 1000.0]:
        _, m = run_backtest_from_dataframe(
            frame([40.0, future_price, 50.0]),
            cost_per_trade=0,
            slippage=0,
            book_risk_policy=BookRiskPolicy(),
        )
        results.append(m["risk_book_ledger"])
    assert results[0] == results[1]


@pytest.mark.parametrize(
    "equity,scale", [(1000, 1), (950, 1), (900, 0.625), (850, 0.25), (800, 0.25)]
)
def test_drawdown_reduces_new_risk_gradually(equity, scale):
    assert BookRiskPolicy().scale(equity, 1000) == pytest.approx(scale)


def test_extreme_loss_still_triggers_the_hard_floor():
    _, m = run_backtest_from_dataframe(
        frame([-5000.0, 50.0, 50.0]),
        book_risk_policy=BookRiskPolicy(),
        cost_per_trade=0,
        slippage=0,
    )
    assert m["halted_at_period"] == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stress_move_gbp_per_mwh": 0},
        {"stress_move_gbp_per_mwh": float("nan")},
        {"daily_loss_budget_pct": 0.03, "outstanding_loss_budget_pct": 0.02},
        {"minimum_scale": 0},
        {"reduce_at_drawdown": 0.2},
    ],
)
def test_invalid_policy_is_rejected(kwargs):
    with pytest.raises(ValueError):
        BookRiskPolicy(**kwargs)
