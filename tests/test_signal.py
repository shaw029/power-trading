"""Unit tests for src/models/signal.py — all functions are pure."""

import numpy as np
import pandas as pd
import pytest

from src.models.signal import (
    generate_signal,
    build_daily_schedule,
    generate_signal_from_dataframe,
    compute_penalty_buffer,
    compute_volatility_threshold,
    _PENALTY_LAG,
    _PENALTY_WINDOW,
    _VOL_LAG,
    _VOL_WINDOW,
)

# ---------------------------------------------------------------------------
# compute_penalty_buffer
# ---------------------------------------------------------------------------

_MIN_WARMUP = _PENALTY_LAG + 48  # first index with a valid (non-NaN) value


class TestComputePenaltyBuffer:
    def _constant_series(self, value: float, n: int = 500):
        return np.full(n, value), np.zeros(n)  # buy, sell → spread = value

    def test_output_length_matches_input(self):
        buy, sell = self._constant_series(10.0)
        result = compute_penalty_buffer(buy, sell)
        assert len(result) == len(buy)

    def test_first_values_are_nan_before_warmup(self):
        buy, sell = self._constant_series(5.0)
        result = compute_penalty_buffer(buy, sell)
        assert np.all(np.isnan(result[: _MIN_WARMUP - 1]))

    def test_first_valid_value_at_warmup_index(self):
        buy, sell = self._constant_series(5.0)
        result = compute_penalty_buffer(buy, sell)
        assert not np.isnan(result[_MIN_WARMUP - 1])

    def test_constant_spread_converges_to_that_spread(self):
        # After the full window warms up, rolling mean of constant c == c
        c = 8.0
        n = _PENALTY_LAG + _PENALTY_WINDOW + 10
        buy = np.full(n, c)
        sell = np.zeros(n)
        result = compute_penalty_buffer(buy, sell)
        assert result[-1] == pytest.approx(c)

    def test_zero_spread_gives_zero_penalty(self):
        buy = sell = np.zeros(500)
        result = compute_penalty_buffer(buy, sell)
        valid = result[~np.isnan(result)]
        assert np.all(valid == pytest.approx(0.0))

    def test_accepts_pandas_series(self):
        buy = pd.Series(np.full(500, 5.0))
        sell = pd.Series(np.zeros(500))
        result = compute_penalty_buffer(buy, sell)
        assert isinstance(result, np.ndarray)
        assert len(result) == 500

    def test_returns_numpy_array(self):
        buy, sell = self._constant_series(3.0)
        result = compute_penalty_buffer(buy, sell)
        assert isinstance(result, np.ndarray)


# ---------------------------------------------------------------------------
# compute_volatility_threshold
# ---------------------------------------------------------------------------

_VOL_MIN_WARMUP = _VOL_LAG + 48


class TestComputeVolatilityThreshold:
    def _constant_spread(self, value: float, n: int = 500):
        return np.full(n, value), np.zeros(n)

    def test_output_length_matches_input(self):
        buy, sell = self._constant_spread(10.0)
        result = compute_volatility_threshold(buy, sell)
        assert len(result) == len(buy)

    def test_returns_numpy_array(self):
        buy, sell = self._constant_spread(5.0)
        assert isinstance(compute_volatility_threshold(buy, sell), np.ndarray)

    def test_first_values_nan_before_warmup(self):
        buy, sell = self._constant_spread(5.0)
        result = compute_volatility_threshold(buy, sell)
        assert np.all(np.isnan(result[: _VOL_MIN_WARMUP - 1]))

    def test_first_valid_value_at_warmup_index(self):
        buy, sell = self._constant_spread(5.0)
        result = compute_volatility_threshold(buy, sell)
        assert not np.isnan(result[_VOL_MIN_WARMUP - 1])

    def test_constant_spread_gives_zero_std(self):
        # std of a constant series is 0
        n = _VOL_LAG + _VOL_WINDOW + 10
        buy = np.full(n, 10.0)
        sell = np.zeros(n)
        result = compute_volatility_threshold(buy, sell)
        assert result[-1] == pytest.approx(0.0)

    def test_varying_spread_gives_positive_std(self):
        rng = np.random.default_rng(42)
        n = _VOL_LAG + _VOL_WINDOW + 10
        buy = rng.normal(10.0, 3.0, n)
        sell = np.zeros(n)
        result = compute_volatility_threshold(buy, sell)
        assert result[-1] > 0.0

    def test_accepts_pandas_series(self):
        n = 500
        buy = pd.Series(np.full(n, 5.0))
        sell = pd.Series(np.zeros(n))
        result = compute_volatility_threshold(buy, sell)
        assert isinstance(result, np.ndarray)
        assert len(result) == n

    def test_custom_window_and_lag(self):
        n = 300
        buy = np.full(n, 5.0)
        sell = np.zeros(n)
        result = compute_volatility_threshold(buy, sell, window=100, lag=50)
        assert len(result) == n


# ---------------------------------------------------------------------------
# generate_signal
# ---------------------------------------------------------------------------


class TestGenerateSignal:
    def test_buy_signal_when_spread_exceeds_threshold(self):
        spread = np.array([10.0])  # 10 > 0 + 5
        penalty = np.array([0.0])
        result = generate_signal(spread, penalty)
        assert result[0] == 1

    def test_sell_signal_when_spread_below_negative_threshold(self):
        spread = np.array([-10.0])  # -10 < -(0 + 5)
        penalty = np.array([0.0])
        result = generate_signal(spread, penalty)
        assert result[0] == -1

    def test_neutral_when_spread_inside_threshold_band(self):
        spread = np.array([3.0])  # 3 < 0 + 5
        penalty = np.array([0.0])
        result = generate_signal(spread, penalty)
        assert result[0] == 0

    def test_exact_threshold_boundary_is_neutral(self):
        # spread == threshold → NOT strictly greater → neutral
        spread = np.array([5.0])
        penalty = np.array([0.0])
        result = generate_signal(spread, penalty)
        assert result[0] == 0

    def test_just_above_threshold_fires_buy(self):
        spread = np.array([5.001])
        penalty = np.array([0.0])
        result = generate_signal(spread, penalty)
        assert result[0] == 1

    def test_positive_penalty_raises_threshold(self):
        # penalty=3 → adjusted=8; spread=6 is below 8 → neutral
        spread = np.array([6.0])
        penalty = np.array([3.0])
        result = generate_signal(spread, penalty, threshold=5.0)
        assert result[0] == 0

    def test_positive_penalty_raises_threshold_fires_above(self):
        spread = np.array([9.0])
        penalty = np.array([3.0])
        result = generate_signal(spread, penalty, threshold=5.0)
        assert result[0] == 1

    def test_negative_penalty_clipped_to_zero(self):
        # negative penalty clipped → adjusted = 0 + 5 = 5; spread=6 → buy
        spread = np.array([6.0])
        penalty = np.array([-10.0])
        result = generate_signal(spread, penalty)
        assert result[0] == 1

    def test_nan_penalty_treated_as_zero(self):
        spread = np.array([6.0])
        penalty = np.array([np.nan])
        result = generate_signal(spread, penalty)
        assert result[0] == 1  # nan→0, adjusted=5, 6>5 → BUY

    def test_custom_threshold(self):
        spread = np.array([12.0])
        penalty = np.array([0.0])
        # 12 > 10 → BUY
        result = generate_signal(spread, penalty, threshold=10.0)
        assert result[0] == 1
        # 12 > 13 is False → NEUTRAL
        result2 = generate_signal(spread, penalty, threshold=13.0)
        assert result2[0] == 0

    def test_all_neutral_returns_zeros(self):
        spread = np.zeros(10)
        penalty = np.zeros(10)
        result = generate_signal(spread, penalty)
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
        spread = np.array([10.0, -10.0, 3.0, -3.0, 6.0])
        penalty = np.zeros(5)
        result = generate_signal(spread, penalty)
        assert list(result) == [1, -1, 0, 0, 1]

    # --- volatility-adjusted gate ---

    def test_vol_threshold_widens_gate_suppresses_signal(self):
        # Without vol: spread=6 > threshold=5 → BUY
        # With vol=8, multiplier=1.0: gate=max(5, 8)=8; 6 < 8 → NEUTRAL
        spread = np.array([6.0])
        penalty = np.array([0.0])
        assert generate_signal(spread, penalty, threshold=5.0)[0] == 1
        vol = np.array([8.0])
        assert (
            generate_signal(spread, penalty, threshold=5.0, vol_threshold=vol, vol_multiplier=1.0)[
                0
            ]
            == 0
        )

    def test_vol_threshold_floor_is_static_threshold(self):
        # vol=2, multiplier=1.0 → vol_gate=2 < threshold=5 → floor kicks in → gate=5
        # spread=6 > 5 → BUY (same as no-vol case)
        spread = np.array([6.0])
        penalty = np.array([0.0])
        vol = np.array([2.0])
        result = generate_signal(
            spread, penalty, threshold=5.0, vol_threshold=vol, vol_multiplier=1.0
        )
        assert result[0] == 1

    def test_vol_multiplier_scales_gate(self):
        # vol=4, multiplier=2.0 → vol_gate=8 > threshold=5 → gate=8
        # spread=7 < 8 → NEUTRAL; spread=9 > 8 → BUY
        penalty = np.array([0.0, 0.0])
        vol = np.array([4.0, 4.0])
        spread = np.array([7.0, 9.0])
        result = generate_signal(
            spread, penalty, threshold=5.0, vol_threshold=vol, vol_multiplier=2.0
        )
        assert result[0] == 0
        assert result[1] == 1

    def test_vol_nan_treated_as_zero_falls_back_to_floor(self):
        # NaN vol → 0 after nan_to_num → vol_gate=max(5, 0)=5 → same as static threshold
        spread = np.array([6.0])
        penalty = np.array([0.0])
        vol = np.array([np.nan])
        result = generate_signal(
            spread, penalty, threshold=5.0, vol_threshold=vol, vol_multiplier=1.0
        )
        assert result[0] == 1

    def test_vol_threshold_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="length"):
            generate_signal(
                np.array([1.0, 2.0]), np.array([0.0, 0.0]), vol_threshold=np.array([1.0])
            )


# ---------------------------------------------------------------------------
# build_daily_schedule
# ---------------------------------------------------------------------------


class TestBuildDailySchedule:
    def _make_inputs(self, n_per_day: int = 10, n_days: int = 2):
        """Return n_days of 30-min timestamps and matching signal arrays."""
        ts = pd.date_range("2018-01-10", periods=n_per_day * n_days, freq="30min", tz="UTC")
        spread = np.tile(np.linspace(10, 1, n_per_day), n_days)  # descending conviction
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
        ts = pd.date_range("2018-01-10", periods=20, freq="30min", tz="UTC")
        spread = np.full(20, 10.0)
        sigs = np.ones(20, dtype=int)
        _, filtered = build_daily_schedule(spread, sigs, ts, top_n=3)
        # Each 30min × 20 spans ~10h; all on the same calendar day
        assert (filtered == 1).sum() <= 3

    def test_top_n_selects_highest_abs_spread_long(self):
        ts = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        spread = np.array([10.0, 8.0, 6.0, 4.0])
        sigs = np.array([1, 1, 1, 1])
        _, filtered = build_daily_schedule(spread, sigs, ts, top_n=2)
        retained = np.where(filtered == 1)[0]
        assert 0 in retained
        assert 1 in retained
        assert 2 not in retained

    def test_top_n_selects_highest_abs_spread_short(self):
        # SHORT conviction = largest |predicted_spread|; -10 and -8 beat -6 and -4
        ts = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        spread = np.array([-4.0, -6.0, -8.0, -10.0])
        sigs = np.array([-1, -1, -1, -1])
        _, filtered = build_daily_schedule(spread, sigs, ts, top_n=2)
        retained = np.where(filtered == -1)[0]
        assert 3 in retained  # -10.0 → highest conviction
        assert 2 in retained  # -8.0 → second
        assert 1 not in retained
        assert 0 not in retained

    def test_top_n_does_not_cross_directions(self):
        # A strong SHORT should not displace a weak LONG and vice versa
        ts = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        spread = np.array([20.0, -20.0, 5.1, -5.1])
        sigs = np.array([1, -1, 1, -1])
        _, filtered = build_daily_schedule(spread, sigs, ts, top_n=1)
        assert filtered[0] == 1  # top LONG: spread=20
        assert filtered[1] == -1  # top SHORT: spread=-20
        assert filtered[2] == 0  # weaker LONG dropped
        assert filtered[3] == 0  # weaker SHORT dropped

    def test_schedule_df_has_required_columns(self):
        ts = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        spread = np.array([10.0, -10.0, 0.0, 0.0])
        sigs = np.array([1, -1, 0, 0])
        schedule, _ = build_daily_schedule(spread, sigs, ts)
        assert "market_date" in schedule.columns
        assert "time" in schedule.columns
        assert "direction" in schedule.columns
        assert "predicted_spread" in schedule.columns

    def test_schedule_direction_labels(self):
        ts = pd.date_range("2018-01-10", periods=2, freq="30min", tz="UTC")
        spread = np.array([10.0, -10.0])
        sigs = np.array([1, -1])
        schedule, _ = build_daily_schedule(spread, sigs, ts)
        directions = set(schedule["direction"])
        assert directions == {"BUY", "SELL"}

    def test_all_neutral_returns_empty_schedule(self):
        ts = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        spread = np.zeros(4)
        sigs = np.zeros(4, dtype=int)
        schedule, filtered = build_daily_schedule(spread, sigs, ts)
        assert schedule.empty
        assert (filtered == 0).all()

    def test_buy_and_sell_are_filtered_independently(self):
        # 4 BUY + 4 SELL on the same day; top_n=2 → 2 BUY + 2 SELL
        ts = pd.date_range("2018-01-10", periods=8, freq="30min", tz="UTC")
        spread = np.array([10.0, 9.0, 8.0, 7.0, -6.0, -7.0, -8.0, -9.0])
        sigs = np.array([1, 1, 1, 1, -1, -1, -1, -1])
        _, filtered = build_daily_schedule(spread, sigs, ts, top_n=2)
        assert (filtered == 1).sum() == 2
        assert (filtered == -1).sum() == 2


# ---------------------------------------------------------------------------
# generate_signal_from_dataframe
# ---------------------------------------------------------------------------


class TestGenerateSignalFromDataframe:
    def _make_df(self, with_penalty: bool = True):
        df = pd.DataFrame(
            {
                "predicted_spread": [10.0, -10.0, 1.0],
                "penalty_buffer": [0.0, 0.0, 0.0],
            }
        )
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
        result_default = generate_signal_from_dataframe(df, threshold=5.0)
        result_high = generate_signal_from_dataframe(df, threshold=7.0)
        assert result_default["signal"].iloc[0] == 1
        assert result_high["signal"].iloc[0] == 0

    def test_top_n_none_returns_all_gated_signals(self):
        # Without top_n, all signals that pass the gate are kept
        ts = pd.date_range("2018-01-10", periods=6, freq="30min", tz="UTC")
        df = pd.DataFrame(
            {
                "time": ts,
                "predicted_spread": [10.0, 9.0, 8.0, 7.0, 6.0, 1.0],
                "penalty_buffer": np.zeros(6),
            }
        )
        result = generate_signal_from_dataframe(df, threshold=5.0, top_n=None)
        assert (result["signal"] == 1).sum() == 5  # all five > 5.0 are kept

    def test_top_n_with_timestamps_applies_conviction_ranking(self):
        # 4 LONG signals on the same day; top_n=2 → only the 2 highest |spread| survive
        ts = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        df = pd.DataFrame(
            {
                "time": ts,
                "predicted_spread": [10.0, 9.0, 8.0, 7.0],
                "penalty_buffer": np.zeros(4),
            }
        )
        result = generate_signal_from_dataframe(df, threshold=5.0, top_n=2)
        signals = list(result["signal"])
        assert signals[0] == 1  # highest conviction retained
        assert signals[1] == 1  # second highest retained
        assert signals[2] == 0  # dropped
        assert signals[3] == 0  # dropped

    def test_top_n_without_timestamps_skips_ranking(self):
        # No timestamp column → top_n is ignored, all gated signals returned
        df = pd.DataFrame(
            {
                "predicted_spread": [10.0, 9.0, 8.0, 7.0],
                "penalty_buffer": np.zeros(4),
            }
        )
        result = generate_signal_from_dataframe(df, threshold=5.0, top_n=1)
        assert (result["signal"] == 1).sum() == 4  # all pass gate, no ranking applied
