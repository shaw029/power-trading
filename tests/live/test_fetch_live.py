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
    """Half-hourly transmission generation mix (long format) — no solar,
    exactly like the real FUELHH feed."""
    times = pd.date_range("2024-01-01T00:00:00Z", periods=48, freq="30min")
    frames = []
    for fuel, mw in (("WIND", 1000.0), ("CCGT", 2500.0)):
        frames.append(pd.DataFrame({"startTime": times, "fuelType": fuel, "generation": mw}))
    return pd.concat(frames, ignore_index=True)


def _solar_raw() -> pd.DataFrame:
    """Half-hourly PV_Live national solar outturn (time, solar_mw)."""
    times = pd.date_range("2024-01-01T00:00:00Z", periods=48, freq="30min")
    return pd.DataFrame({"time": times, "solar_mw": 500.0})


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


def test_get_day_prices_falls_back_missing_mid_to_day_ahead():
    # Mid price covers only the first 23 hours, so the final hour has a valid
    # day-ahead price but no mid price.
    mid_short = _mid_raw().iloc[: 23 * 2]
    with (
        mock.patch.object(fetch_live, "fetch_day_ahead_price", return_value=_day_ahead_raw()),
        mock.patch.object(fetch_live, "fetch_market_index_price", return_value=mid_short),
    ):
        prices = fetch_live.get_day_prices(_DAY)

    # All 24 day-ahead rows are kept and no NaN survives — the last hour's
    # missing mid falls back to that hour's day-ahead price, so the frame is
    # safe for the intraday LP and for strict-JSON serialisation.
    assert len(prices) == 24
    assert not prices.isna().any().any()
    last = pd.Timestamp("2024-01-01T23:00:00Z")
    assert last in prices.index
    assert prices.loc[last, "mid_price"] == prices.loc[last, "day_ahead_price"]


def test_get_day_context_returns_four_aggregate_fields():
    with (
        mock.patch.object(fetch_live, "fetch_generation_actual", return_value=_generation_raw()),
        mock.patch.object(fetch_live, "fetch_solar_actual", return_value=_solar_raw()),
        mock.patch.object(fetch_live, "fetch_demand_actual", return_value=_demand_raw()),
    ):
        context = fetch_live.get_day_context(_DAY)

    assert set(context) == {"wind_gwh", "solar_gwh", "demand_gwh", "wind_share"}
    # 1000 MW across 48 half-hours = 1000 * 0.5 * 48 MWh = 24 GWh.
    assert context["wind_gwh"] == pytest.approx(24.0)
    # Solar comes from PV_Live, not the transmission mix: 500 MW → 12 GWh.
    assert context["solar_gwh"] == pytest.approx(12.0)
    assert context["demand_gwh"] == pytest.approx(720.0)
    # wind / (wind + ccgt), transmission-metered only — solar is not in the mix.
    assert context["wind_share"] == pytest.approx(1000.0 / 3500.0)


def test_solar_failure_leaves_other_context_fields_intact():
    boom = mock.Mock(side_effect=RuntimeError("pvlive down"))
    with (
        mock.patch.object(fetch_live, "fetch_generation_actual", return_value=_generation_raw()),
        mock.patch.object(fetch_live, "fetch_solar_actual", boom),
        mock.patch.object(fetch_live, "fetch_demand_actual", return_value=_demand_raw()),
    ):
        context = fetch_live.get_day_context(_DAY)

    assert context["solar_gwh"] is None  # honest None, never a silent 0.0
    assert context["wind_gwh"] == pytest.approx(24.0)
    assert context["demand_gwh"] == pytest.approx(720.0)


def test_generation_aggregates_raises_when_no_data_for_day():
    # Generation rows exist, but all fall on a different day, so after the
    # delivery-day window filter nothing remains and a ValueError is raised.
    times = pd.date_range("2024-02-01T00:00:00Z", periods=48, freq="30min")
    other_day = pd.DataFrame({"startTime": times, "fuelType": "WIND", "generation": 1000.0})
    with mock.patch.object(fetch_live, "fetch_generation_actual", return_value=other_day):
        with pytest.raises(ValueError):
            fetch_live._generation_aggregates(_DAY)


def test_group_generation_collapses_and_conserves():
    idx = pd.date_range("2024-01-01T00:00:00Z", periods=2, freq="30min")
    system = pd.DataFrame(
        {
            "gen_WIND": [1000.0, 1100.0],
            "gen_CCGT": [2000.0, 1900.0],
            "gen_OCGT": [100.0, 120.0],
            "gen_INTFR": [500.0, -300.0],  # export in the second period
            "gen_INTNED": [200.0, 200.0],
            "gen_COAL": [0.0, 10.0],  # unmapped → Other
            "solar_mw": [0.0, 400.0],
        },
        index=idx,
    )
    grouped = fetch_live.group_generation(system)
    # Fixed order, only groups with data.
    assert list(grouped.columns) == ["Wind", "Solar", "Gas", "Interconnectors", "Other"]
    assert grouped["Gas"].tolist() == [2100.0, 2020.0]  # CCGT + OCGT
    assert grouped["Interconnectors"].tolist() == [700.0, -100.0]  # net, signed
    assert grouped["Other"].tolist() == [0.0, 10.0]  # coal folded in
    # Total MW is conserved across the regrouping.
    assert grouped.sum(axis=1).tolist() == system.sum(axis=1).tolist()


def test_get_day_system_merges_sources_and_survives_partial():
    with (
        mock.patch.object(fetch_live, "fetch_generation_actual", return_value=_generation_raw()),
        mock.patch.object(fetch_live, "fetch_solar_actual", return_value=_solar_raw()),
        mock.patch.object(fetch_live, "fetch_demand_actual", return_value=_demand_raw()),
    ):
        system = fetch_live.get_day_system(_DAY)
    assert "gen_WIND" in system.columns
    assert "solar_mw" in system.columns
    assert "demand_actual" in system.columns
    assert len(system) == 48

    # Solar feed down: the snapshot still returns, just without solar.
    boom = mock.Mock(side_effect=RuntimeError("pvlive down"))
    with (
        mock.patch.object(fetch_live, "fetch_generation_actual", return_value=_generation_raw()),
        mock.patch.object(fetch_live, "fetch_solar_actual", boom),
        mock.patch.object(fetch_live, "fetch_demand_actual", return_value=_demand_raw()),
    ):
        partial = fetch_live.get_day_system(_DAY)
    assert "solar_mw" not in partial.columns
    assert "gen_WIND" in partial.columns


def test_get_day_system_empty_when_all_sources_fail():
    boom = mock.Mock(side_effect=RuntimeError("down"))
    with (
        mock.patch.object(fetch_live, "fetch_generation_actual", boom),
        mock.patch.object(fetch_live, "fetch_solar_actual", boom),
        mock.patch.object(fetch_live, "fetch_demand_actual", boom),
    ):
        assert fetch_live.get_day_system(_DAY).empty


def test_get_day_context_returns_none_when_fetchers_raise():
    boom = mock.Mock(side_effect=RuntimeError("network down"))
    with (
        mock.patch.object(fetch_live, "fetch_generation_actual", boom),
        mock.patch.object(fetch_live, "fetch_solar_actual", boom),
        mock.patch.object(fetch_live, "fetch_demand_actual", boom),
    ):
        context = fetch_live.get_day_context(_DAY)

    assert context == {
        "wind_gwh": None,
        "solar_gwh": None,
        "demand_gwh": None,
        "wind_share": None,
    }


def test_get_day_system_drops_unpublished_generation_periods():
    # FUELHH lag: the last two half-hours arrive with no fuel rows at all.
    # Those periods must be dropped, not treated as zero generation.
    gen = _generation_raw()
    times = pd.date_range("2024-01-01T00:00:00Z", periods=48, freq="30min")
    gen = gen[~gen["startTime"].isin(times[-2:])]
    with (
        mock.patch.object(fetch_live, "fetch_generation_actual", return_value=gen),
        mock.patch.object(fetch_live, "fetch_solar_actual", return_value=_solar_raw()),
        mock.patch.object(fetch_live, "fetch_demand_actual", return_value=_demand_raw()),
    ):
        system = fetch_live.get_day_system(_DAY)
    assert len(system) == 46
    assert not system[[c for c in system.columns if c.startswith("gen_")]].isna().all(axis=1).any()


def _lolpdrm_raw() -> pd.DataFrame:
    """Two settlement periods, several horizon prints each; plus one row on
    the next UTC day that the day window must slice off."""
    rows = []
    for minute, horizons in ((0, (8, 1)), (30, (4,))):
        start = pd.Timestamp(f"2024-01-01T00:{minute:02d}:00Z")
        for h in horizons:
            rows.append(
                {
                    "publishTime": start - pd.Timedelta(hours=h),
                    "startTime": start,
                    "forecastHorizon": h,
                    "lossOfLoadProbability": 0.0,
                    "deratedMargin": 8000.0 + h,
                }
            )
    rows.append(
        {
            "publishTime": pd.Timestamp("2024-01-01T23:00:00Z"),
            "startTime": pd.Timestamp("2024-01-02T00:00:00Z"),
            "forecastHorizon": 1,
            "lossOfLoadProbability": 0.9,
            "deratedMargin": 100.0,
        }
    )
    return pd.DataFrame(rows)


def test_get_day_lolpdrm_windows_to_day_and_softfails():
    with mock.patch.object(fetch_live, "fetch_lolpdrm", return_value=_lolpdrm_raw()):
        day = fetch_live.get_day_lolpdrm(_DAY)
    assert list(day.columns) == ["lolp", "drm_mw"]
    assert len(day) == 2  # next-day row sliced off
    # Latest print per period: horizon 1 for 00:00, the only (4h) for 00:30.
    assert day["drm_mw"].tolist() == [8001.0, 8004.0]

    boom = mock.Mock(side_effect=RuntimeError("elexon down"))
    with mock.patch.object(fetch_live, "fetch_lolpdrm", boom):
        assert fetch_live.get_day_lolpdrm(_DAY).empty


def _cmn_raw() -> list[dict]:
    return [
        {
            "id": 37,
            "type": {"id": 1, "name": "CMN"},
            "title": "Electricity Capacity Market Notice Currently Active",
            "posted": {"timestamp": 1736337674},
            "extended": {
                "startDate": {"timestamp": 1736353800},
                "endDate": {"timestamp": 1736368200},
            },
        },
        {
            "id": 38,
            "type": {"id": 4, "name": "CMN Expiry"},
            "title": "Electricity Capacity Market Notice Cancelled",
            "posted": {"timestamp": 1736339569},
            "extended": {},  # no target window on the expiry row
        },
    ]


def test_get_cmn_notices_parses_timestamps_and_softfails():
    with mock.patch.object(fetch_live, "fetch_cmn_notices", return_value=_cmn_raw()):
        notices = fetch_live.get_cmn_notices()

    assert list(notices.columns) == fetch_live._CMN_COLUMNS
    assert len(notices) == 2
    # Sorted newest-posted first; epoch seconds become tz-aware UTC stamps.
    assert notices["notice_id"].tolist() == [38, 37]
    issued = notices[notices["type_id"] == fetch_live.CMN_ISSUE_TYPE].iloc[0]
    assert issued["posted_utc"] == pd.Timestamp(1736337674, unit="s", tz="UTC")
    assert issued["start_utc"] == pd.Timestamp(1736353800, unit="s", tz="UTC")
    # The expiry row has no target window — NaT, never a fabricated time.
    expiry = notices[notices["type_id"] == fetch_live.CMN_EXPIRY_TYPE].iloc[0]
    assert pd.isna(expiry["start_utc"])

    boom = mock.Mock(side_effect=RuntimeError("register down"))
    with mock.patch.object(fetch_live, "fetch_cmn_notices", boom):
        empty = fetch_live.get_cmn_notices()
    assert empty.empty
    assert list(empty.columns) == fetch_live._CMN_COLUMNS
