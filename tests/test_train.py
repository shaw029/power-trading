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
        return pd.DataFrame(
            {
                "time": pd.date_range("2018-06-01", periods=n, freq="30min", tz="UTC"),
                "day_ahead_price": [50.0] * n,
                "mid_price": mid_values,
                "system_sell_price": [60.0] * n,
                "system_buy_price": [65.0] * n,
            }
        )

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


class TestLabelAvailabilityPurge:
    """A chronological split is not an available one.

    The book for the first test day is committed at that day's D-1 10:30
    auction, but the training window ran to the last settlement period of the
    preceding delivery day — through the evening *after* that auction. For a
    target built from realised cash-out prices those labels did not exist yet.
    """

    def _frame(self, start="2018-07-01", periods=96):
        t = pd.date_range(start, periods=periods, freq="30min", tz="UTC")
        return pd.DataFrame({"time": t, "y": range(periods)})

    def test_training_stops_at_the_first_test_books_decision(self):
        from src.models.train import purge_unavailable_labels

        df = self._frame()
        first_test = pd.Timestamp("2018-07-03T00:00:00Z")  # London date 3 July
        kept = purge_unavailable_labels(df, first_test)
        # Auction for 3 July is 10:30 London on 2 July = 09:30 UTC.
        assert kept["time"].max() <= pd.Timestamp("2018-07-02T09:30:00Z")

    def test_the_evening_after_the_auction_is_dropped(self):
        from src.models.train import purge_unavailable_labels

        df = self._frame()
        first_test = pd.Timestamp("2018-07-03T00:00:00Z")
        kept = purge_unavailable_labels(df, first_test)
        evening = pd.Timestamp("2018-07-02T22:30:00Z")
        assert evening in set(df["time"])
        assert evening not in set(kept["time"])

    def test_publication_lag_moves_the_cutoff_earlier(self):
        from src.models.train import purge_unavailable_labels

        df = self._frame()
        first_test = pd.Timestamp("2018-07-03T00:00:00Z")
        base = purge_unavailable_labels(df, first_test)
        lagged = purge_unavailable_labels(df, first_test, label_lag=pd.Timedelta(hours=4))
        assert lagged["time"].max() < base["time"].max()

    def test_nothing_is_dropped_when_the_window_already_ends_early(self):
        from src.models.train import purge_unavailable_labels

        df = self._frame(periods=4)  # 1 July only
        kept = purge_unavailable_labels(df, pd.Timestamp("2018-07-03T00:00:00Z"))
        assert len(kept) == len(df)


class TestFeatureImportanceReporting:
    """The imputation pipeline must not hide the estimator's importances.

    ``_fit_model`` wraps every model in ``make_pipeline(SimpleImputer, model)``.
    A ``Pipeline`` does not forward ``feature_importances_``, so the plain
    ``hasattr(model, ...)`` check the reporting used silently stopped firing for
    every tree model — no error, just a diagnostic that quietly went away.
    """

    def test_importances_are_reachable_through_the_imputation_pipeline(self):
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import make_pipeline

        from src.models.train import _final_estimator

        X = np.arange(20, dtype=float).reshape(10, 2)
        y = np.arange(10, dtype=float)
        pipeline = make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            RandomForestRegressor(n_estimators=3, random_state=0),
        ).fit(X, y)

        assert not hasattr(pipeline, "feature_importances_")
        assert hasattr(_final_estimator(pipeline), "feature_importances_")

    def test_an_unwrapped_estimator_is_returned_unchanged(self):
        from sklearn.ensemble import RandomForestRegressor

        from src.models.train import _final_estimator

        bare = RandomForestRegressor(n_estimators=3, random_state=0)
        assert _final_estimator(bare) is bare
