"""Unit tests for src/features/build_features.py."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from src.features.build_features import build_features

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_N = 200  # enough periods to have fully-warmed lag96 values at the tail


def _make_df(n: int = _N, seed: int = 0) -> pd.DataFrame:
    """Minimal merged DataFrame with all columns build_features may consume."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2018-01-01", periods=n, freq="30min", tz="UTC")
    ssp = 35.0 + rng.normal(0, 8, n)
    # In GB dual-price settlement SBP >= SSP by construction; model this with a
    # non-negative spread drawn from a half-normal so the invariant always holds.
    sbp = ssp + np.abs(rng.normal(10.0, 5.0, n))
    return pd.DataFrame(
        {
            "time": ts,
            "day_ahead_price": 40.0 + rng.normal(0, 5, n),
            "system_buy_price": sbp,
            "system_sell_price": ssp,
            "wind_fc_da_d1_10h30": 5000.0 + rng.normal(0, 500, n),
            "demand_fc_da_d1_10h30": 30000.0 + rng.normal(0, 1000, n),
            "wind_fc_da_d1_07h": 5000.0 + rng.normal(0, 500, n),
        }
    )


@pytest.fixture()
def df():
    return _make_df()


@pytest.fixture()
def result(df, tmp_path):
    with patch("src.features.build_features.VERSIONED_FEATURES_DIR", tmp_path):
        return build_features(df, save_path=tmp_path / "features.parquet")


# ---------------------------------------------------------------------------
# Output shape and leakage guard
# ---------------------------------------------------------------------------


class TestOutputShape:
    def test_same_row_count_as_input(self, df, result):
        assert len(result) == len(df)

    def test_no_rows_dropped(self, df, result):
        assert result["time"].iloc[0] == df["time"].iloc[0]
        assert result["time"].iloc[-1] == df["time"].iloc[-1]

    def test_does_not_mutate_input(self, df):
        original_cols = set(df.columns)
        with patch("src.features.build_features.VERSIONED_FEATURES_DIR", "/tmp"):
            build_features(df, save_path="/tmp/f.parquet")
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# Lag columns — existence and correctness
# ---------------------------------------------------------------------------

LAG_COLS = [
    "day_ahead_price_lag48",
    "day_ahead_price_lag96",
    "system_sell_price_lag48",
    "system_sell_price_lag96",
    "system_buy_price_lag48",
    "system_buy_price_lag96",
    "imbalance_spread_lag48",
    "imbalance_spread_lag96",
]


class TestLagColumns:
    def test_all_lag_columns_present(self, result):
        for col in LAG_COLS:
            assert col in result.columns, f"Missing lag column: {col}"

    def test_buy_price_lag48_matches_shift(self, df, result):
        expected = df["system_buy_price"].shift(48).values
        np.testing.assert_array_almost_equal(result["system_buy_price_lag48"].values, expected)

    def test_buy_price_lag96_matches_shift(self, df, result):
        expected = df["system_buy_price"].shift(96).values
        np.testing.assert_array_almost_equal(result["system_buy_price_lag96"].values, expected)

    def test_sell_price_lag48_matches_shift(self, df, result):
        expected = df["system_sell_price"].shift(48).values
        np.testing.assert_array_almost_equal(result["system_sell_price_lag48"].values, expected)

    def test_first_48_lag48_values_are_nan(self, result):
        assert np.all(np.isnan(result["system_buy_price_lag48"].values[:48]))
        assert np.all(np.isnan(result["system_sell_price_lag48"].values[:48]))

    def test_first_96_lag96_values_are_nan(self, result):
        assert np.all(np.isnan(result["system_buy_price_lag96"].values[:96]))

    def test_lag48_values_valid_after_warmup(self, result):
        assert not np.any(np.isnan(result["system_buy_price_lag48"].values[48:]))


class TestImbalanceSpreadLags:
    def test_spread_lag48_equals_sbp_minus_ssp_shifted(self, df, result):
        expected = (df["system_buy_price"] - df["system_sell_price"]).shift(48).values
        np.testing.assert_array_almost_equal(result["imbalance_spread_lag48"].values, expected)

    def test_spread_lag96_equals_sbp_minus_ssp_shifted(self, df, result):
        expected = (df["system_buy_price"] - df["system_sell_price"]).shift(96).values
        np.testing.assert_array_almost_equal(result["imbalance_spread_lag96"].values, expected)

    def test_spread_lags_are_non_negative_for_dual_price_system(self, result):
        # In GB dual-price settlement SBP >= SSP by construction; lags inherit this
        valid48 = result["imbalance_spread_lag48"].dropna()
        valid96 = result["imbalance_spread_lag96"].dropna()
        assert (valid48 >= 0).all(), "imbalance_spread_lag48 has negative values"
        assert (valid96 >= 0).all(), "imbalance_spread_lag96 has negative values"

    def test_spread_lags_absent_when_buy_price_missing(self, tmp_path):
        df = _make_df().drop(columns=["system_buy_price"])
        with patch("src.features.build_features.VERSIONED_FEATURES_DIR", tmp_path):
            result = build_features(df, save_path=tmp_path / "f.parquet")
        assert "imbalance_spread_lag48" not in result.columns
        assert "imbalance_spread_lag96" not in result.columns

    def test_buy_price_lags_absent_when_buy_price_missing(self, tmp_path):
        df = _make_df().drop(columns=["system_buy_price"])
        with patch("src.features.build_features.VERSIONED_FEATURES_DIR", tmp_path):
            result = build_features(df, save_path=tmp_path / "f.parquet")
        assert "system_buy_price_lag48" not in result.columns
        assert "system_buy_price_lag96" not in result.columns


# ---------------------------------------------------------------------------
# Derived features — auction fundamentals and drift
# ---------------------------------------------------------------------------


class TestDerivedFeatures:
    def test_auction_residual_load_present(self, result):
        assert "auction_residual_load" in result.columns

    def test_auction_residual_load_equals_demand_minus_wind(self, df, result):
        expected = df["demand_fc_da_d1_10h30"] - df["wind_fc_da_d1_10h30"]
        np.testing.assert_array_almost_equal(result["auction_residual_load"].values, expected.values)

    def test_wind_auction_drift_present(self, result):
        assert "wind_auction_drift" in result.columns

    def test_wind_auction_drift_equals_auction_minus_morning(self, df, result):
        expected = df["wind_fc_da_d1_10h30"] - df["wind_fc_da_d1_07h"]
        np.testing.assert_array_almost_equal(result["wind_auction_drift"].values, expected.values)
