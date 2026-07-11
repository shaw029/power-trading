"""Tests for the fleet performance calculations on synthetic records.

Pillswood (E_PILLB-1 / E_PILLB-2) from the real registry is used as the test
site so the BMU → site mapping is exercised for real.
"""

import pandas as pd
import pytest

from fleet import performance
from fleet.registry import FLEET

_DATE = "2024-01-01"
_PILLSWOOD = next(s for s in FLEET if s.site == "Pillswood")


def _pn_record(bmu: str, hour: int, minute: int, level: float) -> dict:
    start = pd.Timestamp(f"{_DATE}T{hour:02d}:{minute:02d}:00Z")
    return {
        "bmUnit": bmu,
        "settlementDate": _DATE,
        "timeFrom": start.isoformat(),
        "timeTo": (start + pd.Timedelta(minutes=30)).isoformat(),
        "levelFrom": level,
        "levelTo": level,
    }


def _mid(price: float) -> pd.DataFrame:
    times = pd.date_range(f"{_DATE}T00:00:00Z", periods=48, freq="30min")
    return pd.DataFrame({"mid_price": price}, index=times)


def _cashflow_record(bmu: str, **pairs) -> dict:
    cash = {"negative1": None, "positive1": None}
    cash.update(pairs)
    return {"bmUnit": bmu, "settlementPeriod": 1, "bidOfferPairCashflows": cash}


def test_day_site_metrics_energy_and_wholesale():
    # 50 MW discharge for one half hour on each BMU, 50 MW charge on one.
    pn = [
        _pn_record("E_PILLB-1", 18, 0, 50.0),
        _pn_record("E_PILLB-2", 18, 0, 50.0),
        _pn_record("E_PILLB-1", 3, 0, -50.0),
    ]
    df = performance.day_site_metrics(_DATE, pn, {"bid": [], "offer": []}, _mid(100.0))

    assert list(df["site"]) == ["Pillswood"]
    row = df.iloc[0]
    assert row["discharge_mwh"] == pytest.approx(50.0)  # 2 × 50 MW × 0.5 h
    assert row["charge_mwh"] == pytest.approx(25.0)
    # (50 − 25) MWh net at £100/MWh.
    assert row["wholesale_gbp"] == pytest.approx(2500.0)
    assert row["bm_gbp"] == 0.0
    assert row["total_gbp"] == pytest.approx(2500.0)
    assert row["gbp_per_mw"] == pytest.approx(2500.0 / _PILLSWOOD.power_mw)


def test_day_site_metrics_sums_bm_cashflows_across_bmus_and_pairs():
    cashflows = {
        "bid": [_cashflow_record("E_PILLB-1", negative1=-100.0)],
        "offer": [
            _cashflow_record("E_PILLB-1", positive1=300.0),
            _cashflow_record("E_PILLB-2", positive1=50.0, positive2=25.0),
        ],
    }
    df = performance.day_site_metrics(_DATE, [], cashflows, _mid(100.0))

    assert list(df["site"]) == ["Pillswood"]
    assert df.iloc[0]["bm_gbp"] == pytest.approx(275.0)
    assert df.iloc[0]["total_gbp"] == pytest.approx(275.0)


def test_day_site_metrics_omits_silent_sites():
    pn = [_pn_record("E_PILLB-1", 18, 0, 50.0)]
    df = performance.day_site_metrics(_DATE, pn, {"bid": [], "offer": []}, _mid(100.0))
    assert len(df) == 1  # only Pillswood, none of the other 22 sites


def test_day_site_metrics_missing_mid_price_falls_back_to_day_mean():
    pn = [_pn_record("E_PILLB-1", 18, 0, 50.0)]
    mid = _mid(100.0).iloc[:10]  # 18:00 has no MID print
    df = performance.day_site_metrics(_DATE, pn, {"bid": [], "offer": []}, mid)
    assert df.iloc[0]["wholesale_gbp"] == pytest.approx(25.0 * 100.0)


def _daily_fixture() -> pd.DataFrame:
    """Two sites, two days; site A: 100 MW, site B: 50 MW."""
    rows = []
    for date, a_gbp, b_gbp in ((_DATE, 10_000.0, 2_000.0), ("2024-01-02", 6_000.0, 4_000.0)):
        rows.append(
            {
                "date": date, "site": "A", "optimiser": "OptX", "region": "North",
                "power_mw": 100.0, "capacity_mwh": 200.0, "discharge_mwh": 200.0,
                "charge_mwh": 220.0, "wholesale_gbp": a_gbp, "bm_gbp": 0.0,
                "total_gbp": a_gbp, "gbp_per_mw": a_gbp / 100.0,
            }
        )
        rows.append(
            {
                "date": date, "site": "B", "optimiser": "OptY", "region": "South",
                "power_mw": 50.0, "capacity_mwh": 100.0, "discharge_mwh": 50.0,
                "charge_mwh": 55.0, "wholesale_gbp": b_gbp / 2, "bm_gbp": b_gbp / 2,
                "total_gbp": b_gbp, "gbp_per_mw": b_gbp / 50.0,
            }
        )
    return pd.DataFrame(rows)


def test_filter_daily_no_filters_returns_everything():
    daily = _daily_fixture()
    assert len(performance.filter_daily(daily)) == len(daily)
    # Empty lists (the dashboard's untouched multiselects) are also no-ops.
    assert len(performance.filter_daily(daily, sites=[], optimisers=[], day_types=[])) == len(
        daily
    )


def test_filter_daily_by_period_site_optimiser_region():
    daily = _daily_fixture()
    assert set(performance.filter_daily(daily, start="2024-01-02")["date"]) == {"2024-01-02"}
    assert set(performance.filter_daily(daily, end=_DATE)["date"]) == {_DATE}
    assert set(performance.filter_daily(daily, sites=["B"])["site"]) == {"B"}
    assert set(performance.filter_daily(daily, optimisers=["OptX"])["site"]) == {"A"}
    assert set(performance.filter_daily(daily, regions=["South"])["site"]) == {"B"}


def test_filter_daily_by_day_type_and_untagged():
    daily = _daily_fixture()
    labels = {_DATE: ["windy", "volatile"], "2024-01-02": []}

    windy = performance.filter_daily(daily, day_types=["windy"], day_labels=labels)
    assert set(windy["date"]) == {_DATE}

    untagged = performance.filter_daily(daily, day_types=["untagged"], day_labels=labels)
    assert set(untagged["date"]) == {"2024-01-02"}

    # A date missing from the labels map counts as untagged too.
    untagged = performance.filter_daily(daily, day_types=["untagged"], day_labels={})
    assert set(untagged["date"]) == {_DATE, "2024-01-02"}


def test_summarise_by_site_averages_and_ranks():
    site_df = performance.summarise_by_site(_daily_fixture())
    assert list(site_df["site"]) == ["A", "B"]  # £80 vs £60 per MW/day
    a = site_df.iloc[0]
    assert a["gbp_per_mw_day"] == pytest.approx(16_000.0 / (100.0 * 2))
    assert a["cycles_per_day"] == pytest.approx(400.0 / (200.0 * 2))


def test_summarise_by_optimiser_is_mw_weighted():
    opt_df = performance.summarise_by_optimiser(_daily_fixture())
    x = opt_df[opt_df["optimiser"] == "OptX"].iloc[0]
    assert x["gbp_per_mw_day"] == pytest.approx(16_000.0 / 200.0)  # 2 days × 100 MW
    assert x["sites"] == 1
    assert x["power_mw"] == pytest.approx(100.0)


def test_fleet_daily_splits_components():
    daily = performance.fleet_daily(_daily_fixture())
    assert list(daily["date"]) == [_DATE, "2024-01-02"]
    day1 = daily.iloc[0]
    assert day1["total_gbp"] == pytest.approx(12_000.0)
    assert day1["bm_gbp"] == pytest.approx(1_000.0)
    assert day1["gbp_per_mw"] == pytest.approx(12_000.0 / 150.0)
