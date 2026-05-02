"""Unit tests for src/backtest/engine.py — run_backtest and run_backtest_from_dataframe."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import run_backtest, run_backtest_from_dataframe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat(n: int, da: float = 50.0, ssp: float = 60.0, sbp: float = 65.0):
    """n periods of constant prices, all neutral signals."""
    return (
        np.zeros(n, dtype=int),
        np.full(n, da),
        np.full(n, ssp),
        np.full(n, sbp),
    )


# ---------------------------------------------------------------------------
# run_backtest — basic mechanics
# ---------------------------------------------------------------------------

class TestRunBacktestBasic:
    def test_all_neutral_zero_pnl(self):
        sigs, da, ssp, sbp = _flat(10)
        pnl, metrics = run_backtest(sigs, da, ssp, sbp)
        assert np.all(pnl == 0.0)
        assert metrics["total_pnl"] == pytest.approx(0.0)

    def test_final_capital_equals_start_when_no_trades(self):
        sigs, da, ssp, sbp = _flat(10)
        _, metrics = run_backtest(sigs, da, ssp, sbp, starting_capital=50_000)
        assert metrics["final_capital"] == pytest.approx(50_000.0)

    def test_mismatched_array_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            run_backtest(
                np.array([1]),
                np.array([50.0, 50.0]),  # length mismatch
                np.array([60.0]),
                np.array([65.0]),
            )

    def test_output_pnl_length_equals_input(self):
        sigs, da, ssp, sbp = _flat(20)
        pnl, _ = run_backtest(sigs, da, ssp, sbp)
        assert len(pnl) == 20


# ---------------------------------------------------------------------------
# Long trade (signal = 1): profit when SSP > DA
# ---------------------------------------------------------------------------

class TestLongTrade:
    def test_profitable_long_pnl_positive(self):
        # DA=50, SSP=70 → gross = (70-50) * position; net = gross - cost*position
        sigs = np.array([1])
        da   = np.array([50.0])
        ssp  = np.array([70.0])
        sbp  = np.array([75.0])
        pnl, _ = run_backtest(sigs, da, ssp, sbp, starting_capital=50_000, risk_pct=0.02, cost_per_trade=0.0)
        position = 50_000 * 0.02 / 50.0
        expected_gross = position * (70.0 - 50.0)
        assert pnl[0] == pytest.approx(expected_gross, rel=1e-6)

    def test_losing_long_pnl_negative(self):
        sigs = np.array([1])
        da   = np.array([50.0])
        ssp  = np.array([30.0])    # SSP < DA → loss
        sbp  = np.array([35.0])
        pnl, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert pnl[0] < 0.0

    def test_transaction_cost_reduces_pnl(self):
        sigs = np.array([1])
        da   = np.array([50.0])
        ssp  = np.array([70.0])
        sbp  = np.array([75.0])
        pnl_no_cost, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        pnl_with_cost, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=1.0)
        assert pnl_with_cost[0] < pnl_no_cost[0]


# ---------------------------------------------------------------------------
# Short trade (signal = -1): profit when DA > SBP
# ---------------------------------------------------------------------------

class TestShortTrade:
    def test_profitable_short_pnl_positive(self):
        # DA=80, SBP=60 → gross = (80-60)*position
        sigs = np.array([-1])
        da   = np.array([80.0])
        ssp  = np.array([55.0])
        sbp  = np.array([60.0])
        pnl, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert pnl[0] > 0.0

    def test_losing_short_pnl_negative(self):
        sigs = np.array([-1])
        da   = np.array([50.0])
        ssp  = np.array([55.0])
        sbp  = np.array([70.0])    # SBP > DA → loss
        pnl, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert pnl[0] < 0.0

    def test_short_pnl_formula(self):
        sigs = np.array([-1])
        da   = np.array([80.0])
        sbp  = np.array([60.0])
        ssp  = np.array([55.0])
        pnl, _ = run_backtest(sigs, da, ssp, sbp, starting_capital=50_000, risk_pct=0.02, cost_per_trade=0.0)
        position = 50_000 * 0.02 / 80.0
        expected = position * (80.0 - 60.0)
        assert pnl[0] == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

class TestPositionSizing:
    def test_position_scales_with_capital(self):
        """Larger capital → larger position → larger absolute PnL."""
        sigs = np.array([1])
        da   = np.array([50.0])
        ssp  = np.array([70.0])
        sbp  = np.array([75.0])
        pnl_small, _ = run_backtest(sigs, da, ssp, sbp, starting_capital=10_000, cost_per_trade=0.0)
        pnl_large, _ = run_backtest(sigs, da, ssp, sbp, starting_capital=100_000, cost_per_trade=0.0)
        assert abs(pnl_large[0]) > abs(pnl_small[0])

    def test_near_zero_da_price_floored_at_10(self):
        """DA price < 10 should be treated as 10 (floor guard)."""
        sigs = np.array([1])
        da   = np.array([1.0])   # would give huge position without floor
        ssp  = np.array([70.0])
        sbp  = np.array([75.0])
        pnl, _ = run_backtest(sigs, da, ssp, sbp, starting_capital=50_000, risk_pct=0.02, cost_per_trade=0.0)
        # With floor=10: position = 50000*0.02/10 = 100 MWh
        expected = 100.0 * (70.0 - 1.0)
        assert pnl[0] == pytest.approx(expected, rel=1e-6)

    def test_negative_da_price_uses_abs_floor(self):
        sigs = np.array([1])
        da   = np.array([-5.0])   # negative price; abs(-5)=5 < 10 → floor at 10
        ssp  = np.array([0.0])
        sbp  = np.array([5.0])
        pnl, _ = run_backtest(sigs, da, ssp, sbp, starting_capital=50_000, risk_pct=0.02, cost_per_trade=0.0)
        position = 50_000 * 0.02 / 10.0
        expected = position * (0.0 - (-5.0))
        assert pnl[0] == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Max drawdown halt
# ---------------------------------------------------------------------------

class TestDrawdownHalt:
    def test_simulation_halts_when_drawdown_breached(self):
        # Start with 1000; max_drawdown_pct=0.1 → floor=900
        # Each losing trade loses >100 so the first trade should halt
        sigs = np.array([1, 1, 1])          # 3 long signals
        da   = np.array([50.0, 50.0, 50.0])
        ssp  = np.array([0.0,  0.0,  0.0])  # SSP=0 → big loss per trade
        sbp  = np.array([55.0, 55.0, 55.0])
        pnl, metrics = run_backtest(
            sigs, da, ssp, sbp,
            starting_capital=1_000,
            risk_pct=1.0,          # 100% risk → position = 1000/50 = 20 MWh
            max_drawdown_pct=0.10, # floor = 900; first loss = 20*(0-50) = -1000 → capital -0
            cost_per_trade=0.0,
        )
        assert metrics["halted_at_period"] is not None

    def test_no_halt_when_pnl_positive(self):
        sigs = np.array([1, 1, 1])
        da   = np.array([50.0] * 3)
        ssp  = np.array([70.0] * 3)  # profitable
        sbp  = np.array([75.0] * 3)
        _, metrics = run_backtest(sigs, da, ssp, sbp)
        assert metrics["halted_at_period"] is None


# ---------------------------------------------------------------------------
# Metrics correctness
# ---------------------------------------------------------------------------

class TestMetrics:
    def _single_win_loss(self):
        # Period 0: WIN long  (SSP > DA)
        # Period 1: LOSS long (SSP < DA)
        sigs = np.array([1, 1])
        da   = np.array([50.0, 50.0])
        ssp  = np.array([70.0, 30.0])
        sbp  = np.array([75.0, 35.0])
        return run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)

    def test_n_trades(self):
        _, metrics = self._single_win_loss()
        assert metrics["n_trades"] == 2

    def test_win_rate(self):
        _, metrics = self._single_win_loss()
        assert metrics["win_rate"] == pytest.approx(0.5)

    def test_total_return_pct_sign(self):
        # All winning → positive return
        sigs = np.array([1] * 5)
        da   = np.array([50.0] * 5)
        ssp  = np.array([70.0] * 5)
        sbp  = np.array([75.0] * 5)
        _, metrics = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert metrics["total_return_pct"] > 0.0

    def test_max_drawdown_is_zero_or_negative(self):
        sigs, da, ssp, sbp = _flat(10)
        _, metrics = run_backtest(sigs, da, ssp, sbp)
        assert metrics["max_drawdown"] <= 0.0

    def test_profit_factor_infinity_when_no_losses(self):
        sigs = np.array([1])
        da   = np.array([50.0])
        ssp  = np.array([70.0])
        sbp  = np.array([75.0])
        _, metrics = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert metrics["profit_factor"] == float("inf")

    def test_signal_distribution_counts(self):
        sigs = np.array([1, -1, 0, 1])
        da   = np.array([50.0] * 4)
        ssp  = np.array([60.0] * 4)
        sbp  = np.array([65.0] * 4)
        _, metrics = run_backtest(sigs, da, ssp, sbp)
        dist = metrics["signal_distribution"]
        assert dist["long"]    == 2
        assert dist["short"]   == 1
        assert dist["neutral"] == 1

    def test_starting_capital_in_metrics(self):
        _, metrics = run_backtest(*_flat(5), starting_capital=42_000)
        assert metrics["starting_capital"] == pytest.approx(42_000.0)


# ---------------------------------------------------------------------------
# Daily aggregation
# ---------------------------------------------------------------------------

class TestDailyAggregation:
    def test_daily_summary_present_when_timestamps_given(self):
        ts   = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        sigs = np.array([1, 1, -1, 0])
        da   = np.array([50.0] * 4)
        ssp  = np.array([60.0] * 4)
        sbp  = np.array([65.0] * 4)
        _, metrics = run_backtest(sigs, da, ssp, sbp, timestamps=ts)
        assert metrics["daily_summary"] != {}
        assert "mean_daily_pnl" in metrics["daily_summary"]

    def test_daily_summary_empty_when_no_timestamps(self):
        _, metrics = run_backtest(*_flat(4))
        assert metrics["daily_summary"] == {}


# ---------------------------------------------------------------------------
# run_backtest_from_dataframe
# ---------------------------------------------------------------------------

class TestRunBacktestFromDataframe:
    def _make_df(self, n: int = 4, signal_val: int = 1):
        ts = pd.date_range("2018-01-10", periods=n, freq="30min", tz="UTC")
        return pd.DataFrame({
            "time":             ts,
            "signal":           [signal_val] * n,
            "day_ahead_price":  [50.0] * n,
            "system_sell_price":[70.0] * n,
            "system_buy_price": [75.0] * n,
        })

    def test_pnl_column_added_to_output(self):
        df_out, _ = run_backtest_from_dataframe(self._make_df())
        assert "pnl" in df_out.columns

    def test_pnl_column_length_matches_input(self):
        df = self._make_df(6)
        df_out, _ = run_backtest_from_dataframe(df)
        assert len(df_out) == 6

    def test_all_neutral_pnl_column_zero(self):
        df = self._make_df(signal_val=0)
        df_out, _ = run_backtest_from_dataframe(df)
        assert (df_out["pnl"] == 0.0).all()

    def test_metrics_returned(self):
        _, metrics = run_backtest_from_dataframe(self._make_df())
        assert "total_pnl" in metrics
        assert "sharpe_ratio" in metrics
