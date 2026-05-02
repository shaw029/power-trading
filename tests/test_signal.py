"""Unit tests for src/models/signal.py — all functions are pure."""

import numpy as np
import pandas as pd
import pytest

from src.models.signal import (
    generate_signal,
    build_daily_schedule,
    generate_signal_from_dataframe,
)


# ---------------------------------------------------------------------------
# generate_signal
# ---------------------------------------------------------------------------

class TestGenerateSignal:
    def test_buy_signal_when_spread_exceeds_threshold(self):
        spread  = np.array([10.0])   # 10 > 0 + 5
        penalty = np.array([0.0])
        result  = generate_signal(spread, penalty)
        assert result[0] == 1

    def test_sell_signal_when_spread_below_negative_threshold(self):
        spread  = np.array([-10.0])  # -10 < -(0 + 5)
        penalty = np.array([0.0])
        result  = generate_signal(spread, penalty)
        assert result[0] == -1

    def test_neutral_when_spread_inside_threshold_band(self):
        spread  = np.array([3.0])    # 3 < 0 + 5
        penalty = np.array([0.0])
        result  = generate_signal(spread, penalty)
        assert result[0] == 0

    def test_exact_threshold_boundary_is_neutral(self):
        # spread == threshold → NOT strictly greater → neutral
        spread  = np.array([5.0])
        penalty = np.array([0.0])
        result  = generate_signal(spread, penalty)
        assert result[0] == 0

    def test_just_above_threshold_fires_buy(self):
        spread  = np.array([5.001])
        penalty = np.array([0.0])
        result  = generate_signal(spread, penalty)
        assert result[0] == 1

    def test_positive_penalty_raises_threshold(self):
        # penalty=3 → adjusted=8; spread=6 is below 8 → neutral
        spread  = np.array([6.0])
        penalty = np.array([3.0])
        result  = generate_signal(spread, penalty, threshold=5.0)
        assert result[0] == 0

    def test_positive_penalty_raises_threshold_fires_above(self):
        spread  = np.array([9.0])
        penalty = np.array([3.0])
        result  = generate_signal(spread, penalty, threshold=5.0)
        assert result[0] == 1

    def test_negative_penalty_clipped_to_zero(self):
        # negative penalty clipped → adjusted = 0 + 5 = 5; spread=6 → buy
        spread  = np.array([6.0])
        penalty = np.array([-10.0])
        result  = generate_signal(spread, penalty)
        assert result[0] == 1

    def test_nan_penalty_treated_as_zero(self):
        spread  = np.array([6.0])
        penalty = np.array([np.nan])
        result  = generate_signal(spread, penalty)
        assert result[0] == 1  # nan→0, adjusted=5, 6>5 → BUY

    def test_custom_threshold(self):
        spread  = np.array([12.0])
        penalty = np.array([0.0])
        # 12 > 10 → BUY
        result  = generate_signal(spread, penalty, threshold=10.0)
        assert result[0] == 1
        # 12 > 13 is False → NEUTRAL
        result2 = generate_signal(spread, penalty, threshold=13.0)
        assert result2[0] == 0

    def test_all_neutral_returns_zeros(self):
        spread  = np.zeros(10)
        penalty = np.zeros(10)
        result  = generate_signal(spread, penalty)
        assert (result == 0).all()

    def test_output_dtype_is_int(self):
        result = generate_signal(np.array([6.0]), np.array([0.0]))
        assert result.dtype == int

    def test_output_length_matches_input(self):
        n = 100
        result = generate_signal(np.random.randn(n), np.zeros(n))
        assert len(result) == n

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="length"):
            generate_signal(np.array([1.0, 2.0]), np.array([0.0]))

    def test_list_inputs_accepted(self):
        result = generate_signal([10.0, -10.0, 1.0], [0.0, 0.0, 0.0])
        assert list(result) == [1, -1, 0]

    def test_mixed_signals(self):
        spread  = np.array([10.0, -10.0, 3.0, -3.0, 6.0])
        penalty = np.zeros(5)
        result  = generate_signal(spread, penalty)
        assert list(result) == [1, -1, 0, 0, 1]


# ---------------------------------------------------------------------------
# build_daily_schedule
# ---------------------------------------------------------------------------

class TestBuildDailySchedule:
    def _make_inputs(self, n_per_day: int = 10, n_days: int = 2):
        """Return n_days of 30-min timestamps and matching signal arrays."""
        ts = pd.date_range("2018-01-10", periods=n_per_day * n_days, freq="30min", tz="UTC")
        spread = np.tile(np.linspace(10, 1, n_per_day), n_days)   # descending conviction
        signals = np.where(spread >= 5, 1, np.where(spread <= -5, -1, 0))
        return spread, signals, ts

    def test_returns_tuple_of_dataframe_and_array(self):
        spread, signals, ts = self._make_inputs()
        schedule, filtered = build_daily_schedule(spread, signals, ts)
        assert isinstance(schedule, pd.DataFrame)
        assert isinstance(filtered, np.ndarray)

    def test_filtered_array_same_length_as_input(self):
        spread, signals, ts = self._make_inputs()
        _, filtered = build_daily_schedule(spread, signals, ts)
        assert len(filtered) == len(signals)

    def test_no_more_than_top_n_buys_per_day(self):
        # 10 BUY signals per day; top_n=3 → at most 3 buys per day
        ts     = pd.date_range("2018-01-10", periods=20, freq="30min", tz="UTC")
        spread = np.full(20, 10.0)
        sigs   = np.ones(20, dtype=int)
        _, filtered = build_daily_schedule(spread, sigs, ts, top_n=3)
        # Each 30min × 20 spans ~10h; all on the same calendar day
        assert (filtered == 1).sum() <= 3

    def test_top_n_selects_highest_abs_spread(self):
        ts     = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        spread = np.array([10.0, 8.0, 6.0, 4.0])
        sigs   = np.array([1, 1, 1, 1])
        _, filtered = build_daily_schedule(spread, sigs, ts, top_n=2)
        # Periods 0 and 1 have highest spread — they should be retained
        retained_indices = np.where(filtered == 1)[0]
        assert 0 in retained_indices
        assert 1 in retained_indices
        assert 2 not in retained_indices

    def test_schedule_df_has_required_columns(self):
        ts     = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        spread = np.array([10.0, -10.0, 0.0, 0.0])
        sigs   = np.array([1, -1, 0, 0])
        schedule, _ = build_daily_schedule(spread, sigs, ts)
        assert "market_date" in schedule.columns
        assert "time" in schedule.columns
        assert "direction" in schedule.columns
        assert "predicted_spread" in schedule.columns

    def test_schedule_direction_labels(self):
        ts     = pd.date_range("2018-01-10", periods=2, freq="30min", tz="UTC")
        spread = np.array([10.0, -10.0])
        sigs   = np.array([1, -1])
        schedule, _ = build_daily_schedule(spread, sigs, ts)
        directions = set(schedule["direction"])
        assert directions == {"BUY", "SELL"}

    def test_all_neutral_returns_empty_schedule(self):
        ts     = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        spread = np.zeros(4)
        sigs   = np.zeros(4, dtype=int)
        schedule, filtered = build_daily_schedule(spread, sigs, ts)
        assert schedule.empty
        assert (filtered == 0).all()

    def test_buy_and_sell_are_filtered_independently(self):
        # 4 BUY + 4 SELL on the same day; top_n=2 → 2 BUY + 2 SELL
        ts     = pd.date_range("2018-01-10", periods=8, freq="30min", tz="UTC")
        spread = np.array([10.0, 9.0, 8.0, 7.0, -6.0, -7.0, -8.0, -9.0])
        sigs   = np.array([1, 1, 1, 1, -1, -1, -1, -1])
        _, filtered = build_daily_schedule(spread, sigs, ts, top_n=2)
        assert (filtered == 1).sum() == 2
        assert (filtered == -1).sum() == 2


# ---------------------------------------------------------------------------
# generate_signal_from_dataframe
# ---------------------------------------------------------------------------

class TestGenerateSignalFromDataframe:
    def _make_df(self, with_penalty: bool = True):
        df = pd.DataFrame({
            "predicted_spread": [10.0, -10.0, 1.0],
            "penalty_buffer":   [0.0,   0.0,  0.0],
        })
        if not with_penalty:
            df = df.drop(columns=["penalty_buffer"])
        return df

    def test_signal_column_added(self):
        result = generate_signal_from_dataframe(self._make_df())
        assert "signal" in result.columns

    def test_correct_signal_values(self):
        result = generate_signal_from_dataframe(self._make_df())
        assert list(result["signal"]) == [1, -1, 0]

    def test_no_penalty_column_defaults_to_zero_penalty(self):
        df = self._make_df(with_penalty=False)
        result = generate_signal_from_dataframe(df)
        assert list(result["signal"]) == [1, -1, 0]

    def test_does_not_mutate_input(self):
        df = self._make_df()
        original_cols = list(df.columns)
        generate_signal_from_dataframe(df)
        assert list(df.columns) == original_cols

    def test_missing_pred_col_raises(self):
        df = pd.DataFrame({"other": [1.0, 2.0]})
        with pytest.raises(KeyError):
            generate_signal_from_dataframe(df)

    def test_custom_threshold_applied(self):
        df = pd.DataFrame({"predicted_spread": [6.0], "penalty_buffer": [0.0]})
        result_default  = generate_signal_from_dataframe(df, threshold=5.0)
        result_high     = generate_signal_from_dataframe(df, threshold=7.0)
        assert result_default["signal"].iloc[0]  ==  1
        assert result_high["signal"].iloc[0]     ==  0
