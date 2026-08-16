"""Tests for the system-alignment (resilience) module.

Synthetic frames and a small lossless asset keep every check arithmetic-clean;
no network or Streamlit involvement.
"""

import pandas as pd
import pytest

from live import resilience
from src.bess.bess_asset import BESSAsset


def _idx(n: int, freq: str = "30min") -> pd.DatetimeIndex:
    return pd.date_range("2026-06-01T00:00:00Z", periods=n, freq=freq)


def _asset(soc: float = 0.5) -> BESSAsset:
    return BESSAsset(
        capacity_mwh=100.0,
        power_mw=50.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        degradation_cost_per_mwh=0.0,
        initial_soc_pct=soc,
        min_soc_pct=0.0,
        max_soc_pct=1.0,
    )


def test_residual_load_subtracts_wind_and_solar():
    idx = _idx(4)
    system = pd.DataFrame(
        {
            "demand_actual": [30000.0, 30000.0, 30000.0, 30000.0],
            "gen_WIND": [10000.0, 5000.0, 0.0, 10000.0],
            "solar_mw": [0.0, 5000.0, 10000.0, 0.0],
        },
        index=idx,
    )
    res = resilience.residual_load(system)
    assert res.tolist() == [20000.0, 20000.0, 20000.0, 20000.0]


def test_residual_load_missing_component_propagates_nan():
    # A day without a solar feed must not classify as demand-minus-wind only —
    # the whole day's residual comes back NaN and is excluded downstream.
    idx = _idx(2)
    system = pd.DataFrame(
        {"demand_actual": [25000.0, 26000.0], "gen_WIND": [8000.0, 8000.0]},
        index=idx,
    )
    assert resilience.residual_load(system).isna().all()


def test_classify_periods_excludes_unclassifiable_periods():
    # One period missing wind: it must vanish from the flags frame rather
    # than default to not-stressed, and must not distort the quantiles.
    idx = _idx(10)
    residual = pd.Series(
        [10, 20, 30, 40, float("nan"), 60, 70, 80, 90, 100], index=idx, dtype=float
    )
    flags = resilience.classify_periods(residual)
    assert len(flags) == 9
    assert idx[4] not in flags.index
    assert flags.loc[idx[9], "stress"]


def test_classify_periods_quantiles_and_negative_prices():
    idx = _idx(10)
    residual = pd.Series([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], index=idx, dtype=float)
    prices = pd.Series([50.0] * 9 + [50.0], index=idx)
    prices.iloc[4] = -5.0  # mid-residual period, negative price
    flags = resilience.classify_periods(residual, prices)
    assert flags.loc[idx[9], "stress"]        # top decile
    assert not flags.loc[idx[4], "stress"]
    assert flags.loc[idx[0], "surplus"]       # bottom decile
    assert flags.loc[idx[4], "surplus"]       # negative price ⇒ surplus
    assert not flags.loc[idx[5], "surplus"]


def test_alignment_scores_arithmetic():
    idx = _idx(4)
    flags = pd.DataFrame(
        {
            "residual_mw": [100.0, 50.0, 10.0, 90.0],
            "stress": [True, False, False, True],
            "surplus": [False, False, True, False],
        },
        index=idx,
    )
    # Discharge 40 in a stress period and 10 outside; charge 20 in surplus, 20 outside.
    dispatch = pd.Series([40.0, -20.0, -20.0, 10.0], index=idx)
    # Make the outside-stress discharge land outside stress: period 3 IS stress,
    # so discharge split is 40 (stress period 0) + 10 (stress period 3) → all in
    # stress. Move the second discharge off-stress instead:
    dispatch = pd.Series([40.0, 10.0, -20.0, -20.0], index=idx)
    scores = resilience.alignment_scores(dispatch, flags)
    assert scores["stress_coverage"] == pytest.approx(40.0 / 50.0)
    # Charge: 20 in surplus (period 2) + 20 in stress period 3 (not surplus).
    assert scores["surplus_absorption"] == pytest.approx(20.0 / 40.0)
    assert scores["total_discharge"] == pytest.approx(50.0)
    assert scores["total_charge"] == pytest.approx(40.0)


def test_alignment_scores_idle_battery_returns_none_shares():
    idx = _idx(3)
    flags = pd.DataFrame(
        {"residual_mw": [1.0, 2.0, 3.0], "stress": [False] * 3, "surplus": [False] * 3},
        index=idx,
    )
    scores = resilience.alignment_scores(pd.Series([0.0, 0.0, 0.0], index=idx), flags)
    assert scores["stress_coverage"] is None
    assert scores["surplus_absorption"] is None


def test_readiness_at_stress_onset_mean_soc():
    idx = _idx(5, freq="60min")
    stress = pd.Series([False, True, True, False, True], index=idx)
    soc = pd.Series([0.5, 0.8, 0.2, 0.4, 0.6], index=idx)
    # Onsets at periods 1 and 4 → mean(0.8, 0.6) = 0.7
    assert resilience.readiness_at_stress(soc, stress) == pytest.approx(0.7)


def test_readiness_none_when_no_onset():
    idx = _idx(3, freq="60min")
    stress = pd.Series([False, False, False], index=idx)
    soc = pd.Series([0.5, 0.5, 0.5], index=idx)
    assert resilience.readiness_at_stress(soc, stress) is None


def test_resilience_dispatch_targets_stress_and_surplus():
    # Surplus early, stress late: charge then discharge, within power/SOC limits.
    stress = [False, False, False, True, True, False]
    surplus = [True, True, False, False, False, False]
    schedule = resilience.optimize_resilience_dispatch(stress, surplus, _asset(soc=0.0))
    assert schedule[0] < 0 and schedule[1] < 0            # charges in surplus
    assert schedule[3] > 0 or schedule[4] > 0             # discharges in stress
    assert all(abs(mw) <= 50.0 + 1e-6 for mw in schedule)
    # Stays quiet outside flagged periods (tie-break penalty).
    assert schedule[2] == pytest.approx(0.0, abs=1e-6)
    assert schedule[5] == pytest.approx(0.0, abs=1e-6)


def test_resilience_dispatch_respects_cycle_cap():
    stress = [True] * 6
    surplus = [False] * 6
    schedule = resilience.optimize_resilience_dispatch(
        stress, surplus, _asset(soc=1.0), target_daily_cycles=0.5
    )
    discharged = sum(mw for mw in schedule if mw > 0)
    assert discharged <= 0.5 * 100.0 + 1e-6


def test_alignment_gap_signs_and_valuation():
    # Prices peak off-stress, so arbitrage discharges off-stress and the gap
    # has positive components on both sides.
    stress = [False, True, False, False]
    surplus = [False, False, False, True]
    prices = [30.0, 40.0, 100.0, 10.0]
    arb = [0.0, 0.0, 50.0, -50.0]  # sell the £100 hour, buy the £10 hour
    gap = resilience.alignment_gap(arb, prices, stress, surplus, _asset(soc=0.5))
    assert gap["profit_arb"] == pytest.approx(50 * 100 - 50 * 10)
    assert gap["stress_mwh_arb"] == pytest.approx(0.0)
    assert gap["stress_mwh_res"] > 0.0
    assert gap["profit_cost_of_alignment"] == pytest.approx(
        gap["profit_arb"] - gap["profit_res"]
    )
    assert gap["stress_mwh_forgone"] == pytest.approx(
        gap["stress_mwh_res"] - gap["stress_mwh_arb"]
    )


def test_alignment_gap_credits_terminal_inventory():
    # No stress at all: the resilience schedule only charges in surplus and
    # holds. With the inventory credit, buying 50 MWh at £10 and holding it at
    # a £30 mean price is a gain, not a pure cost.
    stress = [False, False, False, False]
    surplus = [False, False, False, True]
    prices = [40.0, 40.0, 30.0, 10.0]  # mean = 30
    gap = resilience.alignment_gap([0.0] * 4, prices, stress, surplus, _asset(soc=0.0))
    # Res schedule charges 50 MWh at £10 (−500) and holds 50 MWh valued at £30
    # (+1500) → profit_res = +1000, not −500.
    assert gap["profit_res"] == pytest.approx(50 * 30.0 - 50 * 10.0)
    assert gap["profit_arb"] == pytest.approx(0.0)


def test_resilience_dispatch_serves_stress_under_cycle_cap_no_churn():
    # Regression: with gross-flow surplus credit, a cycle-capped LP spent its
    # whole discharge budget enabling charge/discharge churn inside the surplus
    # window and left the stress hour unserved. The anti-gaming weights must
    # (a) serve the stress hour at full power, and (b) never discharge outside
    # stress periods.
    stress = [False] * 19 + [True] + [False] * 4
    surplus = [False] * 9 + [True] * 7 + [False] * 8
    asset = BESSAsset(
        capacity_mwh=100.0, power_mw=50.0,
        charge_efficiency=0.94, discharge_efficiency=0.94,
        degradation_cost_per_mwh=5.0, initial_soc_pct=0.10,
        min_soc_pct=0.10, max_soc_pct=0.90,
    )
    schedule = resilience.optimize_resilience_dispatch(
        stress, surplus, asset, target_daily_cycles=1.5
    )
    assert schedule[19] == pytest.approx(50.0, abs=1e-6)
    for h, mw in enumerate(schedule):
        if not stress[h]:
            assert mw <= 1e-6, f"off-stress discharge at hour {h}: {mw}"


def _tier_flags(n: int = 6) -> pd.DataFrame:
    idx = _idx(n)
    return pd.DataFrame(
        {
            "residual_mw": [float(10 * (i + 1)) for i in range(n)],
            "stress": [False] * (n - 2) + [True, True],
            "surplus": [True] + [False] * (n - 1),
        },
        index=idx,
    )


def test_classify_tiers_thresholds_and_unknowns():
    flags = _tier_flags(6)
    lolpdrm = pd.DataFrame(
        {
            # Period 2: LoLP alone trips tier 2. Period 3: DRM 1999 < 2000 trips.
            # Period 4: DRM exactly 2000 does NOT (strict <). Period 5: no data.
            "lolp": [0.0, 0.0, 0.02, 0.0, 0.0, float("nan")],
            "drm_mw": [9000.0, 9000.0, 9000.0, 1999.0, 2000.0, float("nan")],
        },
        index=flags.index,
    )
    tiers = resilience.classify_tiers(flags, lolpdrm)
    assert tiers["tier2"].tolist() == [False, False, True, True, False, False]
    assert tiers["tier2_known"].tolist() == [True] * 5 + [False]
    # Unknown is not calm: period 5 is excluded, not classified False-with-data.
    assert not tiers["tier2_known"].iloc[5]
    # tier = highest active: period 4 is tier-1 stress only, period 5 tier 1.
    assert tiers["tier"].tolist() == [0, 0, 2, 2, 1, 1]


def test_classify_tiers_without_feeds_degrades_gracefully():
    flags = _tier_flags(4)
    tiers = resilience.classify_tiers(flags, lolpdrm=None, cmn_windows=None)
    assert not tiers["tier2_known"].any()
    assert not tiers["tier2"].any()
    assert not tiers["tier3"].any()
    assert tiers["tier"].tolist() == [int(s) for s in flags["stress"]]


def test_cmn_flags_half_open_overlap():
    idx = _idx(4)  # 10:00 handled generically: periods at 00:00..01:30
    windows = pd.DataFrame(
        {
            "start_utc": [pd.Timestamp("2026-06-01T00:15:00Z")],
            "end_utc": [pd.Timestamp("2026-06-01T00:45:00Z")],
        }
    )
    flagged = resilience.cmn_flags(idx, windows)
    # The 00:00 and 00:30 half-hours overlap [00:15, 00:45); 01:00 does not —
    # a window ending exactly at a period's start must not flag it.
    assert flagged.tolist() == [True, True, False, False]

    nat_rows = pd.DataFrame({"start_utc": [pd.NaT], "end_utc": [pd.NaT]})
    assert not resilience.cmn_flags(idx, nat_rows).any()
    assert not resilience.cmn_flags(idx, None).any()
    assert not resilience.cmn_flags(idx, pd.DataFrame()).any()

    # An issued-and-still-open notice has a start but no end yet (the register
    # only stamps the end on cancellation): it must flag its target settlement
    # period, never be silently dropped.
    open_notice = pd.DataFrame(
        {"start_utc": [pd.Timestamp("2026-06-01T01:00:00Z")], "end_utc": [pd.NaT]}
    )
    assert resilience.cmn_flags(idx, open_notice).tolist() == [False, False, True, False]


def test_tier_metrics_arithmetic_and_unknown_exclusion():
    flags = _tier_flags(6)
    lolpdrm = pd.DataFrame(
        {
            "lolp": [0.0, 0.0, 0.1, 0.0, 0.0, float("nan")],
            "drm_mw": [9000.0, 8000.0, 1500.0, 3000.0, 2500.0, float("nan")],
        },
        index=flags.index,
    )
    tiers = resilience.classify_tiers(flags, lolpdrm)
    # Discharge 30 in the tier-2 period, 10 in a known non-tier-2 period, and
    # 40 in the unknown period (must not enter the coverage denominator).
    dispatch = pd.Series([0.0, -20.0, 30.0, 10.0, 0.0, 40.0], index=flags.index)
    m = resilience.tier_metrics(tiers, dispatch)
    assert m["min_drm_mw"] == pytest.approx(1500.0)
    assert m["min_drm_time"] == flags.index[2]
    assert m["n_lolp_positive"] == 1
    assert m["n_tier2"] == 1
    assert m["n_tier2_known"] == 5
    assert m["tier2_coverage"] == pytest.approx(30.0 / 40.0)
    # min DRM while discharging considers known-DRM periods only.
    assert m["min_drm_at_discharge"] == pytest.approx(1500.0)
    # Both tier-1 stress periods (4, 5): period 5 unknown → confirmable = {4},
    # which is not tier 2, so the confirm rate is 0.
    assert m["tier2_confirm_rate"] == pytest.approx(0.0)


def test_tier_metrics_none_denominators_and_no_cmn():
    flags = _tier_flags(4)
    tiers = resilience.classify_tiers(flags, lolpdrm=None)
    idle = pd.Series([0.0] * 4, index=flags.index)
    soc = pd.Series([0.5] * 4, index=flags.index)
    m = resilience.tier_metrics(tiers, idle, soc)
    assert m["min_drm_mw"] is None
    assert m["min_drm_time"] is None
    assert m["tier2_coverage"] is None
    assert m["min_drm_at_discharge"] is None
    assert m["tier2_confirm_rate"] is None  # no stress period has tier-2 data
    assert m["readiness_at_cmn"] is None  # no CMN onset anywhere
