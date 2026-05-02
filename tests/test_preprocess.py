"""Unit tests for src/data/preprocess.py.

All functions under test are pure (same input → same output, no network/IO),
except merge_all which writes a parquet file — patched via monkeypatch.
"""

import datetime
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

UTC = datetime.timezone.utc

from src.data.preprocess import (
    _utc_index,
    process_imbalance_price,
    process_generation_mix,
    process_market_index_price,
    process_demand_actual,
    process_day_ahead_price,
    process_wind_forecast,
    process_demand_forecast,
    _build_rolling_snapshots,
    _build_static_snapshots,
    merge_all,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def _range(start: str, periods: int, freq: str = "30min") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq=freq, tz="UTC")


# ---------------------------------------------------------------------------
# _utc_index
# ---------------------------------------------------------------------------

class TestUtcIndex:
    def test_string_input_becomes_utc_datetimeindex(self):
        s = pd.Series(["2018-01-01 00:00:00", "2018-01-01 00:30:00"])
        idx = _utc_index(s)
        assert isinstance(idx, pd.DatetimeIndex)
        assert str(idx.tz) == "UTC"
        assert idx.name == "time"

    def test_already_tz_aware_input(self):
        s = pd.Series(pd.date_range("2018-01-01", periods=3, freq="30min", tz="UTC"))
        idx = _utc_index(s)
        assert idx.tz == UTC
        assert len(idx) == 3

    def test_naive_strings_are_localised_to_utc(self):
        s = pd.Series(["2018-06-01 12:00:00"])  # no tz
        idx = _utc_index(s)
        assert idx[0] == _ts("2018-06-01 12:00:00")


# ---------------------------------------------------------------------------
# process_imbalance_price
# ---------------------------------------------------------------------------

class TestProcessImbalancePrice:
    def _make(self, n: int = 3):
        idx = _range("2018-01-01", n)
        return pd.DataFrame({
            "startTime":          idx.strftime("%Y-%m-%d %H:%M:%S+00:00"),
            "systemBuyPrice":     [100.0, 110.0, 105.0],
            "systemSellPrice":    [90.0,  95.0,  88.0],
            "netImbalanceVolume": [10.0, -5.0,   3.0],
        })

    def test_output_columns(self):
        result = process_imbalance_price(self._make())
        assert set(result.columns) == {"system_buy_price", "system_sell_price", "niv"}

    def test_index_is_utc_datetimeindex(self):
        result = process_imbalance_price(self._make())
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.tz == UTC
        assert result.index.name == "time"

    def test_values_are_numeric(self):
        result = process_imbalance_price(self._make())
        assert result["system_buy_price"].dtype == float
        assert result["system_sell_price"].dtype == float

    def test_non_numeric_coerced_to_nan(self):
        df = self._make(3)
        df["systemBuyPrice"] = df["systemBuyPrice"].astype(object)
        df.loc[0, "systemBuyPrice"] = "n/a"
        result = process_imbalance_price(df)
        assert np.isnan(result["system_buy_price"].iloc[0])

    def test_duplicates_dropped_keep_first(self):
        df = self._make(3)
        # Add a duplicate of the first row
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        result = process_imbalance_price(df)
        assert not result.index.duplicated().any()
        assert len(result) == 3

    def test_sorted_ascending(self):
        df = self._make(3)
        df = df.iloc[::-1].reset_index(drop=True)  # reverse order
        result = process_imbalance_price(df)
        assert result.index.is_monotonic_increasing

    def test_does_not_mutate_input(self):
        df = self._make()
        original_cols = list(df.columns)
        process_imbalance_price(df)
        assert list(df.columns) == original_cols


# ---------------------------------------------------------------------------
# process_generation_mix
# ---------------------------------------------------------------------------

class TestProcessGenerationMix:
    def _make(self):
        times = _range("2018-01-01", 4)
        return pd.DataFrame({
            "startTime":  list(times.strftime("%Y-%m-%d %H:%M:%S+00:00")) * 1,
            "fuelType":   ["CCGT", "WIND", "CCGT", "WIND"],
            "generation": [200.0, 50.0, 210.0, 55.0],
            "startTime":  [
                "2018-01-01 00:00:00+00:00",
                "2018-01-01 00:00:00+00:00",
                "2018-01-01 00:30:00+00:00",
                "2018-01-01 00:30:00+00:00",
            ],
        })

    def test_columns_prefixed_with_gen(self):
        result = process_generation_mix(self._make())
        assert all(c.startswith("gen_") for c in result.columns)

    def test_fuel_types_become_columns(self):
        result = process_generation_mix(self._make())
        assert "gen_CCGT" in result.columns
        assert "gen_WIND" in result.columns

    def test_index_is_utc_datetimeindex(self):
        result = process_generation_mix(self._make())
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.name == "time"

    def test_values_aggregated_correctly(self):
        # Two CCGT rows at same timestamp should average
        df = pd.DataFrame({
            "startTime":  ["2018-01-01 00:00:00+00:00"] * 2,
            "fuelType":   ["CCGT", "CCGT"],
            "generation": [200.0, 300.0],
        })
        result = process_generation_mix(df)
        assert result["gen_CCGT"].iloc[0] == pytest.approx(250.0)

    def test_non_numeric_generation_coerced(self):
        df = self._make()
        df["generation"] = df["generation"].astype(object)
        df.loc[0, "generation"] = "bad"
        result = process_generation_mix(df)
        assert result.notna().any().any()  # other rows survive


# ---------------------------------------------------------------------------
# process_market_index_price
# ---------------------------------------------------------------------------

class TestProcessMarketIndexPrice:
    def _make(self):
        return pd.DataFrame({
            "startTime":    ["2018-01-01 00:00:00+00:00", "2018-01-01 00:00:00+00:00"],
            "dataProvider": ["APXMIDP", "OTHER"],
            "price":        [50.0, 99.0],
        })

    def test_filters_to_apxmidp_only(self):
        result = process_market_index_price(self._make())
        assert len(result) == 1
        assert result["mid_price"].iloc[0] == 50.0

    def test_output_column_is_mid_price(self):
        result = process_market_index_price(self._make())
        assert list(result.columns) == ["mid_price"]

    def test_index_is_utc(self):
        result = process_market_index_price(self._make())
        assert result.index.tz == UTC

    def test_non_numeric_price_coerced(self):
        df = pd.DataFrame({
            "startTime":    ["2018-01-01 00:00:00+00:00"],
            "dataProvider": ["APXMIDP"],
            "price":        ["N/A"],
        })
        result = process_market_index_price(df)
        assert np.isnan(result["mid_price"].iloc[0])

    def test_no_apxmidp_rows_returns_empty(self):
        df = pd.DataFrame({
            "startTime":    ["2018-01-01 00:00:00+00:00"],
            "dataProvider": ["OTHER"],
            "price":        [10.0],
        })
        result = process_market_index_price(df)
        assert result.empty


# ---------------------------------------------------------------------------
# process_demand_actual
# ---------------------------------------------------------------------------

class TestProcessDemandActual:
    def _make(self):
        return pd.DataFrame({
            "startTime": ["2018-01-01 00:00:00+00:00", "2018-01-01 00:30:00+00:00"],
            "demand":    [25000.0, 25500.0],
        })

    def test_output_column(self):
        result = process_demand_actual(self._make())
        assert list(result.columns) == ["demand_actual"]

    def test_values_preserved(self):
        result = process_demand_actual(self._make())
        assert result["demand_actual"].iloc[0] == pytest.approx(25000.0)

    def test_non_numeric_coerced(self):
        df = self._make()
        df["demand"] = df["demand"].astype(object)
        df.loc[0, "demand"] = "missing"
        result = process_demand_actual(df)
        assert np.isnan(result["demand_actual"].iloc[0])

    def test_dedup(self):
        df = self._make()
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        result = process_demand_actual(df)
        assert not result.index.duplicated().any()


# ---------------------------------------------------------------------------
# process_day_ahead_price
# ---------------------------------------------------------------------------

class TestProcessDayAheadPrice:
    def _make_hourly(self, n_hours: int = 4):
        times = pd.date_range("2018-01-01", periods=n_hours, freq="h", tz="UTC")
        return pd.DataFrame({"time": times, "value": [50.0] * n_hours})

    def test_hourly_expanded_to_30min(self):
        # 2 hourly points at 00:00 and 01:00 → resample produces 00:00, 00:30, 01:00 = 3 slots
        result = process_day_ahead_price(self._make_hourly(2))
        assert len(result) == 3

    def test_output_column(self):
        result = process_day_ahead_price(self._make_hourly(2))
        assert "day_ahead_price" in result.columns

    def test_forward_fill_fills_30min_slot(self):
        # Two hourly points: 00:00 and 01:00 — the 00:30 slot is filled from 00:00
        df = pd.DataFrame({
            "time":  pd.date_range("2018-01-01", periods=2, freq="h", tz="UTC"),
            "value": [75.0, 80.0],
        })
        result = process_day_ahead_price(df)
        assert result["day_ahead_price"].iloc[0] == pytest.approx(75.0)
        assert result["day_ahead_price"].iloc[1] == pytest.approx(75.0)  # ffill from 00:00

    def test_non_numeric_coerced(self):
        df = pd.DataFrame({
            "time":  [pd.Timestamp("2018-01-01", tz="UTC")],
            "value": ["bad"],
        })
        result = process_day_ahead_price(df)
        assert np.isnan(result["day_ahead_price"].iloc[0])

    def test_index_is_utc(self):
        result = process_day_ahead_price(self._make_hourly())
        assert result.index.tz == UTC
        assert result.index.name == "time"


# ---------------------------------------------------------------------------
# _build_rolling_snapshots
# ---------------------------------------------------------------------------

class TestBuildRollingSnapshots:
    def _delivery(self, h: int) -> pd.Timestamp:
        return pd.Timestamp("2018-01-02 12:00", tz="UTC") + pd.Timedelta(hours=h)

    def _pub(self, h: int) -> pd.Timestamp:
        return pd.Timestamp("2018-01-01 00:00", tz="UTC") + pd.Timedelta(hours=h)

    def _make_df(self, lead_hours: list, value: float = 100.0):
        delivery = pd.Timestamp("2018-01-02 12:00", tz="UTC")
        rows = []
        for lh in lead_hours:
            rows.append({
                "_time": delivery,
                "_pub":  delivery - pd.Timedelta(hours=lh),
                "_gen":  value,
            })
        return pd.DataFrame(rows)

    def test_24h_lead_captured(self):
        df = self._make_df([25])  # published 25h before delivery → eligible for 24h snapshot
        result = _build_rolling_snapshots(df, "_time", "_pub", "_gen", "wind")
        assert "wind_fc_rel_24h" in result.columns
        assert result["wind_fc_rel_24h"].notna().any()

    def test_too_recent_publish_excluded(self):
        # Published only 30min before delivery — not eligible for any snapshot
        df = self._make_df([0.5])
        result = _build_rolling_snapshots(df, "_time", "_pub", "_gen", "wind")
        assert result.empty

    def test_latest_eligible_forecast_selected(self):
        # Two publishes at 25h and 30h before delivery — 25h is newer, should win
        df = self._make_df([25, 30], value=100.0)
        df.loc[df["_pub"] == df["_pub"].max(), "_gen"] = 200.0  # 25h publish has value 200
        result = _build_rolling_snapshots(df, "_time", "_pub", "_gen", "wind")
        assert result["wind_fc_rel_24h"].iloc[0] == pytest.approx(200.0)

    def test_empty_input_returns_empty(self):
        df = pd.DataFrame(columns=["_time", "_pub", "_gen"])
        result = _build_rolling_snapshots(df, "_time", "_pub", "_gen", "wind")
        assert result.empty

    def test_prefix_applied_to_columns(self):
        df = self._make_df([25])
        result = _build_rolling_snapshots(df, "_time", "_pub", "_gen", "demand")
        assert all(c.startswith("demand_") for c in result.columns)


# ---------------------------------------------------------------------------
# _build_static_snapshots
# ---------------------------------------------------------------------------

class TestBuildStaticSnapshots:
    def _make_df(self, delivery: str, publish: str, value: float = 100.0):
        return pd.DataFrame([{
            "_time": pd.Timestamp(delivery, tz="UTC"),
            "_pub":  pd.Timestamp(publish,  tz="UTC"),
            "_gen":  value,
        }])

    def test_d1_1030_winter_cutoff(self):
        # Delivery on 2018-01-10 (GMT = UTC); d-1 10:30 London = 10:30 UTC
        # Forecast published at 10:00 UTC on 2018-01-09 — should be included
        df = self._make_df("2018-01-10 12:00", "2018-01-09 10:00")
        result = _build_static_snapshots(df, "_time", "_pub", "_gen", "wind")
        assert "wind_fc_da_d1_10h30" in result.columns
        assert result["wind_fc_da_d1_10h30"].notna().any()

    def test_d1_1030_winter_too_late_excluded(self):
        # Published at 11:00 UTC on d-1 in winter → after 10:30 cutoff
        df = self._make_df("2018-01-10 12:00", "2018-01-09 11:00")
        result = _build_static_snapshots(df, "_time", "_pub", "_gen", "wind")
        if "wind_fc_da_d1_10h30" in result.columns:
            assert result["wind_fc_da_d1_10h30"].isna().all()
        else:
            assert True  # column absent = also correct

    def test_d1_1030_summer_cutoff_is_0930_utc(self):
        # Delivery on 2018-07-10 (BST = UTC+1); d-1 10:30 London = 09:30 UTC
        # Forecast published at 09:00 UTC on 2018-07-09 — should be included
        df = self._make_df("2018-07-10 12:00", "2018-07-09 09:00")
        result = _build_static_snapshots(df, "_time", "_pub", "_gen", "wind")
        assert "wind_fc_da_d1_10h30" in result.columns
        assert result["wind_fc_da_d1_10h30"].notna().any()

    def test_d1_1030_summer_too_late_excluded(self):
        # Published at 10:00 UTC on 2018-07-09 (= 11:00 BST) → after 09:30 UTC cutoff
        df = self._make_df("2018-07-10 12:00", "2018-07-09 10:00")
        result = _build_static_snapshots(df, "_time", "_pub", "_gen", "wind")
        if "wind_fc_da_d1_10h30" in result.columns:
            assert result["wind_fc_da_d1_10h30"].isna().all()
        else:
            assert True

    def test_d2_noon_snapshot_present(self):
        # Delivery 2018-01-10; d-2 noon London (winter) = 2018-01-08 12:00 UTC
        # Published 2018-01-08 11:00 UTC — should be included in d2_noon
        df = self._make_df("2018-01-10 00:00", "2018-01-08 11:00")
        result = _build_static_snapshots(df, "_time", "_pub", "_gen", "wind")
        assert "wind_fc_da_d2_noon" in result.columns

    def test_empty_input_returns_empty(self):
        df = pd.DataFrame({
            "_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "_pub":  pd.Series(dtype="datetime64[ns, UTC]"),
            "_gen":  pd.Series(dtype=float),
        })
        result = _build_static_snapshots(df, "_time", "_pub", "_gen", "wind")
        assert result.empty


# ---------------------------------------------------------------------------
# process_wind_forecast (end-to-end)
# ---------------------------------------------------------------------------

class TestProcessWindForecast:
    def _make(self):
        delivery = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        publish  = [d - pd.Timedelta(hours=25) for d in delivery]
        return pd.DataFrame({
            "startTime":   [str(d) for d in delivery],
            "publishTime": [str(p) for p in publish],
            "generation":  [100.0] * 4,
        })

    def test_returns_dataframe(self):
        result = process_wind_forecast(self._make())
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_has_rolling_columns(self):
        result = process_wind_forecast(self._make())
        assert any("wind_fc_rel_" in c for c in result.columns)

    def test_index_freq_is_30min(self):
        result = process_wind_forecast(self._make())
        assert result.index.inferred_freq in ("30min", "30T")

    def test_index_name_is_time(self):
        result = process_wind_forecast(self._make())
        assert result.index.name == "time"

    def test_empty_input_returns_empty(self):
        df = pd.DataFrame(columns=["startTime", "publishTime", "generation"])
        result = process_wind_forecast(df)
        assert result.empty


# ---------------------------------------------------------------------------
# process_demand_forecast (end-to-end)
# ---------------------------------------------------------------------------

class TestProcessDemandForecast:
    def _make(self):
        delivery = pd.date_range("2018-01-10", periods=4, freq="30min", tz="UTC")
        forecast = [d - pd.Timedelta(hours=25) for d in delivery]
        return pd.DataFrame({
            "time":          [str(d) for d in delivery],
            "forecast_time": [str(f) for f in forecast],
            "value":         [25000.0] * 4,
        })

    def test_returns_dataframe(self):
        result = process_demand_forecast(self._make())
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_has_rolling_columns(self):
        result = process_demand_forecast(self._make())
        assert any("demand_fc_rel_" in c for c in result.columns)

    def test_index_is_utc(self):
        result = process_demand_forecast(self._make())
        assert result.index.tz == UTC


# ---------------------------------------------------------------------------
# merge_all
# ---------------------------------------------------------------------------

class TestMergeAll:
    """merge_all is pure except for the final to_parquet call, which is patched."""

    def _gen_mix(self):
        idx = _range("2018-01-01", 4)
        return pd.DataFrame({"gen_CCGT": [200.0] * 4}, index=idx)

    def _imbalance(self):
        idx = _range("2018-01-01", 4)
        return pd.DataFrame({
            "system_buy_price":  [100.0] * 4,
            "system_sell_price": [90.0]  * 4,
            "niv":               [5.0]   * 4,
        }, index=idx)

    def _da_price(self):
        idx = _range("2018-01-01", 4)
        return pd.DataFrame({"day_ahead_price": [50.0] * 4}, index=idx)

    def test_required_columns_all_present(self):
        with patch("src.data.preprocess.pd.DataFrame.to_parquet"):
            result = merge_all(self._gen_mix(), self._imbalance(), self._da_price())
        assert "gen_CCGT" in result.columns
        assert "system_buy_price" in result.columns
        assert "day_ahead_price" in result.columns

    def test_optional_none_skipped(self):
        with patch("src.data.preprocess.pd.DataFrame.to_parquet"):
            result = merge_all(
                self._gen_mix(), self._imbalance(), self._da_price(),
                wind_forecast=None, demand_forecast=None,
            )
        assert not result.empty

    def test_total_gen_actual_computed(self):
        with patch("src.data.preprocess.pd.DataFrame.to_parquet"):
            result = merge_all(self._gen_mix(), self._imbalance(), self._da_price())
        assert "total_gen_actual" in result.columns
        assert result["total_gen_actual"].iloc[0] == pytest.approx(200.0)

    def test_output_has_time_column(self):
        with patch("src.data.preprocess.pd.DataFrame.to_parquet"):
            result = merge_all(self._gen_mix(), self._imbalance(), self._da_price())
        assert "time" in result.columns

    def test_raises_when_all_empty(self):
        with patch("src.data.preprocess.pd.DataFrame.to_parquet"):
            with pytest.raises(ValueError, match="No data to merge"):
                merge_all(
                    pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
                )

    def test_duplicate_timestamps_removed(self):
        idx = _range("2018-01-01", 4)
        dup_idx = idx.append(idx[:2])  # add 2 duplicates
        gen = pd.DataFrame({"gen_CCGT": [200.0] * 6}, index=dup_idx)
        with patch("src.data.preprocess.pd.DataFrame.to_parquet"):
            result = merge_all(gen, self._imbalance(), self._da_price())
        assert len(result) == 4
