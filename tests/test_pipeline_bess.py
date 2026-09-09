import json

import numpy as np
import pytest
import pandas as pd

from src.pipeline import run_full_pipeline


def _synthetic_prices(n_days=3):
    start = pd.Timestamp("2024-01-01", tz="UTC")
    periods = n_days * 48
    index = pd.date_range(start, periods=periods, freq="30min")

    rng = np.random.default_rng(42)
    base = 40 + 20 * np.sin(np.arange(periods) * np.pi / 24)

    da = pd.DataFrame({"day_ahead_price": base + rng.normal(0, 2, periods)}, index=index)
    mid = pd.DataFrame({"mid_price": base + 2 + rng.normal(0, 3, periods)}, index=index)
    imb = pd.DataFrame(
        {
            "system_buy_price": 50 + rng.normal(0, 5, periods),
            "system_sell_price": 35 + rng.normal(0, 5, periods),
        },
        index=index,
    )

    for df in (da, mid, imb):
        df.index.name = "time"

    return da, mid, imb


def _synthetic_dst_prices(start_date, end_date):
    tz = "Europe/London"
    start = pd.Timestamp(start_date, tz=tz)
    end = pd.Timestamp(end_date, tz=tz)
    index = pd.date_range(start, end, freq="1h", inclusive="left")

    rng = np.random.default_rng(42)
    n = len(index)
    base = 40 + 20 * np.sin(np.arange(n) * np.pi / 12)

    da = pd.DataFrame({"day_ahead_price": base + rng.normal(0, 2, n)}, index=index)
    mid = pd.DataFrame({"mid_price": base + 2 + rng.normal(0, 3, n)}, index=index)
    imb = pd.DataFrame(
        {
            "system_buy_price": 50 + rng.normal(0, 5, n),
            "system_sell_price": 35 + rng.normal(0, 5, n),
        },
        index=index,
    )

    for df in (da, mid, imb):
        df.index.name = "time"

    return da, mid, imb


def _synthetic_features(price_df):
    """Build synthetic features matching a price DataFrame's index."""
    idx = price_df.index
    utc_idx = idx.tz_convert("UTC") if idx.tz is not None and str(idx.tz) != "UTC" else idx
    rng = np.random.default_rng(99)
    n = len(idx)
    hour = idx.hour + idx.minute / 60
    dow = idx.dayofweek

    return pd.DataFrame(
        {
            "time": utc_idx,
            "day_ahead_price": price_df["day_ahead_price"].values,
            "wind_fc_da_d1_10h30": rng.uniform(5000, 15000, n),
            "demand_fc_da_d1_10h30": rng.uniform(25000, 45000, n),
            "auction_residual_load": rng.uniform(15000, 35000, n),
            "wind_auction_drift": rng.normal(0, 500, n),
            "day_ahead_price_lag96": np.full(n, 40.0),
            "day_ahead_price_lag144": np.full(n, 40.0),
            "system_sell_price_lag96": np.full(n, 35.0),
            "system_sell_price_lag144": np.full(n, 35.0),
            "system_buy_price_lag96": np.full(n, 50.0),
            "system_buy_price_lag144": np.full(n, 50.0),
            "imbalance_gap_lag96": np.full(n, 15.0),
            "imbalance_gap_lag144": np.full(n, 15.0),
            "hour_sin": np.sin(2 * np.pi * hour / 24),
            "hour_cos": np.cos(2 * np.pi * hour / 24),
            "dow_sin": np.sin(2 * np.pi * dow / 7),
            "dow_cos": np.cos(2 * np.pi * dow / 7),
            "system_sell_price": 35 + rng.normal(0, 5, n),
            "system_buy_price": 50 + rng.normal(0, 5, n),
            "mid_price": 42 + rng.normal(0, 3, n),
        }
    )


class _RampModel:
    def predict(self, X):
        return np.arange(len(X), dtype=float)


def _setup_bess_mocks(da, tmp_path, monkeypatch):
    """Pre-create features file and mock DA model training for BESS tests."""
    features_df = _synthetic_features(da)

    features_dir = tmp_path / "artifacts" / "bess_test" / "integration_run" / "features"
    features_dir.mkdir(parents=True)
    features_df.to_parquet(features_dir / "features.parquet", index=False)

    times = pd.to_datetime(features_df["time"], utc=True)
    london_dates = sorted(times.dt.tz_convert("Europe/London").dt.date.unique())
    oos_dates = set(london_dates[1:])
    oos_mask = times.dt.tz_convert("Europe/London").dt.date.isin(oos_dates)
    oos_rows = features_df[oos_mask]

    def mock_train(*args, **kwargs):
        return (
            _RampModel(),
            pd.DataFrame(
                {
                    "time": oos_rows["time"].values,
                    "actual_da_price": oos_rows["day_ahead_price"].values,
                    "predicted_da_price": np.arange(len(oos_rows), dtype=float),
                }
            ),
            pd.DataFrame({"dummy": [0]}),
        )

    monkeypatch.setattr("src.models.train.train_da_price_model", mock_train)
    monkeypatch.setattr("src.pipeline.save_model", lambda *a, **kw: None)


EXPECTED_METRIC_KEYS = {
    "total_da_revenue",
    "total_intraday_pnl",
    "total_execution_costs_paid",
    "total_intraday_throughput_mwh",
    "total_degradation_cost",
    "total_net_pnl",
    "total_cycles",
    "avg_daily_net_pnl",
    "sharpe_ratio",
    "max_drawdown",
}


class TestBESSPipelineIntegration:
    def test_bess_branch_writes_outputs(self, tmp_path, monkeypatch):
        da, mid, imb = _synthetic_prices(4)

        monkeypatch.setattr("src.pipeline.fetch_day_ahead_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_market_index_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_imbalance_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.process_day_ahead_price", lambda _: da)
        monkeypatch.setattr("src.pipeline.process_market_index_price", lambda _: mid)
        monkeypatch.setattr("src.pipeline.process_imbalance_price", lambda _: imb)
        monkeypatch.setattr("src.pipeline.PROJECT_ROOT", tmp_path)
        _setup_bess_mocks(da, tmp_path, monkeypatch)

        config = {
            "strategy": "bess_test",
            "strategy_type": "bess",
            "run_name": "integration_run",
            "bess": {
                "capacity_mwh": 100.0,
                "power_mw": 50.0,
                "charge_efficiency": 0.92,
                "discharge_efficiency": 0.96,
                "degradation_cost_per_mwh": 5.00,
                "initial_soc_pct": 0.50,
            },
        }

        results = run_full_pipeline(config=config)

        trading_dir = tmp_path / "artifacts" / "bess_test" / "integration_run" / "bess" / "trading"
        assert (trading_dir / "pnl.csv").exists()
        assert (trading_dir / "metrics.json").exists()

        pnl = pd.read_csv(trading_dir / "pnl.csv")
        assert list(pnl.columns) == [
            "date",
            "da_revenue",
            "intraday_pnl",
            "execution_costs_paid",
            "degradation_cost",
            "intraday_throughput_mwh",
            "discharge_mwh",
            "net_pnl",
        ]
        assert len(pnl) == 3

        with open(trading_dir / "metrics.json") as f:
            metrics = json.load(f)

        assert set(metrics.keys()) == EXPECTED_METRIC_KEYS

        assert "results_df" in results
        assert len(results["results_df"]) == 3

    def _run_with_prices(self, da, mid, imb, tmp_path, monkeypatch):
        monkeypatch.setattr("src.pipeline.fetch_day_ahead_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_market_index_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_imbalance_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.process_day_ahead_price", lambda _: da)
        monkeypatch.setattr("src.pipeline.process_market_index_price", lambda _: mid)
        monkeypatch.setattr("src.pipeline.process_imbalance_price", lambda _: imb)
        monkeypatch.setattr("src.pipeline.PROJECT_ROOT", tmp_path)
        _setup_bess_mocks(da, tmp_path, monkeypatch)

        config = {
            "strategy": "bess_test",
            "strategy_type": "bess",
            "run_name": "integration_run",
            "bess": {
                "capacity_mwh": 100.0,
                "power_mw": 50.0,
                "charge_efficiency": 0.92,
                "discharge_efficiency": 0.96,
                "degradation_cost_per_mwh": 5.00,
                "initial_soc_pct": 0.50,
            },
        }
        return run_full_pipeline(config=config)

    def test_spring_forward_23h_day(self, tmp_path, monkeypatch):
        da, mid, imb = _synthetic_dst_prices("2024-03-29", "2024-04-02")
        results = self._run_with_prices(da, mid, imb, tmp_path, monkeypatch)

        results_df = results["results_df"]
        assert len(results_df) == 3
        spring_fwd = results_df[results_df["date"].astype(str) == "2024-03-31"]
        assert len(spring_fwd) == 1

    def test_fall_back_25h_day(self, tmp_path, monkeypatch):
        da, mid, imb = _synthetic_dst_prices("2024-10-25", "2024-10-29")
        results = self._run_with_prices(da, mid, imb, tmp_path, monkeypatch)

        results_df = results["results_df"]
        assert len(results_df) == 3
        fall_back = results_df[results_df["date"].astype(str) == "2024-10-27"]
        assert len(fall_back) == 1

    def test_day_absent_from_predictions_is_not_dispatched(self, tmp_path, monkeypatch):
        da, mid, imb = _synthetic_prices(4)

        monkeypatch.setattr("src.pipeline.fetch_day_ahead_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_market_index_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_imbalance_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.process_day_ahead_price", lambda _: da)
        monkeypatch.setattr("src.pipeline.process_market_index_price", lambda _: mid)
        monkeypatch.setattr("src.pipeline.process_imbalance_price", lambda _: imb)
        monkeypatch.setattr("src.pipeline.PROJECT_ROOT", tmp_path)

        features_df = _synthetic_features(da)
        times = pd.to_datetime(features_df["time"], utc=True)
        london_dates = sorted(times.dt.tz_convert("Europe/London").dt.date.unique())

        # Features cover every day; the predictions deliberately skip one.
        features_dir = tmp_path / "artifacts" / "bess_test" / "integration_run" / "features"
        features_dir.mkdir(parents=True)
        features_df.to_parquet(features_dir / "features.parquet", index=False)

        missing_date = london_dates[2]
        oos_dates = set(london_dates[1:]) - {missing_date}
        oos_mask = times.dt.tz_convert("Europe/London").dt.date.isin(oos_dates)
        oos_rows = features_df[oos_mask]

        def mock_train(*args, **kwargs):
            return (
                _RampModel(),
                pd.DataFrame(
                    {
                        "time": oos_rows["time"].values,
                        "actual_da_price": oos_rows["day_ahead_price"].values,
                        "predicted_da_price": np.arange(len(oos_rows), dtype=float),
                    }
                ),
                pd.DataFrame({"dummy": [0]}),
            )

        monkeypatch.setattr("src.models.train.train_da_price_model", mock_train)
        monkeypatch.setattr("src.pipeline.save_model", lambda *a, **kw: None)

        config = {
            "strategy": "bess_test",
            "strategy_type": "bess",
            "run_name": "integration_run",
            "bess": {
                "capacity_mwh": 100.0,
                "power_mw": 50.0,
                "charge_efficiency": 0.92,
                "discharge_efficiency": 0.96,
                "degradation_cost_per_mwh": 5.00,
                "initial_soc_pct": 0.50,
            },
        }

        results = run_full_pipeline(config=config)

        # Dispatch follows the walk-forward predictions, so a day the model never
        # scored out-of-sample simply is not traded. It is no longer enough for a
        # date to appear in the feature file: the forecast for it has to exist.
        assert "results_df" in results
        result_dates = set(results["results_df"]["date"].astype(str))
        assert str(missing_date) not in result_dates
        assert len(result_dates) == 2

    def test_empty_predictions_raise_rather_than_returning_nothing(self, tmp_path, monkeypatch):
        da, mid, imb = _synthetic_prices(4)

        monkeypatch.setattr("src.pipeline.fetch_day_ahead_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_market_index_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_imbalance_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.process_day_ahead_price", lambda _: da)
        monkeypatch.setattr("src.pipeline.process_market_index_price", lambda _: mid)
        monkeypatch.setattr("src.pipeline.process_imbalance_price", lambda _: imb)
        monkeypatch.setattr("src.pipeline.PROJECT_ROOT", tmp_path)

        features_df = _synthetic_features(da).iloc[:1]

        features_dir = tmp_path / "artifacts" / "bess_test" / "integration_run" / "features"
        features_dir.mkdir(parents=True)
        features_df.to_parquet(features_dir / "features.parquet", index=False)

        monkeypatch.setattr(
            "src.models.train.train_da_price_model",
            lambda *a, **kw: (
                _RampModel(),
                pd.DataFrame({"time": [], "actual_da_price": [], "predicted_da_price": []}),
                pd.DataFrame({"dummy": [0]}),
            ),
        )
        monkeypatch.setattr("src.pipeline.save_model", lambda *a, **kw: None)

        config = {
            "strategy": "bess_test",
            "strategy_type": "bess",
            "run_name": "integration_run",
            "bess": {
                "capacity_mwh": 100.0,
                "power_mw": 50.0,
                "charge_efficiency": 0.92,
                "discharge_efficiency": 0.96,
                "degradation_cost_per_mwh": 5.00,
                "initial_soc_pct": 0.50,
            },
        }

        with pytest.raises(RuntimeError, match="no out-of-sample predictions"):
            run_full_pipeline(config=config)

    def test_forecast_aggregation(self, tmp_path, monkeypatch):
        da, mid, imb = _synthetic_prices(4)

        monkeypatch.setattr("src.pipeline.fetch_day_ahead_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_market_index_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.fetch_imbalance_price", lambda *a, **kw: None)
        monkeypatch.setattr("src.pipeline.process_day_ahead_price", lambda _: da)
        monkeypatch.setattr("src.pipeline.process_market_index_price", lambda _: mid)
        monkeypatch.setattr("src.pipeline.process_imbalance_price", lambda _: imb)
        monkeypatch.setattr("src.pipeline.PROJECT_ROOT", tmp_path)
        _setup_bess_mocks(da, tmp_path, monkeypatch)

        captured_forecasts = []

        def capturing_optimize(
            da_price_forecast,
            asset,
            duration_h=1.0,
            target_daily_cycles=None,
            commit_fraction=1.0,
        ):
            captured_forecasts.append(list(da_price_forecast))
            return [0.0] * len(da_price_forecast)

        monkeypatch.setattr(
            "src.bess.da_optimizer.optimize_da_schedule",
            capturing_optimize,
        )

        config = {
            "strategy": "bess_test",
            "strategy_type": "bess",
            "run_name": "integration_run",
            "bess": {
                "capacity_mwh": 100.0,
                "power_mw": 50.0,
                "charge_efficiency": 0.92,
                "discharge_efficiency": 0.96,
                "degradation_cost_per_mwh": 5.00,
                "initial_soc_pct": 0.50,
            },
        }

        run_full_pipeline(config=config)

        assert len(captured_forecasts) == 3

        # Each delivery day is dispatched on *its own* walk-forward prediction,
        # aggregated from half-hourly to the hourly dispatch grid by timestamp.
        # The predictions are a ramp across the whole OOS window, so consecutive
        # days must carry consecutive stretches of it. Re-predicting every day
        # with the last fitted model instead produced the identical forecast on
        # all three days, which is what this used to assert.
        for day_offset, forecast in enumerate(captured_forecasts):
            assert len(forecast) == 24
            base = day_offset * 48
            expected = [base + i * 2 + 0.5 for i in range(24)]
            np.testing.assert_allclose(forecast, expected)

        assert captured_forecasts[0] != captured_forecasts[1]
