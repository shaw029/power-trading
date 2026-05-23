"""Unit tests for src/models/train.py — regression tests for data integrity."""

import numpy as np
import pandas as pd
import pytest

from src.models.train import _make_predictions_df


class TestMidPriceLookaheadBias:
    """Verify that mid_price NaNs are forward-filled, not back-filled.

    Back-filling would leak future prices into earlier rows, creating
    lookahead bias in the predictions DataFrame.
    """

    def _build_test_df(self, mid_values):
        n = len(mid_values)
        return pd.DataFrame({
            "time": pd.date_range("2018-06-01", periods=n, freq="30min", tz="UTC"),
            "day_ahead_price": [50.0] * n,
            "mid_price": mid_values,
            "system_sell_price": [60.0] * n,
            "system_buy_price": [65.0] * n,
        })

    def test_leading_nans_remain_nan(self):
        """NaNs before the first valid mid_price must stay NaN (no bfill)."""
        test_df = self._build_test_df([np.nan, np.nan, 100.0, 110.0])
        y_test = pd.Series([5.0] * 4)
        preds = np.array([4.0] * 4)

        result = _make_predictions_df(test_df, y_test, preds)

        assert pd.isna(result["mid_price"].iloc[0])
        assert pd.isna(result["mid_price"].iloc[1])
        assert result["mid_price"].iloc[2] == pytest.approx(100.0)

    def test_interior_nans_filled_forward(self):
        """NaNs after a valid value should carry the last observation forward."""
        test_df = self._build_test_df([80.0, np.nan, np.nan, 90.0])
        y_test = pd.Series([5.0] * 4)
        preds = np.array([4.0] * 4)

        result = _make_predictions_df(test_df, y_test, preds)

        assert result["mid_price"].iloc[0] == pytest.approx(80.0)
        assert result["mid_price"].iloc[1] == pytest.approx(80.0)
        assert result["mid_price"].iloc[2] == pytest.approx(80.0)
        assert result["mid_price"].iloc[3] == pytest.approx(90.0)

    def test_no_future_values_leak_backward(self):
        """The first row must never equal a value that only appears later."""
        test_df = self._build_test_df([np.nan, 200.0, np.nan, 300.0])
        y_test = pd.Series([5.0] * 4)
        preds = np.array([4.0] * 4)

        result = _make_predictions_df(test_df, y_test, preds)

        assert pd.isna(result["mid_price"].iloc[0])
        assert result["mid_price"].iloc[1] == pytest.approx(200.0)
        assert result["mid_price"].iloc[2] == pytest.approx(200.0)
