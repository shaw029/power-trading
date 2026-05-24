import json

import numpy as np
import pandas as pd

from pipeline import run_full_pipeline


def _synthetic_prices(n_days=3):
    start = pd.Timestamp("2024-01-01", tz="UTC")
    periods = n_days * 48
    index = pd.date_range(start, periods=periods, freq="30min")

    rng = np.random.default_rng(42)
    base = 40 + 20 * np.sin(np.arange(periods) * np.pi / 24)

    da = pd.DataFrame({"day_ahead_price": base + rng.normal(0, 2, periods)}, index=index)
    mid = pd.DataFrame({"mid_price": base + 2 + rng.normal(0, 3, periods)}, index=index)
    imb = pd.DataFrame({
        "system_buy_price": 50 + rng.normal(0, 5, periods),
        "system_sell_price": 35 + rng.normal(0, 5, periods),
    }, index=index)

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
    imb = pd.DataFrame({
        "system_buy_price": 50 + rng.normal(0, 5, n),
        "system_sell_price": 35 + rng.normal(0, 5, n),
    }, index=index)

    for df in (da, mid, imb):
        df.index.name = "time"

    return da, mid, imb


EXPECTED_METRIC_KEYS = {
    "total_da_revenue",
    "total_intraday_pnl",
    "total_imbalance_pnl",
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

        monkeypatch.setattr("pipeline.fetch_day_ahead_price", lambda *a, **kw: None)
        monkeypatch.setattr("pipeline.fetch_market_index_price", lambda *a, **kw: None)
        monkeypatch.setattr("pipeline.fetch_imbalance_price", lambda *a, **kw: None)
        monkeypatch.setattr("pipeline.process_day_ahead_price", lambda _: da)
        monkeypatch.setattr("pipeline.process_market_index_price", lambda _: mid)
        monkeypatch.setattr("pipeline.process_imbalance_price", lambda _: imb)
        monkeypatch.setattr("pipeline.PROJECT_ROOT", tmp_path)

        config = {
            "strategy": "bess_test",
            "strategy_type": "bess",
            "run_name": "integration_run",
            "bess": {
                "capacity_mwh": 100.0,
                "power_mw": 50.0,
                "round_trip_efficiency": 0.88,
                "degradation_cost_per_mwh": 8.50,
                "initial_soc_pct": 0.50,
                "price_history_lookback_days": 14,
            },
        }

        results = run_full_pipeline(config=config)

        trading_dir = tmp_path / "artifacts" / "bess_test" / "integration_run" / "trading"
        assert (trading_dir / "pnl.csv").exists()
        assert (trading_dir / "metrics.json").exists()

        pnl = pd.read_csv(trading_dir / "pnl.csv")
        assert list(pnl.columns) == [
            "date", "da_revenue", "intraday_pnl",
            "imbalance_pnl", "degradation_cost", "net_pnl",
        ]
        assert len(pnl) == 3

        with open(trading_dir / "metrics.json") as f:
            metrics = json.load(f)

        assert set(metrics.keys()) == EXPECTED_METRIC_KEYS

        assert "results_df" in results
        assert len(results["results_df"]) == 3

    def _run_with_prices(self, da, mid, imb, tmp_path, monkeypatch):
        monkeypatch.setattr("pipeline.fetch_day_ahead_price", lambda *a, **kw: None)
        monkeypatch.setattr("pipeline.fetch_market_index_price", lambda *a, **kw: None)
        monkeypatch.setattr("pipeline.fetch_imbalance_price", lambda *a, **kw: None)
        monkeypatch.setattr("pipeline.process_day_ahead_price", lambda _: da)
        monkeypatch.setattr("pipeline.process_market_index_price", lambda _: mid)
        monkeypatch.setattr("pipeline.process_imbalance_price", lambda _: imb)
        monkeypatch.setattr("pipeline.PROJECT_ROOT", tmp_path)

        config = {
            "strategy": "bess_test",
            "strategy_type": "bess",
            "run_name": "integration_run",
            "bess": {
                "capacity_mwh": 100.0,
                "power_mw": 50.0,
                "round_trip_efficiency": 0.88,
                "degradation_cost_per_mwh": 8.50,
                "initial_soc_pct": 0.50,
                "price_history_lookback_days": 14,
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
