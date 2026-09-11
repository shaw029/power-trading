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

    @pytest.mark.parametrize("ratio", [-0.1, 1.01, -1.0, 2.0])
    def test_invalid_baseline_hedge_ratio_raises(self, ratio):
        sigs, da, ssp, sbp = _flat(5)
        with pytest.raises(ValueError, match="baseline_hedge_ratio"):
            run_backtest(sigs, da, ssp, sbp, baseline_hedge_ratio=ratio)

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
        da = np.array([50.0])
        ssp = np.array([70.0])
        sbp = np.array([75.0])
        pnl, _ = run_backtest(
            sigs, da, ssp, sbp, starting_capital=50_000, risk_pct=0.02, cost_per_trade=0.0
        )
        position = 50_000 * 0.02 / 50.0
        expected_gross = position * (70.0 - 50.0)
        assert pnl[0] == pytest.approx(expected_gross, rel=1e-6)

    def test_losing_long_pnl_negative(self):
        sigs = np.array([1])
        da = np.array([50.0])
        ssp = np.array([30.0])  # SSP < DA → loss
        sbp = np.array([35.0])
        pnl, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert pnl[0] < 0.0

    def test_slippage_reduces_hybrid_pnl(self):
        """Slippage widens the bid-ask cost on intraday mid-price exits."""
        sigs = np.array([1])
        da = np.array([50.0])
        ssp = np.array([70.0])
        sbp = np.array([75.0])
        common = dict(
            mid_prices=np.array([65.0]),
            predicted_spreads=np.array([20.0]),
            cost_per_trade=0.0,
        )
        pnl_no_slip, _ = run_backtest(sigs, da, ssp, sbp, slippage=0.0, **common)
        pnl_with_slip, _ = run_backtest(sigs, da, ssp, sbp, slippage=2.0, **common)
        assert pnl_with_slip[0] < pnl_no_slip[0]

    def test_transaction_cost_reduces_pnl(self):
        sigs = np.array([1])
        da = np.array([50.0])
        ssp = np.array([70.0])
        sbp = np.array([75.0])
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
        da = np.array([80.0])
        ssp = np.array([55.0])
        sbp = np.array([60.0])
        pnl, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert pnl[0] > 0.0

    def test_losing_short_pnl_negative(self):
        sigs = np.array([-1])
        da = np.array([50.0])
        ssp = np.array([55.0])
        sbp = np.array([70.0])  # SBP > DA → loss
        pnl, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert pnl[0] < 0.0

    def test_short_pnl_formula(self):
        sigs = np.array([-1])
        da = np.array([80.0])
        sbp = np.array([60.0])
        ssp = np.array([55.0])
        pnl, _ = run_backtest(
            sigs, da, ssp, sbp, starting_capital=50_000, risk_pct=0.02, cost_per_trade=0.0
        )
        position = 50_000 * 0.02 / 50.0
        expected = position * (80.0 - 60.0)
        assert pnl[0] == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------


class TestPositionSizing:
    def test_position_scales_with_capital(self):
        """Larger capital → larger position → larger absolute PnL."""
        sigs = np.array([1])
        da = np.array([50.0])
        ssp = np.array([70.0])
        sbp = np.array([75.0])
        pnl_small, _ = run_backtest(sigs, da, ssp, sbp, starting_capital=10_000, cost_per_trade=0.0)
        pnl_large, _ = run_backtest(
            sigs, da, ssp, sbp, starting_capital=100_000, cost_per_trade=0.0
        )
        assert abs(pnl_large[0]) > abs(pnl_small[0])

    def test_near_zero_reference_price_floored_at_10(self):
        """DA price < 10 should be treated as 10 (floor guard)."""
        sigs = np.array([1])
        da = np.array([1.0])  # would give huge position without floor
        ssp = np.array([70.0])
        sbp = np.array([75.0])
        pnl, _ = run_backtest(
            sigs,
            da,
            ssp,
            sbp,
            starting_capital=50_000,
            risk_pct=0.02,
            cost_per_trade=0.0,
            sizing_prices=da,
        )
        # With floor=10: position = 50000*0.02/10 = 100 MWh
        expected = 100.0 * (70.0 - 1.0)
        assert pnl[0] == pytest.approx(expected, rel=1e-6)

    def test_negative_reference_price_uses_abs_floor(self):
        sigs = np.array([1])
        da = np.array([-5.0])  # negative price; abs(-5)=5 < 10 → floor at 10
        ssp = np.array([0.0])
        sbp = np.array([5.0])
        pnl, _ = run_backtest(
            sigs,
            da,
            ssp,
            sbp,
            starting_capital=50_000,
            risk_pct=0.02,
            cost_per_trade=0.0,
            sizing_prices=da,
        )
        position = 50_000 * 0.02 / 10.0
        expected = position * (0.0 - (-5.0))
        assert pnl[0] == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Max drawdown halt
# ---------------------------------------------------------------------------


class TestDrawdownHalt:
    def test_halt_reports_observable_equity_despite_pending_recovery(self, caplog):
        # Day 1 settles a loss; day 2's committed book recovers above the floor.
        # At the auction for day 3 only day 1 is observable, so it still halts.
        ts = pd.date_range("2024-01-01T12:00:00Z", periods=4, freq="D")
        pnl, metrics = run_backtest(
            np.ones(4),
            np.full(4, 50.0),
            np.array([20.0, 80.0, 80.0, 80.0]),
            np.full(4, 50.0),
            timestamps=ts,
            starting_capital=1000.0,
            risk_pct=0.5,
            cost_per_trade=0.0,
        )
        np.testing.assert_allclose(pnl, [-300.0, 300.0, 0.0, 0.0])
        assert metrics["halt_details"] == {
            "auction_time": "2024-01-02T10:30:00+00:00",
            "first_unbid_delivery_time": "2024-01-03T12:00:00+00:00",
            "settled_equity": 700.0,
            "booked_equity": 1000.0,
            "capital_floor": 800.0,
        }
        assert "settled equity £700 ≤ floor £800" in caplog.text

    def test_dataframe_wrapper_respects_sizing_and_publication_lag(self):
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01T12:00:00Z", periods=4, freq="D"),
                "signal": 1,
                "day_ahead_price": 50.0,
                "system_sell_price": 20.0,
                "system_buy_price": 50.0,
            }
        )
        # 5 MWh per book; a 30-hour publication delay leaves the first loss
        # unavailable until after the third book's auction.
        result, metrics = run_backtest_from_dataframe(
            df,
            starting_capital=1000.0,
            risk_pct=0.5,
            cost_per_trade=0.0,
            max_drawdown_pct=0.1,
            sizing_prices=np.full(4, 100.0),
            settlement_publication_lag_h=30.0,
        )
        np.testing.assert_allclose(result["pnl"], [-150.0, -150.0, -150.0, 0.0])
        assert metrics["halted_at_period"] == 3

    def test_dataframe_wrapper_sorts_reference_prices_with_their_rows(self):
        df = pd.DataFrame(
            {
                "time": pd.to_datetime(["2024-01-02", "2024-01-01"], utc=True),
                "signal": 1,
                "day_ahead_price": 50.0,
                "system_sell_price": 60.0,
                "system_buy_price": 50.0,
            }
        )
        result, _ = run_backtest_from_dataframe(
            df,
            starting_capital=1000.0,
            risk_pct=0.5,
            cost_per_trade=0.0,
            sizing_prices=np.array([100.0, 50.0]),
        )
        np.testing.assert_allclose(result["pnl"], [100.0, 50.0])

    def test_simulation_halts_once_the_loss_has_actually_settled(self):
        # Day 1 loses the account through the floor. Day 2's book was bid at
        # 10:30 on day 1, while day 1 was still delivering, so the halt cannot
        # know yet. It bites at day 3, the first auction held after day 1's
        # settlement was observable.
        sigs = np.array([1, 1, 1])
        da = np.array([50.0, 50.0, 50.0])
        ssp = np.array([0.0, 0.0, 0.0])  # SSP=0 → big loss per trade
        sbp = np.array([55.0, 55.0, 55.0])
        ts = pd.to_datetime(
            ["2024-01-01T12:00:00Z", "2024-01-02T12:00:00Z", "2024-01-03T12:00:00Z"], utc=True
        )
        pnl, metrics = run_backtest(
            sigs,
            da,
            ssp,
            sbp,
            timestamps=ts,
            starting_capital=1_000,
            risk_pct=1.0,  # 100% risk → position = 1000/50 = 20 MWh
            max_drawdown_pct=0.10,  # floor = 900; day 1 loses 20*(0-50) = -1000
            cost_per_trade=0.0,
        )
        assert metrics["halted_at_period"] is not None
        assert pnl[0] != 0.0  # day 1 traded
        assert pnl[1] != 0.0  # day 2 was already committed and could not be pulled
        assert pnl[2] == 0.0  # day 3 never bid

    def test_halt_cannot_cancel_contracts_already_in_the_book(self):
        # All three periods belong to one delivery day, so all three were bid at
        # one auction. A mid-day breach cannot retract them: doing so would let
        # the drawdown rule act on information that arrived after the commitment.
        sigs = np.array([1, 1, 1])
        da = np.array([50.0, 50.0, 50.0])
        ssp = np.array([0.0, 0.0, 0.0])
        sbp = np.array([55.0, 55.0, 55.0])
        ts = pd.to_datetime(
            ["2024-01-01T10:00:00Z", "2024-01-01T11:00:00Z", "2024-01-01T12:00:00Z"], utc=True
        )
        pnl, metrics = run_backtest(
            sigs,
            da,
            ssp,
            sbp,
            timestamps=ts,
            starting_capital=1_000,
            risk_pct=1.0,
            max_drawdown_pct=0.10,
            cost_per_trade=0.0,
        )
        assert metrics["halted_at_period"] is None
        assert (pnl != 0).all()

    def test_no_halt_when_pnl_positive(self):
        sigs = np.array([1, 1, 1])
        da = np.array([50.0] * 3)
        ssp = np.array([70.0] * 3)  # profitable
        sbp = np.array([75.0] * 3)
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
        da = np.array([50.0, 50.0])
        ssp = np.array([70.0, 30.0])
        sbp = np.array([75.0, 35.0])
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
        da = np.array([50.0] * 5)
        ssp = np.array([70.0] * 5)
        sbp = np.array([75.0] * 5)
        _, metrics = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert metrics["total_return_pct"] > 0.0

    def test_max_drawdown_is_zero_or_negative(self):
        sigs, da, ssp, sbp = _flat(10)
        _, metrics = run_backtest(sigs, da, ssp, sbp)
        assert metrics["max_drawdown"] <= 0.0

    def test_profit_factor_none_when_no_losses(self):
        sigs = np.array([1])
        da = np.array([50.0])
        ssp = np.array([70.0])
        sbp = np.array([75.0])
        _, metrics = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        assert metrics["profit_factor"] is None

    def test_signal_distribution_counts(self):
        sigs = np.array([1, -1, 0, 1])
        da = np.array([50.0] * 4)
        ssp = np.array([60.0] * 4)
        sbp = np.array([65.0] * 4)
        _, metrics = run_backtest(sigs, da, ssp, sbp)
        dist = metrics["signal_distribution"]
        assert dist["long"] == 2
        assert dist["short"] == 1
        assert dist["neutral"] == 1

    def test_starting_capital_in_metrics(self):
        _, metrics = run_backtest(*_flat(5), starting_capital=42_000)
        assert metrics["starting_capital"] == pytest.approx(42_000.0)


# ---------------------------------------------------------------------------
# Daily aggregation
# ---------------------------------------------------------------------------


class TestDailyAggregation:
    def test_daily_summary_present_when_timestamps_given(self):
        ts = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        sigs = np.array([1, 1, -1, 0])
        da = np.array([50.0] * 4)
        ssp = np.array([60.0] * 4)
        sbp = np.array([65.0] * 4)
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
        return pd.DataFrame(
            {
                "time": ts,
                "signal": [signal_val] * n,
                "day_ahead_price": [50.0] * n,
                "system_sell_price": [70.0] * n,
                "system_buy_price": [75.0] * n,
            }
        )

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


# ---------------------------------------------------------------------------
# Hybrid passive/active exit logic (mid_prices + predicted_spreads provided)
# ---------------------------------------------------------------------------


class TestHybridExecution:
    """Cover all six hybrid exit branches and supporting behaviour."""

    _CAP = 50_000.0
    _RISK = 0.02
    _DA = 50.0
    # position = 50_000 * 0.02 / 50 = 20 MWh; at default hedge_ratio=0.50 → passive=active=10 MWh

    def _run(self, signal, mid, pred_spread, ssp=70.0, sbp=40.0, **kw):
        # These tests verify the exit-branch arithmetic; the expected values
        # below are computed at £0.50 slippage and a 50/50 hedge split, pinned
        # explicitly so they never silently track the config defaults.
        kw.setdefault("slippage", 0.50)
        kw.setdefault("baseline_hedge_ratio", 0.50)
        return run_backtest(
            np.array([signal]),
            np.array([self._DA]),
            np.array([ssp]),
            np.array([sbp]),
            starting_capital=self._CAP,
            risk_pct=self._RISK,
            cost_per_trade=0.0,
            mid_prices=np.array([mid]),
            predicted_spreads=np.array([pred_spread]),
            **kw,
        )

    # ---- LONG — imbalance fallback (no TP, no SL) -------------------------

    def test_long_imbalance_fallback_pnl(self):
        # mid_adj=59.5; tp_level=50+20*0.9=68 → tp_hit=False; loss=-9.5 → sl_hit=False
        # active_exit=ssp=70; passive=10*(59.5-50)=95; active=10*(70-50)=200 → gross=295
        pnl, _ = self._run(signal=1, mid=60.0, pred_spread=20.0, ssp=70.0)
        assert pnl[0] == pytest.approx(295.0)

    def test_long_imbalance_increments_imbalance_counter(self):
        _, metrics = self._run(signal=1, mid=60.0, pred_spread=20.0)
        assert metrics["execution_breakdown"]["active_rode_to_imbalance"] == 1
        assert metrics["execution_breakdown"]["active_tp_triggered"] == 0
        assert metrics["execution_breakdown"]["active_sl_triggered"] == 0

    # ---- LONG — take-profit hit -------------------------------------------

    def test_long_take_profit_triggered_pnl(self):
        # mid_adj=74.5 >= tp_level=68 → tp_hit; active_exit=74.5
        # passive=10*(74.5-50)=245; active=10*(74.5-50)=245 → gross=490
        pnl, _ = self._run(signal=1, mid=75.0, pred_spread=20.0)
        assert pnl[0] == pytest.approx(490.0)

    def test_long_take_profit_increments_tp_counter(self):
        _, metrics = self._run(signal=1, mid=75.0, pred_spread=20.0)
        assert metrics["execution_breakdown"]["active_tp_triggered"] == 1
        assert metrics["execution_breakdown"]["active_sl_triggered"] == 0
        assert metrics["execution_breakdown"]["active_rode_to_imbalance"] == 0

    # ---- LONG — stop-loss hit ---------------------------------------------

    def test_long_stop_loss_triggered_pnl(self):
        # mid_adj=42.5; loss_per_mwh=50-42.5=7.5 >= stop_loss_price_delta=5 → sl_hit
        # passive=10*(42.5-50)=-75; active=10*(42.5-50)=-75 → gross=-150
        pnl, _ = self._run(signal=1, mid=43.0, pred_spread=20.0, stop_loss_price_delta=5.0)
        assert pnl[0] == pytest.approx(-150.0)

    def test_long_stop_loss_increments_sl_counter(self):
        _, metrics = self._run(signal=1, mid=43.0, pred_spread=20.0, stop_loss_price_delta=5.0)
        assert metrics["execution_breakdown"]["active_sl_triggered"] == 1
        assert metrics["execution_breakdown"]["active_tp_triggered"] == 0
        assert metrics["execution_breakdown"]["active_rode_to_imbalance"] == 0

    # ---- SHORT — imbalance fallback (no TP, no SL) ------------------------

    def test_short_imbalance_fallback_pnl(self):
        # mid_adj=45.5; tp_level=50+(-15)*0.9=36.5 → tp_hit=False; loss=-4.5 → sl_hit=False
        # active_exit=sbp=40; passive=10*(50-45.5)=45; active=10*(50-40)=100 → gross=145
        pnl, _ = self._run(signal=-1, mid=45.0, pred_spread=-15.0, sbp=40.0)
        assert pnl[0] == pytest.approx(145.0)

    def test_short_imbalance_increments_imbalance_counter(self):
        _, metrics = self._run(signal=-1, mid=45.0, pred_spread=-15.0)
        assert metrics["execution_breakdown"]["active_rode_to_imbalance"] == 1
        assert metrics["execution_breakdown"]["active_tp_triggered"] == 0
        assert metrics["execution_breakdown"]["active_sl_triggered"] == 0

    # ---- SHORT — take-profit hit ------------------------------------------

    def test_short_take_profit_triggered_pnl(self):
        # mid_adj=33.5 <= tp_level=36.5 → tp_hit; active_exit=33.5
        # passive=10*(50-33.5)=165; active=10*(50-33.5)=165 → gross=330
        pnl, _ = self._run(signal=-1, mid=33.0, pred_spread=-15.0)
        assert pnl[0] == pytest.approx(330.0)

    def test_short_take_profit_increments_tp_counter(self):
        _, metrics = self._run(signal=-1, mid=33.0, pred_spread=-15.0)
        assert metrics["execution_breakdown"]["active_tp_triggered"] == 1
        assert metrics["execution_breakdown"]["active_sl_triggered"] == 0
        assert metrics["execution_breakdown"]["active_rode_to_imbalance"] == 0

    # ---- SHORT — stop-loss hit --------------------------------------------

    def test_short_stop_loss_triggered_pnl(self):
        # mid_adj=57.5; loss_per_mwh=57.5-50=7.5 >= stop_loss_price_delta=5 → sl_hit
        # passive=10*(50-57.5)=-75; active=10*(50-57.5)=-75 → gross=-150
        pnl, _ = self._run(signal=-1, mid=57.0, pred_spread=-15.0, stop_loss_price_delta=5.0)
        assert pnl[0] == pytest.approx(-150.0)

    def test_short_stop_loss_increments_sl_counter(self):
        _, metrics = self._run(signal=-1, mid=57.0, pred_spread=-15.0, stop_loss_price_delta=5.0)
        assert metrics["execution_breakdown"]["active_sl_triggered"] == 1
        assert metrics["execution_breakdown"]["active_tp_triggered"] == 0
        assert metrics["execution_breakdown"]["active_rode_to_imbalance"] == 0

    # ---- Multi-period breakdown counter accumulation ----------------------

    def test_execution_breakdown_accumulates_across_periods(self):
        # Period 0: long TP hit (mid=75, pred=20)
        # Period 1: short imbalance (mid=45, pred=-15)
        # Period 2: long SL hit  (mid=43, pred=20)
        sigs = np.array([1, -1, 1])
        da = np.array([self._DA] * 3)
        ssp = np.array([70.0] * 3)
        sbp = np.array([40.0] * 3)
        _, metrics = run_backtest(
            sigs,
            da,
            ssp,
            sbp,
            starting_capital=self._CAP,
            risk_pct=self._RISK,
            cost_per_trade=0.0,
            mid_prices=np.array([75.0, 45.0, 43.0]),
            predicted_spreads=np.array([20.0, -15.0, 20.0]),
            stop_loss_price_delta=5.0,
        )
        bd = metrics["execution_breakdown"]
        assert bd["active_tp_triggered"] == 1
        assert bd["active_sl_triggered"] == 1
        assert bd["active_rode_to_imbalance"] == 1

    # ---- LONG — double hit: both TP and SL true, TP takes precedence ------

    def test_long_double_hit_counts_as_tp(self):
        # pred_spread=-20 → tp_level=50+(-20)*0.9=32; stop_loss_price_delta=5
        # mid_adj=42.5; tp_hit: 42.5>=32 True; loss=50-42.5=7.5>=5 True
        # Both fire → counted as TP, not SL
        _, metrics = self._run(
            signal=1,
            mid=43.0,
            pred_spread=-20.0,
            stop_loss_price_delta=5.0,
        )
        assert metrics["execution_breakdown"]["active_tp_triggered"] == 1
        assert metrics["execution_breakdown"]["active_sl_triggered"] == 0

    def test_long_double_hit_exit_price_is_mid_adj(self):
        # Exit price is mid_adj regardless of which flag wins
        # mid_adj=42.5; passive=10*(42.5-50)=-75; active=10*(42.5-50)=-75 → gross=-150
        pnl, _ = self._run(
            signal=1,
            mid=43.0,
            pred_spread=-20.0,
            stop_loss_price_delta=5.0,
        )
        assert pnl[0] == pytest.approx(-150.0)

    # ---- SHORT — double hit: both TP and SL true, TP takes precedence ----

    def test_short_positive_pred_spread_triggers_sl(self):
        # pred_spread=+20 (atypical) → tp_level=50-20*0.9=32; stop_loss_price_delta=5
        # mid_adj=56.5; tp_hit: 56.5<=32 False; loss=56.5-50=6.5>=5 True
        # Only SL fires — positive pred_spread no longer inflates tp_level above DA
        _, metrics = self._run(
            signal=-1,
            mid=56.0,
            pred_spread=20.0,
            stop_loss_price_delta=5.0,
        )
        assert metrics["execution_breakdown"]["active_tp_triggered"] == 0
        assert metrics["execution_breakdown"]["active_sl_triggered"] == 1

    def test_short_positive_pred_spread_sl_exit_uses_mid_adj(self):
        # mid_adj=56.5; passive=10*(50-56.5)=-65; active=10*(50-56.5)=-65 → gross=-130
        pnl, _ = self._run(
            signal=-1,
            mid=56.0,
            pred_spread=20.0,
            stop_loss_price_delta=5.0,
        )
        assert pnl[0] == pytest.approx(-130.0)

    # ---- NaN mid → baseline fallback --------------------------------------

    def test_nan_mid_price_falls_back_to_baseline(self):
        # NaN mid → hybrid branch skipped → active exit uses SSP directly
        sigs = np.array([1])
        da = np.array([self._DA])
        ssp = np.array([70.0])
        sbp = np.array([75.0])
        pnl_base, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        pnl_nan, _ = run_backtest(
            sigs,
            da,
            ssp,
            sbp,
            cost_per_trade=0.0,
            mid_prices=np.array([np.nan]),
            predicted_spreads=np.array([20.0]),
        )
        assert pnl_nan[0] == pytest.approx(pnl_base[0])

    def test_nan_predicted_spread_falls_back_to_baseline(self):
        sigs = np.array([1])
        da = np.array([self._DA])
        ssp = np.array([70.0])
        sbp = np.array([75.0])
        pnl_base, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        pnl_nan, _ = run_backtest(
            sigs,
            da,
            ssp,
            sbp,
            cost_per_trade=0.0,
            mid_prices=np.array([60.0]),
            predicted_spreads=np.array([np.nan]),
        )
        assert pnl_nan[0] == pytest.approx(pnl_base[0])

    # ---- Mid/pred array length validation ---------------------------------

    def test_mid_prices_wrong_length_raises(self):
        sigs = np.array([1, 1])
        da = np.array([self._DA] * 2)
        ssp = np.array([70.0] * 2)
        sbp = np.array([75.0] * 2)
        with pytest.raises(ValueError, match="same length"):
            run_backtest(
                sigs,
                da,
                ssp,
                sbp,
                mid_prices=np.array([60.0]),
                predicted_spreads=np.array([20.0, 20.0]),
            )

    # ---- Hybrid produces different outcome than pure baseline -------------

    def test_hybrid_differs_from_baseline_when_tp_hit(self):
        # TP at mid=75 exits active slice at 74.5, not at ssp=60 → different total
        sigs = np.array([1])
        da = np.array([self._DA])
        ssp = np.array([60.0])
        sbp = np.array([65.0])
        pnl_base, _ = run_backtest(sigs, da, ssp, sbp, cost_per_trade=0.0)
        pnl_hybrid, _ = run_backtest(
            sigs,
            da,
            ssp,
            sbp,
            cost_per_trade=0.0,
            mid_prices=np.array([75.0]),
            predicted_spreads=np.array([20.0]),
        )
        assert pnl_hybrid[0] != pytest.approx(pnl_base[0])


# ---------------------------------------------------------------------------
# NaN in da_prices / system_sell_price / system_buy_price
# ---------------------------------------------------------------------------


class TestNaNPriceInputs:
    """NaN in core price arrays must not corrupt current_capital."""

    _CAP = 50_000.0
    _RISK = 0.02

    def test_nan_da_price_skips_period_zero_pnl(self):
        pnl, _ = run_backtest(
            np.array([1]),
            np.array([np.nan]),
            np.array([70.0]),
            np.array([75.0]),
            starting_capital=self._CAP,
            risk_pct=self._RISK,
            cost_per_trade=0.0,
        )
        assert np.isfinite(pnl[0])
        assert pnl[0] == pytest.approx(0.0)

    def test_nan_system_sell_price_skips_period_zero_pnl(self):
        pnl, _ = run_backtest(
            np.array([1]),
            np.array([50.0]),
            np.array([np.nan]),
            np.array([75.0]),
            starting_capital=self._CAP,
            risk_pct=self._RISK,
            cost_per_trade=0.0,
        )
        assert np.isfinite(pnl[0])
        assert pnl[0] == pytest.approx(0.0)

    def test_nan_system_buy_price_skips_period_zero_pnl(self):
        pnl, _ = run_backtest(
            np.array([-1]),
            np.array([50.0]),
            np.array([45.0]),
            np.array([np.nan]),
            starting_capital=self._CAP,
            risk_pct=self._RISK,
            cost_per_trade=0.0,
        )
        assert np.isfinite(pnl[0])
        assert pnl[0] == pytest.approx(0.0)

    def test_nan_period_does_not_corrupt_capital_for_subsequent_trade(self):
        # Period 0: NaN da_price → skipped; capital stays at 50_000
        # Period 1: valid long with DA=50, SSP=70 → normal PnL
        sigs = np.array([1, 1])
        da = np.array([np.nan, 50.0])
        ssp = np.array([70.0, 70.0])
        sbp = np.array([75.0, 75.0])
        pnl, metrics = run_backtest(
            sigs,
            da,
            ssp,
            sbp,
            starting_capital=self._CAP,
            risk_pct=self._RISK,
            cost_per_trade=0.0,
        )
        assert np.isfinite(pnl[0])
        assert pnl[0] == pytest.approx(0.0)
        # Period 1 should trade at full starting capital (not NaN-tainted)
        expected_position = self._CAP * self._RISK / 50.0
        expected_pnl1 = expected_position * (70.0 - 50.0)
        assert pnl[1] == pytest.approx(expected_pnl1, rel=1e-6)
        assert np.isfinite(metrics["final_capital"])


# ---------------------------------------------------------------------------
# Auction-book sizing and the execution ledger
# ---------------------------------------------------------------------------


class TestAuctionBookSizing:
    """One auction commits a whole delivery day, so sizing cannot learn from it."""

    def _two_contracts(self, first_mid: float):
        ts = pd.to_datetime(["2024-01-01T10:00:00Z", "2024-01-01T11:00:00Z"], utc=True)
        return run_backtest(
            signals=np.array([1, 1]),
            da_prices=np.array([50.0, 50.0]),
            system_sell_price=np.array([50.0, 50.0]),
            system_buy_price=np.array([50.0, 50.0]),
            timestamps=ts,
            cost_per_trade=0.0,
            mid_prices=np.array([first_mid, 60.0]),
            predicted_spreads=np.array([10.0, 10.0]),
            baseline_hedge_ratio=1.0,
            slippage=0.0,
        )[0]

    def test_later_contract_is_unmoved_by_an_earlier_settlement(self):
        # Both contracts were bid at the same auction. Changing the first one's
        # cash-out price must not resize the second: it used to move it from
        # £200 to £204, which is the second contract responding to information
        # that did not exist when its quantity was chosen.
        flat = self._two_contracts(50.0)
        spiked = self._two_contracts(100.0)
        assert flat[1] == pytest.approx(spiked[1])

    def test_capital_compounds_once_a_book_has_settled(self):
        # Equity is released with a one-book lag: day 2 is bid while day 1 is
        # still delivering, so it cannot yet see day 1's result. Day 3 can.
        ts = pd.to_datetime(
            ["2024-01-01T12:00:00Z", "2024-01-02T12:00:00Z", "2024-01-03T12:00:00Z"], utc=True
        )
        pnl, _ = run_backtest(
            signals=np.array([1, 1, 1]),
            da_prices=np.array([50.0, 50.0, 50.0]),
            system_sell_price=np.array([60.0, 60.0, 60.0]),
            system_buy_price=np.array([60.0, 60.0, 60.0]),
            timestamps=ts,
            cost_per_trade=0.0,
        )
        assert pnl[1] == pytest.approx(pnl[0])  # day 2 sized before day 1 settled
        assert pnl[2] > pnl[1]  # day 3 compounds on it

    def test_a_settled_outcome_cannot_resize_an_already_committed_book(self):
        # The cross-day version of the same rule: changing day 1's cash-out must
        # not move day 2's quantity, because day 2 was bid before it landed.
        def run(first_cashout):
            ts = pd.to_datetime(["2024-01-01T20:00:00Z", "2024-01-02T20:00:00Z"], utc=True)
            return run_backtest(
                signals=np.array([1, 1]),
                da_prices=np.array([50.0, 50.0]),
                system_sell_price=np.array([first_cashout, 60.0]),
                system_buy_price=np.array([first_cashout, 60.0]),
                timestamps=ts,
                cost_per_trade=0.0,
            )[0]

        assert run(50.0)[1] == pytest.approx(run(100.0)[1])

    def test_book_exposure_budget_scales_the_day_back(self):
        ts = pd.to_datetime([f"2024-01-01T{h:02d}:00:00Z" for h in range(10)], utc=True)
        common = dict(
            signals=np.ones(10, dtype=int),
            da_prices=np.full(10, 50.0),
            system_sell_price=np.full(10, 60.0),
            system_buy_price=np.full(10, 60.0),
            timestamps=ts,
            cost_per_trade=0.0,
            risk_pct=0.5,  # 10 x 50% of equity would be 5x the balance sheet
        )
        capped, _ = run_backtest(max_book_exposure_pct=1.0, **common)
        uncapped, _ = run_backtest(max_book_exposure_pct=100.0, **common)
        assert capped.sum() < uncapped.sum()


class TestExecutionLedger:
    def test_costs_are_weighted_by_traded_mwh_not_trade_count(self):
        # A trade count times a £/MWh fee is not a cost. On the saved winning run
        # that shortcut reported £1,069 of drag against £29,760.67 actually paid.
        sigs = np.array([1])
        da = np.array([50.0])
        _, metrics = run_backtest(
            sigs,
            da,
            np.array([70.0]),
            np.array([70.0]),
            starting_capital=50_000,
            risk_pct=0.02,
            cost_per_trade=1.0,
        )
        position = 50_000 * 0.02 / 50.0
        assert metrics["total_position_mwh"] == pytest.approx(position)
        assert metrics["total_transaction_costs"] == pytest.approx(position * 1.0)
        assert metrics["total_transaction_costs"] != pytest.approx(metrics["n_trades"] * 1.0)

    def test_gross_less_costs_equals_net(self):
        sigs = np.array([1, -1])
        _, metrics = run_backtest(
            sigs,
            np.array([50.0, 80.0]),
            np.array([70.0, 55.0]),
            np.array([70.0, 60.0]),
            cost_per_trade=1.0,
        )
        assert metrics["gross_pnl"] - metrics["total_transaction_costs"] == pytest.approx(
            metrics["total_pnl"]
        )

    def test_n_trades_counts_executions_not_proposals(self):
        # The middle period has no price, so it is proposed but never filled.
        sigs = np.array([1, 1, 1])
        da = np.array([50.0, np.nan, 50.0])
        _, metrics = run_backtest(sigs, da, np.full(3, 60.0), np.full(3, 60.0), cost_per_trade=0.0)
        assert metrics["n_signals_proposed"] == 3
        assert metrics["n_trades"] == 2

    def test_first_loss_is_a_drawdown(self):
        # Running the high-water mark over cumulative P&L alone made an account
        # that only ever lost report a £0 maximum drawdown.
        sigs = np.array([1])
        _, metrics = run_backtest(
            sigs,
            np.array([50.0]),
            np.array([30.0]),
            np.array([30.0]),
            starting_capital=10_000,
            risk_pct=0.05,
            cost_per_trade=0.0,
        )
        assert metrics["max_drawdown"] < 0.0

    def test_calmar_and_return_to_dd_are_reported_separately(self):
        ts = pd.to_datetime([f"2024-01-{d:02d}T12:00:00Z" for d in range(1, 11)], utc=True)
        _, metrics = run_backtest(
            signals=np.ones(10, dtype=int),
            da_prices=np.full(10, 50.0),
            system_sell_price=np.full(10, 55.0),
            system_buy_price=np.full(10, 55.0),
            timestamps=ts,
            cost_per_trade=0.0,
        )
        assert "calmar_ratio" in metrics
        assert "return_to_dd" in metrics
        assert "sharpe_cash" in metrics
