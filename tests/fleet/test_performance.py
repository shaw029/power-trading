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
    """Two sites, two days; site A: 100 MW 2h, site B: 50 MW 1h."""
    rows = []
    for date, a_gbp, b_gbp in ((_DATE, 10_000.0, 2_000.0), ("2024-01-02", 6_000.0, 4_000.0)):
        rows.append(
            {
                "date": date, "site": "A", "optimiser": "OptX", "region": "North",
                "duration": "2h",
                "power_mw": 100.0, "capacity_mwh": 200.0, "discharge_mwh": 200.0,
                "charge_mwh": 220.0, "wholesale_gbp": a_gbp, "bm_gbp": 0.0,
                "total_gbp": a_gbp, "gbp_per_mw": a_gbp / 100.0,
            }
        )
        rows.append(
            {
                "date": date, "site": "B", "optimiser": "OptY", "region": "South",
                "duration": "1h",
                "power_mw": 50.0, "capacity_mwh": 50.0, "discharge_mwh": 50.0,
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
    assert set(performance.filter_daily(daily, durations=["1h"])["site"]) == {"B"}


def test_site_profile_sums_bmus_and_converts_to_mw():
    # Two BMUs discharging 50 MW plus one charging 30 MW in the same half-hour
    # collapse to one site row at net 70 MW; energy → MW uses the 0.5 h slot.
    pn = [
        _pn_record("E_PILLB-1", 18, 0, 50.0),
        _pn_record("E_PILLB-2", 18, 0, 50.0),
        _pn_record("E_PILLB-1", 18, 30, -30.0),
    ]
    profile = performance.site_profile(pn)
    assert list(profile["site"].unique()) == ["Pillswood"]
    assert len(profile) == 2
    t18 = profile[profile["time"] == pd.Timestamp(f"{_DATE}T18:00:00Z")]
    assert t18["mw"].iloc[0] == pytest.approx(100.0)
    t1830 = profile[profile["time"] == pd.Timestamp(f"{_DATE}T18:30:00Z")]
    assert t1830["mw"].iloc[0] == pytest.approx(-30.0)


def test_site_profile_empty_records():
    profile = performance.site_profile([])
    assert list(profile.columns) == ["site", "time", "mw"]
    assert profile.empty


def test_duration_label_rounds_to_whole_hours():
    assert performance.duration_label(100.0, 107.0) == "1h"  # Capenhurst-style
    assert performance.duration_label(98.0, 196.0) == "2h"
    assert performance.duration_label(50.0, 50.0) == "1h"


def test_day_site_metrics_carries_duration():
    pn = [_pn_record("E_PILLB-1", 18, 0, 50.0)]
    df = performance.day_site_metrics(_DATE, pn, {"bid": [], "offer": []}, _mid(100.0))
    assert df.iloc[0]["duration"] == "2h"  # Pillswood: 196 MWh / 98 MW


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


def test_summarise_by_site_flags_low_cycling_as_likely_ancillary():
    daily = _daily_fixture()
    # Site B barely discharges: 10 MWh/day against 100 MWh nameplate = 0.1 cycles.
    daily.loc[daily["site"] == "B", "discharge_mwh"] = 10.0
    site_df = performance.summarise_by_site(daily).set_index("site")
    assert not site_df.loc["A", "likely_ancillary"]  # 1.0 cycles/day
    assert site_df.loc["B", "likely_ancillary"]


def test_summarise_by_optimiser_is_mw_weighted():
    opt_df = performance.summarise_by_optimiser(_daily_fixture())
    x = opt_df[opt_df["optimiser"] == "OptX"].iloc[0]
    assert x["gbp_per_mw_day"] == pytest.approx(16_000.0 / 200.0)  # 2 days × 100 MW
    assert x["sites"] == 1
    assert x["power_mw"] == pytest.approx(100.0)
    # Volume story: 200 MWh/day discharged over a 200 MWh nameplate = 1 cycle.
    assert x["discharge_mwh_day"] == pytest.approx(200.0)
    assert x["charge_mwh_day"] == pytest.approx(220.0)
    assert x["cycles_per_day"] == pytest.approx(1.0)


def test_fleet_daily_splits_components():
    daily = performance.fleet_daily(_daily_fixture())
    assert list(daily["date"]) == [_DATE, "2024-01-02"]
    day1 = daily.iloc[0]
    assert day1["total_gbp"] == pytest.approx(12_000.0)
    assert day1["bm_gbp"] == pytest.approx(1_000.0)
    assert day1["gbp_per_mw"] == pytest.approx(12_000.0 / 150.0)
    assert day1["discharge_mwh"] == pytest.approx(250.0)
    assert day1["charge_mwh"] == pytest.approx(275.0)
    assert day1["cycles"] == pytest.approx(250.0 / 250.0)


def _limit_record(bmu: str, t_from: str, t_to: str, level: float,
                  notified: str = "2024-01-01T00:00:00Z", seq: int = 1) -> dict:
    return {
        "bmUnit": bmu,
        "settlementDate": _DATE,
        "timeFrom": f"{_DATE}T{t_from}:00Z",
        "timeTo": f"{_DATE}T{t_to}:00Z",
        "levelFrom": level,
        "levelTo": level,
        "notificationTime": notified,
        "notificationSequence": seq,
    }


def test_site_limit_profile_time_weights_partial_spans():
    # 50 MW declared for 24 of 30 minutes, 0 MW for the rest: the half-hour
    # reads 40 MW — a last-effective rule would wrongly say 0 or 50.
    records = [
        _limit_record("E_PILLB-1", "18:00", "18:24", 50.0),
        _limit_record("E_PILLB-1", "18:24", "18:30", 0.0),
    ]
    profile = performance.site_limit_profile(records)
    assert list(profile.columns) == ["site", "time", "mw"]
    assert len(profile) == 1
    assert profile["site"].iloc[0] == "Pillswood"
    assert profile["time"].iloc[0] == pd.Timestamp(f"{_DATE}T18:00:00Z")
    assert profile["mw"].iloc[0] == pytest.approx(50.0 * 24 / 30)


def test_site_limit_profile_later_notification_overrides():
    # A redeclaration posted later overwrites the original across the overlap.
    records = [
        _limit_record("E_PILLB-1", "18:00", "18:30", 50.0,
                      notified="2024-01-01T10:00:00Z", seq=1),
        _limit_record("E_PILLB-1", "18:00", "18:30", 10.0,
                      notified="2024-01-01T17:00:00Z", seq=2),
    ]
    profile = performance.site_limit_profile(records)
    assert profile["mw"].iloc[0] == pytest.approx(10.0)


def test_site_limit_profile_sums_bmus_within_site():
    records = [
        _limit_record("E_PILLB-1", "18:00", "18:30", 49.0),
        _limit_record("E_PILLB-2", "18:00", "18:30", 49.0),
    ]
    profile = performance.site_limit_profile(records)
    assert len(profile) == 1
    assert profile["mw"].iloc[0] == pytest.approx(98.0)


def test_site_limit_profile_negative_mils_levels():
    records = [_limit_record("E_PILLB-1", "18:00", "18:30", -11.0)]
    profile = performance.site_limit_profile(records)
    assert profile["mw"].iloc[0] == pytest.approx(-11.0)


def test_site_limit_profile_empty_and_unknown_bmus():
    empty = performance.site_limit_profile([])
    assert list(empty.columns) == ["site", "time", "mw"]
    assert empty.empty
    unknown = performance.site_limit_profile(
        [_limit_record("T_NOTAFLEETUNIT-1", "18:00", "18:30", 50.0)]
    )
    assert unknown.empty


def _two_site_daily() -> pd.DataFrame:
    """Two sites over two days, with round numbers so ratios are exact."""
    rows = []
    for date, site, power, cap, disch, gbp in (
        ("2026-08-01", "A", 100.0, 200.0, 100.0, 5000.0),
        ("2026-08-01", "B", 50.0, 50.0, 25.0, 500.0),
        ("2026-08-02", "A", 100.0, 200.0, 200.0, 6000.0),
        ("2026-08-02", "B", 50.0, 50.0, 50.0, 2000.0),
    ):
        rows.append(
            {
                "date": date, "site": site, "optimiser": f"Opt{site}",
                "region": "R", "duration": "2h", "power_mw": power,
                "capacity_mwh": cap, "discharge_mwh": disch, "charge_mwh": disch,
                "wholesale_gbp": gbp, "bm_gbp": 0.0, "total_gbp": gbp,
                "gbp_per_mw": gbp / power,
            }
        )
    return pd.DataFrame(rows)


def test_capture_spread_is_revenue_over_throughput():
    site = performance.summarise_by_site(_two_site_daily()).set_index("site")
    # A: £11,000 over 300 MWh discharged.
    assert site.loc["A", "capture_spread"] == pytest.approx(11000.0 / 300.0)
    # B: £2,500 over 75 MWh.
    assert site.loc["B", "capture_spread"] == pytest.approx(2500.0 / 75.0)
    # Total cycles is throughput over nameplate energy, not a daily rate.
    assert site.loc["A", "total_cycles"] == pytest.approx(300.0 / 200.0)


def test_capture_spread_is_nan_when_nothing_was_discharged():
    daily = _two_site_daily()
    daily.loc[daily["site"] == "B", "discharge_mwh"] = 0.0
    site = performance.summarise_by_site(daily).set_index("site")
    # No throughput means no spread to report — never an infinity, which would
    # poison any median taken across sites.
    assert pd.isna(site.loc["B", "capture_spread"])
    assert pd.notna(site.loc["A", "capture_spread"])


def test_fleet_daily_distribution_spreads_across_sites():
    dist = performance.fleet_daily_distribution(_two_site_daily(), "revenue")
    assert list(dist.columns) == ["date", "median", "p25", "p75", "min", "max"]
    assert len(dist) == 2
    # Day one: A made £50/MW, B £10/MW.
    day1 = dist.iloc[0]
    assert day1["median"] == pytest.approx(30.0)
    assert day1["p25"] == pytest.approx(20.0)
    assert day1["p75"] == pytest.approx(40.0)
    # The outer band is the real spread, not the quartiles.
    assert day1["min"] == pytest.approx(10.0)
    assert day1["max"] == pytest.approx(50.0)


def test_fleet_daily_distribution_empty_input():
    empty = performance.fleet_daily_distribution(
        _two_site_daily().iloc[0:0], "revenue"
    )
    assert list(empty.columns) == ["date", "median", "p25", "p75", "min", "max"]
    assert empty.empty


def test_site_day_metric_derives_ratio_metrics():
    daily = _two_site_daily()
    cycles = performance.site_day_metric(daily, "cycles")
    assert cycles.iloc[0] == pytest.approx(100.0 / 200.0)
    capture = performance.site_day_metric(daily, "capture")
    assert capture.iloc[0] == pytest.approx(5000.0 / 100.0)
    assert performance.site_day_metric(daily, "capacity").iloc[0] == pytest.approx(100.0)


def test_fleet_daily_carries_capture_spread():
    daily = performance.fleet_daily(_two_site_daily())
    # Day one across both sites: £5,500 over 125 MWh.
    assert daily.iloc[0]["capture_spread"] == pytest.approx(5500.0 / 125.0)


def test_volume_is_reported_per_day_not_as_a_window_total():
    site = performance.summarise_by_site(_two_site_daily()).set_index("site")
    # A discharged 300 MWh over two days.
    assert site.loc["A", "discharge_mwh"] == pytest.approx(300.0)
    assert site.loc["A", "discharge_mwh_per_day"] == pytest.approx(150.0)


def test_capture_spread_pools_a_week_before_dividing():
    """A day of pure charging must not report a wild negative margin."""
    rows = []
    for i in range(10):
        # Alternating: charge-heavy day, then discharge-heavy day.
        charging = i % 2 == 0
        rows.append(
            {
                "date": f"2026-08-{i + 1:02d}", "site": "A", "optimiser": "X",
                "region": "R", "duration": "2h", "power_mw": 100.0,
                "capacity_mwh": 200.0,
                "discharge_mwh": 5.0 if charging else 195.0,
                "charge_mwh": 195.0 if charging else 5.0,
                "wholesale_gbp": -8000.0 if charging else 12000.0,
                "bm_gbp": 0.0,
                "total_gbp": -8000.0 if charging else 12000.0,
                "gbp_per_mw": -80.0 if charging else 120.0,
            }
        )
    daily = pd.DataFrame(rows)

    # Day by day the ratio is nonsense: -£8,000 over 5 MWh is -£1,600/MWh.
    naive = daily["total_gbp"] / daily["discharge_mwh"]
    assert naive.min() < -1000

    dist = performance.fleet_daily_distribution(daily, "capture")
    # Pooled over a week, charge and discharge balance and the margin is sane.
    assert not dist.empty
    assert dist["median"].abs().max() < 200


def test_capture_spread_drops_negligible_throughput():
    rows = [
        {
            "date": f"2026-08-{i + 1:02d}", "site": "A", "optimiser": "X",
            "region": "R", "duration": "2h", "power_mw": 100.0,
            "capacity_mwh": 200.0,
            "discharge_mwh": 0.1,          # far below the cycle floor
            "charge_mwh": 0.1,
            "wholesale_gbp": 0.0, "bm_gbp": 5000.0, "total_gbp": 5000.0,
            "gbp_per_mw": 50.0,
        }
        for i in range(10)
    ]
    # Balancing-market money over almost no throughput would read as thousands
    # of pounds per MWh; it is reported as nothing instead.
    assert performance.fleet_daily_distribution(pd.DataFrame(rows), "capture").empty
