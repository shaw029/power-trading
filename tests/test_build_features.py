"""Unit tests for src/features/build_features.py."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from src.features.build_features import (
    build_features,
    assert_auction_available,
    auction_decision_time,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_N = 200  # enough periods to have fully-warmed lag96 values at the tail


def _make_df(n: int = _N, seed: int = 0) -> pd.DataFrame:
    """Minimal merged DataFrame with all columns build_features may consume."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2018-01-01", periods=n, freq="30min", tz="UTC")
    ssp = 35.0 + rng.normal(0, 8, n)
    # GB has settled on a single cash-out price since BSC P305 (5 November 2015),
    # so SBP == SSP in every real settlement period. The fixture keeps them
    # distinct only so a test can tell which column it is looking at; model with a
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
    "day_ahead_price_lag96",
    "day_ahead_price_lag144",
    "system_sell_price_lag96",
    "system_sell_price_lag144",
    "system_buy_price_lag96",
    "system_buy_price_lag144",
    "imbalance_gap_lag96",
    "imbalance_gap_lag144",
]


class TestLagColumns:
    def test_all_lag_columns_present(self, result):
        for col in LAG_COLS:
            assert col in result.columns, f"Missing lag column: {col}"

    def test_buy_price_lag96_matches_shift(self, df, result):
        expected = df["system_buy_price"].shift(96).values
        np.testing.assert_array_almost_equal(result["system_buy_price_lag96"].values, expected)

    def test_buy_price_lag144_matches_shift(self, df, result):
        expected = df["system_buy_price"].shift(144).values
        np.testing.assert_array_almost_equal(result["system_buy_price_lag144"].values, expected)

    def test_sell_price_lag96_matches_shift(self, df, result):
        expected = df["system_sell_price"].shift(96).values
        np.testing.assert_array_almost_equal(result["system_sell_price_lag96"].values, expected)

    def test_first_96_lag96_values_are_nan(self, result):
        assert np.all(np.isnan(result["system_buy_price_lag96"].values[:96]))
        assert np.all(np.isnan(result["system_sell_price_lag96"].values[:96]))

    def test_first_144_lag144_values_are_nan(self, result):
        assert np.all(np.isnan(result["system_buy_price_lag144"].values[:144]))

    def test_lag96_values_valid_after_warmup(self, result):
        assert not np.any(np.isnan(result["system_buy_price_lag96"].values[96:]))

    def test_no_24h_lag_columns_are_built(self, result):
        # A 24-hour lag reads a settlement period that closes after the D-1 10:30
        # auction for every delivery period past 10:30 — 9,542 of 17,616 rows of
        # the 2018 sample. The columns must not exist to be picked up by name.
        leaky = [c for c in result.columns if c.endswith("_lag48")]
        assert leaky == [], f"24-hour lag columns are post-auction: {leaky}"


class TestImbalanceGapLags:
    """The lagged risk feature is cash-out minus DA, not SBP minus SSP.

    GB has settled on a single cash-out price since BSC P305 (5 November 2015),
    so SBP - SSP is zero in every settlement period and the old "spread" feature
    carried no information at all.
    """

    def test_gap_lag96_equals_cashout_minus_da_shifted(self, df, result):
        expected = (df["system_buy_price"] - df["day_ahead_price"]).shift(96).values
        np.testing.assert_array_almost_equal(result["imbalance_gap_lag96"].values, expected)

    def test_gap_lag144_equals_cashout_minus_da_shifted(self, df, result):
        expected = (df["system_buy_price"] - df["day_ahead_price"]).shift(144).values
        np.testing.assert_array_almost_equal(result["imbalance_gap_lag144"].values, expected)

    def test_gap_is_not_identically_zero_under_single_pricing(self, result):
        # Under single pricing the old SBP-SSP feature was all zeros; this one
        # must actually vary, or the gate it feeds is inert again.
        valid = result["imbalance_gap_lag96"].dropna()
        assert valid.abs().sum() > 0, "imbalance gap is identically zero"

    def test_gap_lags_absent_when_buy_price_missing(self, tmp_path):
        df = _make_df().drop(columns=["system_buy_price"])
        with patch("src.features.build_features.VERSIONED_FEATURES_DIR", tmp_path):
            result = build_features(df, save_path=tmp_path / "f.parquet")
        assert "imbalance_gap_lag96" not in result.columns
        assert "imbalance_gap_lag144" not in result.columns

    def test_buy_price_lags_absent_when_buy_price_missing(self, tmp_path):
        df = _make_df().drop(columns=["system_buy_price"])
        with patch("src.features.build_features.VERSIONED_FEATURES_DIR", tmp_path):
            result = build_features(df, save_path=tmp_path / "f.parquet")
        assert "system_buy_price_lag96" not in result.columns
        assert "system_buy_price_lag144" not in result.columns


# ---------------------------------------------------------------------------
# Derived features — auction fundamentals and drift
# ---------------------------------------------------------------------------


class TestDerivedFeatures:
    def test_auction_residual_load_present(self, result):
        assert "auction_residual_load" in result.columns

    def test_auction_residual_load_equals_demand_minus_wind(self, df, result):
        expected = df["demand_fc_da_d1_10h30"] - df["wind_fc_da_d1_10h30"]
        np.testing.assert_array_almost_equal(
            result["auction_residual_load"].values, expected.values
        )

    def test_wind_auction_drift_present(self, result):
        assert "wind_auction_drift" in result.columns

    def test_wind_auction_drift_equals_auction_minus_morning(self, df, result):
        expected = df["wind_fc_da_d1_10h30"] - df["wind_fc_da_d1_07h"]
        np.testing.assert_array_almost_equal(result["wind_auction_drift"].values, expected.values)


# ---------------------------------------------------------------------------
# Auction-availability guard
# ---------------------------------------------------------------------------


class TestAuctionAvailability:
    """The timing claim is enforced on the built frame, not just documented."""

    def test_decision_time_is_1030_london_the_day_before(self):
        delivery = pd.Series(pd.to_datetime(["2018-07-15T20:00:00Z"], utc=True))
        decision = auction_decision_time(delivery)[0]
        london = decision.tz_convert("Europe/London")
        assert (london.year, london.month, london.day) == (2018, 7, 14)
        assert (london.hour, london.minute) == (10, 30)

    def test_decision_time_holds_at_1030_through_bst(self):
        # A fixed UTC offset would drift the cutoff by an hour across the clock
        # change; the auction sits at 10:30 London on both sides of it.
        delivery = pd.Series(
            pd.to_datetime(["2018-01-15T12:00:00Z", "2018-07-15T12:00:00Z"], utc=True)
        )
        london = auction_decision_time(delivery).dt.tz_convert("Europe/London")
        assert list(london.dt.hour) == [10, 10]
        assert list(london.dt.minute) == [30, 30]

    def test_a_24_hour_lag_is_rejected(self):
        df = _make_df()
        df["leaky"] = df["system_buy_price"].shift(48)
        with pytest.raises(ValueError, match="post-auction"):
            assert_auction_available(df, {"leaky": 48})

    def test_a_48_hour_lag_is_accepted(self):
        df = _make_df()
        df["safe"] = df["system_buy_price"].shift(96)
        assert_auction_available(df, {"safe": 96})  # does not raise

    def test_built_features_pass_their_own_guard(self, result):
        assert_auction_available(
            result,
            {
                "day_ahead_price_lag96": 96,
                "day_ahead_price_lag144": 144,
                "system_buy_price_lag96": 96,
                "imbalance_gap_lag96": 96,
            },
        )

    def test_absent_columns_are_skipped_not_failed(self):
        df = _make_df()
        assert_auction_available(df, {"never_built": 48})  # does not raise
