"""Tests for the single-day live data adapter.

The underlying ``src.data`` fetchers are mocked with in-memory fixture frames so
no real network calls happen; the real ``process_*`` functions run on top of
those fixtures.
"""

import datetime as dt
from unittest import mock

import pandas as pd
import pytest

from live import fetch_live

_DAY = dt.date(2024, 1, 1)


def _day_ahead_raw() -> pd.DataFrame:
    """Hourly day-ahead prices for the delivery day (time, value)."""
    times = pd.date_range("2024-01-01T00:00:00Z", periods=24, freq="60min")
    return pd.DataFrame({"time": times, "value": range(50, 74)})


def _mid_raw() -> pd.DataFrame:
    """Half-hourly APXMIDP market-index prices (startTime, dataProvider, price)."""
    times = pd.date_range("2024-01-01T00:00:00Z", periods=48, freq="30min")
    return pd.DataFrame(
        {
            "startTime": times,
            "dataProvider": "APXMIDP",
            "price": range(48),
        }
    )


def _generation_raw() -> pd.DataFrame:
    """Half-hourly generation mix for WIND, SOLAR and GAS (long format)."""
    times = pd.date_range("2024-01-01T00:00:00Z", periods=48, freq="30min")
    frames = []
    for fuel, mw in (("WIND", 1000.0), ("SOLAR", 500.0), ("CCGT", 2000.0)):
        frames.append(pd.DataFrame({"startTime": times, "fuelType": fuel, "generation": mw}))
    return pd.concat(frames, ignore_index=True)


def _demand_raw() -> pd.DataFrame:
    """Half-hourly actual demand (startTime, demand)."""
    times = pd.date_range("2024-01-01T00:00:00Z", periods=48, freq="30min")
    return pd.DataFrame({"startTime": times, "demand": 30000.0})


def test_get_day_prices_returns_hourly_frame_with_both_columns():
    with (
        mock.patch.object(fetch_live, "fetch_day_ahead_price", return_value=_day_ahead_raw()),
        mock.patch.object(fetch_live, "fetch_market_index_price", return_value=_mid_raw()),
    ):
        prices = fetch_live.get_day_prices(_DAY)

    assert list(prices.columns) == ["day_ahead_price", "mid_price"]
    assert len(prices) == 24
    assert isinstance(prices.index, pd.DatetimeIndex)
    assert str(prices.index.tz) == "UTC"
    assert prices.index.min() == pd.Timestamp("2024-01-01T00:00:00Z")
    assert prices.index.max() == pd.Timestamp("2024-01-01T23:00:00Z")
    assert not prices.isna().any().any()


def test_get_day_prices_keeps_day_ahead_rows_with_missing_mid():
    # Mid price covers only the first 23 hours, so the final hour has a valid
    # day-ahead price but no mid price.
    mid_short = _mid_raw().iloc[: 23 * 2]
    with (
        mock.patch.object(fetch_live, "fetch_day_ahead_price", return_value=_day_ahead_raw()),
        mock.patch.object(fetch_live, "fetch_market_index_price", return_value=mid_short),
    ):
        prices = fetch_live.get_day_prices(_DAY)

    # All 24 day-ahead rows are kept even though the last hour's mid is missing.
    assert len(prices) == 24
    assert not prices["day_ahead_price"].isna().any()
    last = pd.Timestamp("2024-01-01T23:00:00Z")
    assert last in prices.index
    assert pd.isna(prices.loc[last, "mid_price"])


def test_get_day_context_returns_four_aggregate_fields():
    with (
        mock.patch.object(fetch_live, "fetch_generation_actual", return_value=_generation_raw()),
        mock.patch.object(fetch_live, "fetch_demand_actual", return_value=_demand_raw()),
    ):
        context = fetch_live.get_day_context(_DAY)

    assert set(context) == {"wind_gwh", "solar_gwh", "demand_gwh", "wind_share"}
    # 1000 MW across 48 half-hours = 1000 * 0.5 * 48 MWh = 24 GWh.
    assert context["wind_gwh"] == pytest.approx(24.0)
    assert context["solar_gwh"] == pytest.approx(12.0)
    assert context["demand_gwh"] == pytest.approx(720.0)
    # wind / (wind + solar + ccgt) = 1000 / 3500.
    assert context["wind_share"] == pytest.approx(1000.0 / 3500.0)


def test_get_day_context_returns_none_when_fetchers_raise():
    boom = mock.Mock(side_effect=RuntimeError("network down"))
    with (
        mock.patch.object(fetch_live, "fetch_generation_actual", boom),
        mock.patch.object(fetch_live, "fetch_demand_actual", boom),
    ):
        context = fetch_live.get_day_context(_DAY)

    assert context == {
        "wind_gwh": None,
        "solar_gwh": None,
        "demand_gwh": None,
        "wind_share": None,
    }
