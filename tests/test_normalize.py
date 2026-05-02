"""Unit tests for the two normalization helpers in src/data/download.py.

Both _normalize_forecast and _normalize_neso_ndfd are pure functions —
no network or filesystem access required.
"""

import numpy as np
import pandas as pd
import pytest

from src.data.download import _normalize_forecast, _normalize_neso_ndfd


# ---------------------------------------------------------------------------
# _normalize_forecast
# ---------------------------------------------------------------------------

class TestNormalizeForecastWindfor:
    """WINDFOR path: DataFrame has startTime + publishTime + generation."""

    def _make(self, n: int = 3, value_col: str = "generation"):
        delivery = pd.date_range("2018-01-10", periods=n, freq="30min", tz="UTC")
        publish  = delivery - pd.Timedelta(hours=24)
        df = pd.DataFrame({
            "startTime":   [str(d) for d in delivery],
            "publishTime": [str(p) for p in publish],
        })
        df[value_col] = [100.0 + i for i in range(n)]
        return df

    def test_output_columns_are_time_forecast_time_value(self):
        result = _normalize_forecast(self._make())
        assert list(result.columns) == ["time", "forecast_time", "value"]

    def test_time_is_utc(self):
        result = _normalize_forecast(self._make())
        assert str(result["time"].dt.tz) == "UTC"
        assert str(result["forecast_time"].dt.tz) == "UTC"

    def test_generation_mapped_to_value(self):
        result = _normalize_forecast(self._make(value_col="generation"))
        assert result["value"].iloc[0] == pytest.approx(100.0)

    def test_quantity_column_also_accepted(self):
        df = self._make(value_col="generation")
        df = df.rename(columns={"generation": "quantity"})
        result = _normalize_forecast(df)
        assert "value" in result.columns

    def test_missing_publish_time_raises(self):
        df = self._make()
        df = df.drop(columns=["publishTime"])
        with pytest.raises(ValueError, match="publishTime missing"):
            _normalize_forecast(df)

    def test_missing_value_column_raises(self):
        df = pd.DataFrame({
            "startTime":   ["2018-01-10 00:00:00+00:00"],
            "publishTime": ["2018-01-09 00:00:00+00:00"],
            # no generation or quantity
        })
        with pytest.raises(ValueError, match="No value column"):
            _normalize_forecast(df)

    def test_sorted_by_time_then_forecast_time(self):
        df = self._make(3)
        df = df.iloc[::-1].reset_index(drop=True)  # reverse order
        result = _normalize_forecast(df)
        assert result["time"].is_monotonic_increasing

    def test_duplicates_dropped(self):
        df = self._make(3)
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)  # add duplicate
        result = _normalize_forecast(df)
        dupes = result.duplicated(subset=["time", "forecast_time", "value"])
        assert not dupes.any()

    def test_does_not_mutate_input(self):
        df = self._make()
        original_cols = list(df.columns)
        _normalize_forecast(df)
        assert list(df.columns) == original_cols


class TestNormalizeForecastNdfd:
    """NDFD path: DataFrame has forecastDate + publishTime + demand."""

    def _make(self, n: int = 3):
        dates   = pd.date_range("2018-01-10", periods=n, freq="D")
        publish = dates - pd.Timedelta(hours=16)
        return pd.DataFrame({
            "forecastDate": [str(d.date()) for d in dates],
            "publishTime":  [str(p) for p in publish],
            "demand":       [25000.0 + i * 100 for i in range(n)],
        })

    def test_output_columns(self):
        result = _normalize_forecast(self._make())
        assert list(result.columns) == ["time", "forecast_time", "value"]

    def test_demand_mapped_to_value(self):
        result = _normalize_forecast(self._make())
        assert result["value"].iloc[0] == pytest.approx(25000.0)

    def test_time_is_utc(self):
        result = _normalize_forecast(self._make())
        assert str(result["time"].dt.tz) == "UTC"

    def test_missing_demand_raises(self):
        df = self._make()
        df = df.drop(columns=["demand"])
        with pytest.raises(ValueError, match="demand column missing"):
            _normalize_forecast(df)

    def test_missing_publish_time_raises(self):
        df = self._make()
        df = df.drop(columns=["publishTime"])
        with pytest.raises(ValueError, match="publishTime missing"):
            _normalize_forecast(df)


class TestNormalizeForecastUnknownStructure:
    def test_unknown_structure_raises(self):
        df = pd.DataFrame({"foo": [1], "bar": [2]})
        with pytest.raises(ValueError, match="Unknown dataset structure"):
            _normalize_forecast(df)


# ---------------------------------------------------------------------------
# _normalize_neso_ndfd
# ---------------------------------------------------------------------------

class TestNormalizeNesoNdfd:
    def _make(self, upper: bool = True, n: int = 3):
        """upper=True mimics the real NESO API column names (ALLCAPS)."""
        delivery = pd.date_range("2018-01-10", periods=n, freq="30min", tz="UTC")
        publish  = delivery - pd.Timedelta(hours=24)
        if upper:
            return pd.DataFrame({
                "DELIVERYTIME":   [str(d) for d in delivery],
                "PUBLISHTIME":    [str(p) for p in publish],
                "FORECASTDEMAND": [25000.0 + i for i in range(n)],
            })
        else:
            return pd.DataFrame({
                "deliverytime":   [str(d) for d in delivery],
                "publishtime":    [str(p) for p in publish],
                "forecastdemand": [25000.0 + i for i in range(n)],
            })

    def test_required_output_columns_present(self):
        result = _normalize_neso_ndfd(self._make())
        for col in ("time", "forecast_time", "value"):
            assert col in result.columns

    def test_case_insensitive_column_lookup_upper(self):
        result = _normalize_neso_ndfd(self._make(upper=True))
        assert not result.empty

    def test_case_insensitive_column_lookup_lower(self):
        result = _normalize_neso_ndfd(self._make(upper=False))
        assert not result.empty

    def test_forecastdemand_mapped_to_value(self):
        result = _normalize_neso_ndfd(self._make())
        assert result["value"].iloc[0] == pytest.approx(25000.0)

    def test_time_columns_are_utc(self):
        result = _normalize_neso_ndfd(self._make())
        assert str(result["time"].dt.tz) == "UTC"
        assert str(result["forecast_time"].dt.tz) == "UTC"

    def test_missing_forecastdemand_raises(self):
        df = self._make()
        df = df.drop(columns=["FORECASTDEMAND"])
        with pytest.raises(ValueError, match="forecastdemand"):
            _normalize_neso_ndfd(df)

    def test_publishtime_column_used_as_forecast_time(self):
        result = _normalize_neso_ndfd(self._make())
        expected_pub = pd.Timestamp("2018-01-09 00:00:00", tz="UTC")
        assert result["forecast_time"].iloc[0] == expected_pub

    def test_fallback_when_no_publish_time(self):
        # No PUBLISHTIME → forecast_time should equal time (delivery)
        df = pd.DataFrame({
            "DELIVERYTIME":   ["2018-01-10 00:00:00+00:00"],
            "FORECASTDEMAND": [25000.0],
        })
        result = _normalize_neso_ndfd(df)
        assert result["forecast_time"].iloc[0] == result["time"].iloc[0]

    def test_duplicates_dropped(self):
        df = self._make(n=3)
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        result = _normalize_neso_ndfd(df)
        dupes = result.duplicated(subset=["time", "forecast_time", "value"])
        assert not dupes.any()

    def test_optional_cardinal_point_preserved(self):
        df = self._make()
        df["CARDINALPOINT"] = ["N", "S", "E"]
        result = _normalize_neso_ndfd(df)
        assert "cardinal_point" in result.columns

    def test_optional_cp_type_preserved(self):
        df = self._make()
        df["CP_TYPE"] = ["A", "B", "A"]
        result = _normalize_neso_ndfd(df)
        assert "cp_type" in result.columns

    def test_unknown_optional_columns_not_in_output(self):
        df = self._make()
        df["RANDOM_EXTRA"] = [1, 2, 3]
        result = _normalize_neso_ndfd(df)
        assert "RANDOM_EXTRA" not in result.columns

    def test_does_not_mutate_input(self):
        df = self._make()
        original_cols = list(df.columns)
        _normalize_neso_ndfd(df)
        assert list(df.columns) == original_cols

    def test_non_numeric_forecastdemand_coerced(self):
        df = self._make(n=2)
        df["FORECASTDEMAND"] = df["FORECASTDEMAND"].astype(object)
        df.loc[0, "FORECASTDEMAND"] = "bad"
        result = _normalize_neso_ndfd(df)
        # row with bad value may still appear with NaN, or be filtered — either way, no crash
        assert isinstance(result, pd.DataFrame)

    def test_targetdate_column_accepted_as_time(self):
        # When only TARGETDATE is present (no DELIVERYTIME)
        df = pd.DataFrame({
            "TARGETDATE":     ["2018-01-10", "2018-01-11"],
            "PUBLISHTIME":    ["2018-01-09 10:00:00+00:00"] * 2,
            "FORECASTDEMAND": [25000.0, 26000.0],
        })
        result = _normalize_neso_ndfd(df)
        assert not result.empty
