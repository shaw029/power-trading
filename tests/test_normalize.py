"""Unit tests for the two normalization helpers in src/data/download.py.

Both _normalize_forecast and _normalize_neso_ndfd are pure functions —
no network or filesystem access required.
"""

import numpy as np
import pandas as pd
import pytest

from src.data.download import _normalize_elexon_ndfd, _normalize_neso_ndfd


# ---------------------------------------------------------------------------
# _normalize_elexon_ndfd
# ---------------------------------------------------------------------------

class TestNormalizeElexonNdfd:
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
        result = _normalize_elexon_ndfd(self._make())
        assert list(result.columns) == ["time", "forecast_time", "value"]

    def test_demand_mapped_to_value(self):
        result = _normalize_elexon_ndfd(self._make())
        assert result["value"].iloc[0] == pytest.approx(25000.0)

    def test_time_is_utc(self):
        result = _normalize_elexon_ndfd(self._make())
        assert str(result["time"].dt.tz) == "UTC"

    def test_missing_demand_raises(self):
        df = self._make()
        df = df.drop(columns=["demand"])
        with pytest.raises(ValueError, match="demand column missing for Elexon NDFD"):
            _normalize_elexon_ndfd(df)

    def test_missing_publish_time_raises(self):
        df = self._make()
        df = df.drop(columns=["publishTime"])
        with pytest.raises(ValueError, match="publishTime missing for Elexon NDFD"):
            _normalize_elexon_ndfd(df)


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
