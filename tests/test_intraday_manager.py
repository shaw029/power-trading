import pytest

from src.bess.bess_asset import BESSAsset
from src.bess.intraday_manager import (
    _compute_implied_soc,
    _find_bottleneck_index,
    run_intraday_session,
)


class TestComputeImpliedSocClamping:
    def test_soc_clamped_above_capacity(self):
        soc = _compute_implied_soc(
            da_schedule=[-200.0, -200.0],
            initial_soc_mwh=80.0,
            charge_efficiency=0.9,
            discharge_efficiency=0.95,
            min_soc_mwh=0.0,
            max_soc_mwh=100.0,
        )
        assert all(s <= 100.0 for s in soc)
        assert soc[-1] == pytest.approx(100.0)

    def test_soc_clamped_below_zero(self):
        soc = _compute_implied_soc(
            da_schedule=[200.0, 200.0],
            initial_soc_mwh=20.0,
            charge_efficiency=0.9,
            discharge_efficiency=0.95,
            min_soc_mwh=0.0,
            max_soc_mwh=100.0,
        )
        assert all(s >= 0.0 for s in soc)
        assert soc[-1] == pytest.approx(0.0)


class TestNoRebalance:
    def test_clean_execution_no_rebalance(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=5.0, initial_soc_pct=0.5,
        )
        result = run_intraday_session(
            da_schedule=[10.0, -10.0, 0.0],
            da_price_actual=[50.0, 30.0, 40.0],
            mid_prices=[51.0, 31.0, 40.0],
            imbalance_prices=[48.0, 32.0, 40.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 5.0},
        )

        assert result["da_revenue_delivered"] == pytest.approx(200.0)
        assert result["intraday_pnl"] == pytest.approx(0.0)
        assert result["imbalance_pnl"] == pytest.approx(0.0)
        assert result["total_degradation_cost"] == pytest.approx(100.0)
        assert result["net_pnl"] == pytest.approx(100.0)
        assert len(result["dispatch_log"]) == 3
        assert result["dispatch_log"][0]["action"] == "discharge"
        assert result["dispatch_log"][1]["action"] == "charge"
        assert result["dispatch_log"][2]["action"] == "idle"


class TestSpreadImprovement:
    def test_favorable_mid_triggers_extra_discharge(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=2.0, initial_soc_pct=0.6,
        )
        result = run_intraday_session(
            da_schedule=[46.0],
            da_price_actual=[40.0],
            mid_prices=[50.0],
            imbalance_prices=[38.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 2.0},
        )

        assert result["da_revenue_delivered"] == pytest.approx(46.0 * 40.0)
        assert result["intraday_pnl"] == pytest.approx(4.0 * 50.0)
        assert result["imbalance_pnl"] == pytest.approx(0.0)

    def test_no_trigger_when_spread_below_degradation(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=10.0, initial_soc_pct=0.5,
        )
        result = run_intraday_session(
            da_schedule=[20.0],
            da_price_actual=[40.0],
            mid_prices=[45.0],
            imbalance_prices=[38.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 10.0},
        )

        assert result["intraday_pnl"] == pytest.approx(0.0)


class TestHalfHourlyResolution:
    def test_half_hourly_session(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.88,
            discharge_efficiency=1.0, degradation_cost_per_mwh=5.0, initial_soc_pct=0.5,
        )
        result = run_intraday_session(
            da_schedule=[10.0, -10.0],
            da_price_actual=[50.0, 30.0],
            mid_prices=[50.0, 30.0],
            imbalance_prices=[48.0, 32.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 5.0, "resolution_h": 0.5},
        )

        assert result["da_revenue_delivered"] == pytest.approx(10 * 0.5 * 50 + (-10) * 0.5 * 30)
        assert result["intraday_pnl"] == pytest.approx(0.0)
        assert result["imbalance_pnl"] == pytest.approx(0.0)
        assert result["total_degradation_cost"] == pytest.approx(5.0 * 5.0 + 5.0 * 5.0)
        assert len(result["dispatch_log"]) == 2
        assert result["dispatch_log"][0]["action"] == "discharge"
        assert result["dispatch_log"][1]["action"] == "charge"
        assert result["dispatch_log"][1]["soc_after"] == pytest.approx(0.494)


class TestImbalanceFallback:
    def test_discharge_shortfall_settles_at_imbalance(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=1.0, initial_soc_pct=0.2,
        )
        result = run_intraday_session(
            da_schedule=[30.0],
            da_price_actual=[50.0],
            mid_prices=[50.0],
            imbalance_prices=[60.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 1.0},
        )

        max_mw = 20.0 * 0.95
        shortfall = 30.0 - max_mw
        assert result["da_revenue_delivered"] == pytest.approx(30.0 * 50.0)
        assert result["imbalance_pnl"] == pytest.approx(-shortfall * 60.0)
        assert result["dispatch_log"][0]["mw"] == pytest.approx(max_mw)

    def test_charge_shortfall_settles_at_ssp(self):
        # Charging shortfall: BESS is long (couldn't absorb), settles at SSP not SBP.
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=1.0, initial_soc_pct=0.9,
        )
        result = run_intraday_session(
            da_schedule=[-40.0],
            da_price_actual=[30.0],
            mid_prices=[30.0],
            imbalance_prices=[25.0],       # SBP
            asset=asset,
            config={"degradation_cost_per_mwh": 1.0},
            imbalance_sell_prices=[18.0],  # SSP — distinct value to confirm it is used
        )

        max_charge = 10.0 / 0.9
        shortfall = 40.0 - max_charge
        assert result["da_revenue_delivered"] == pytest.approx(-40.0 * 30.0)
        assert result["imbalance_pnl"] == pytest.approx(shortfall * 18.0)  # uses SSP=18.0


class TestForwardGuardrails:
    """required_reserve and available_headroom accumulate over the remaining
    locked DA schedule and are logged before any rule executes."""

    def _unit_asset(self):
        return BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=1.0,
            discharge_efficiency=1.0, degradation_cost_per_mwh=0.0, initial_soc_pct=0.5,
        )

    def test_reserve_and_headroom_accumulate(self):
        result = run_intraday_session(
            da_schedule=[0.0, 30.0, -20.0],
            da_price_actual=[40.0, 40.0, 40.0],
            mid_prices=[40.0, 40.0, 40.0],
            imbalance_prices=[40.0, 40.0, 40.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0},
        )
        log = result["dispatch_log"]

        # h=0 sees a future discharge (30) and charge (-20): reserve must hold the
        # 30 MWh the discharge will draw; headroom is capped at max SOC.
        assert log[0]["required_reserve_mwh"] == pytest.approx(30.0)
        assert log[0]["available_headroom_mwh"] == pytest.approx(100.0)
        # h=1 only sees the future charge (-20): no reserve needed, headroom drops.
        assert log[1]["required_reserve_mwh"] == pytest.approx(0.0)
        assert log[1]["available_headroom_mwh"] == pytest.approx(80.0)
        # h=2 is the last period: reserve floors at min SOC, headroom at max SOC.
        assert log[2]["required_reserve_mwh"] == pytest.approx(0.0)
        assert log[2]["available_headroom_mwh"] == pytest.approx(100.0)

    def test_reserve_floors_and_headroom_clamps(self):
        # A large future charge (-50) would push reserve below min SOC; it clamps
        # to 0, while the future discharge keeps headroom from exceeding max SOC.
        result = run_intraday_session(
            da_schedule=[0.0, -50.0, 30.0],
            da_price_actual=[40.0, 40.0, 40.0],
            mid_prices=[40.0, 40.0, 40.0],
            imbalance_prices=[40.0, 40.0, 40.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0},
        )
        log = result["dispatch_log"]
        assert log[0]["required_reserve_mwh"] == pytest.approx(0.0)
        assert log[0]["available_headroom_mwh"] == pytest.approx(50.0)


class TestFindBottleneckIndex:
    def test_ceiling_reached_mid_schedule(self):
        # Two charges lift SOC; the ceiling is breached on the second period.
        offset = _find_bottleneck_index(
            start_soc_mwh=50.0, future_schedule=[-20.0, -40.0],
            charge_efficiency=1.0, discharge_efficiency=1.0,
            bound_mwh=100.0, duration_h=1.0, hitting_ceiling=True,
        )
        assert offset == 1

    def test_floor_reached_mid_schedule(self):
        offset = _find_bottleneck_index(
            start_soc_mwh=50.0, future_schedule=[30.0, 30.0],
            charge_efficiency=1.0, discharge_efficiency=1.0,
            bound_mwh=0.0, duration_h=1.0, hitting_ceiling=False,
        )
        assert offset == 1

    def test_bound_reached_immediately(self):
        offset = _find_bottleneck_index(
            start_soc_mwh=90.0, future_schedule=[-20.0],
            charge_efficiency=1.0, discharge_efficiency=1.0,
            bound_mwh=100.0, duration_h=1.0, hitting_ceiling=True,
        )
        assert offset == 0

    def test_bound_never_reached_returns_length(self):
        offset = _find_bottleneck_index(
            start_soc_mwh=50.0, future_schedule=[5.0, 5.0],
            charge_efficiency=1.0, discharge_efficiency=1.0,
            bound_mwh=0.0, duration_h=1.0, hitting_ceiling=False,
        )
        assert offset == 2


class TestFinancialNetting:
    """Rule 2: capture the DA-MID spread financially without moving the battery."""

    def _unit_asset(self):
        return BESSAsset(
            capacity_mwh=100, power_mw=20, charge_efficiency=1.0,
            discharge_efficiency=1.0, degradation_cost_per_mwh=0.0, initial_soc_pct=0.5,
        )

    def test_buyback_when_future_da_beats_mid(self):
        # h=0 would discharge into a 40 price while a future DA period clears 60;
        # MID (45) is below that future price, so the volume is netted at MID.
        result = run_intraday_session(
            da_schedule=[20.0, 10.0],
            da_price_actual=[40.0, 60.0],
            mid_prices=[45.0, 55.0],
            imbalance_prices=[40.0, 60.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0},
        )

        assert result["dispatch_log"][0]["trade_type"] == "financial_buyback"
        assert result["dispatch_log"][0]["netted_mwh"] == pytest.approx(20.0)
        assert result["financial_netting_pnl"] == pytest.approx(-20.0 * 45.0)
        assert result["physical_dispatch_pnl"] == pytest.approx(0.0)
        assert result["intraday_pnl"] == pytest.approx(-900.0)
        assert result["cycles_saved_mwh"] == pytest.approx(20.0)
        # The netted leg sells the DA volume at its DA price and buys it back at MID;
        # the captured spread is the DA leg plus the (negative) buyback pnl.
        assert result["da_revenue_netted"] == pytest.approx(20.0 * 40.0)
        assert result["financial_spread_captured"] == pytest.approx(20.0 * 40.0 - 20.0 * 45.0)

    def test_sellback_when_future_da_below_mid(self):
        # h=0 would charge against a 60 price while a future DA period sits at 40;
        # MID (55) beats that future price, so the charge is netted at MID.
        result = run_intraday_session(
            da_schedule=[-20.0, -10.0],
            da_price_actual=[60.0, 40.0],
            mid_prices=[55.0, 45.0],
            imbalance_prices=[60.0, 40.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0},
        )

        assert result["dispatch_log"][0]["trade_type"] == "financial_sellback"
        assert result["dispatch_log"][0]["netted_mwh"] == pytest.approx(20.0)
        assert result["financial_netting_pnl"] == pytest.approx(20.0 * 55.0)
        assert result["cycles_saved_mwh"] == pytest.approx(20.0)
        # The netted charge leg is a DA cost (negative) bought back by selling at MID.
        assert result["da_revenue_netted"] == pytest.approx(-20.0 * 60.0)
        assert result["financial_spread_captured"] == pytest.approx(-20.0 * 60.0 + 20.0 * 55.0)

    def test_no_netting_when_mid_above_future_da(self):
        # MID (70) exceeds the best future DA price (60): there is no spread to
        # capture, so the volume is dispatched physically.
        result = run_intraday_session(
            da_schedule=[20.0, 10.0],
            da_price_actual=[40.0, 60.0],
            mid_prices=[70.0, 55.0],
            imbalance_prices=[40.0, 60.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0},
        )

        assert result["dispatch_log"][0]["trade_type"] == "physical_dispatch"
        assert result["financial_netting_pnl"] == pytest.approx(0.0)
        assert result["cycles_saved_mwh"] == pytest.approx(0.0)
        # Nothing was netted, so there is no netted DA revenue or captured spread.
        assert result["da_revenue_netted"] == pytest.approx(0.0)
        assert result["financial_spread_captured"] == pytest.approx(0.0)

    def test_margin_buy_blocks_marginal_netting(self):
        # MID (55) clears the future DA (60) by only 5; a larger margin_buy of 10
        # raises the hurdle above the spread, so netting is suppressed.
        result = run_intraday_session(
            da_schedule=[20.0, 10.0],
            da_price_actual=[40.0, 60.0],
            mid_prices=[55.0, 55.0],
            imbalance_prices=[40.0, 60.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0, "margin_buy": 10.0},
        )

        assert result["dispatch_log"][0]["trade_type"] == "physical_dispatch"
        assert result["financial_netting_pnl"] == pytest.approx(0.0)


class TestGuardrailsPreventImbalance:
    """A strictly-feasible DA schedule must settle with zero imbalance with every
    intraday rule firing — Rule 2 netting and Rule 4 spread both stay within
    R_h/H_h, so no rule can leave an uncovered shortfall that spills to imbalance."""

    def test_all_rules_yield_zero_imbalance(self):
        import random

        from src.bess.da_optimizer import optimize_da_schedule

        random.seed(7)
        worst = 0.0
        for _ in range(200):
            asset = BESSAsset(
                capacity_mwh=20.0, power_mw=10.0,
                charge_efficiency=0.92, discharge_efficiency=0.92,
                degradation_cost_per_mwh=2.0,
                initial_soc_pct=random.uniform(0.1, 0.9),
                min_soc_pct=0.05, max_soc_pct=0.95,
            )
            fc = [random.uniform(-50, 200) for _ in range(24)]
            sched = optimize_da_schedule(fc, asset, duration_h=1.0)
            asset.reset()
            mid = [f + random.uniform(-60, 60) for f in fc]
            result = run_intraday_session(
                da_schedule=sched, da_price_actual=fc, mid_prices=mid,
                imbalance_prices=[abs(f) + 20 for f in fc], asset=asset,
                config={
                    "degradation_cost_per_mwh": 2.0, "resolution_h": 1.0,
                    "margin_buy": 2.0, "margin_sell": 2.0,
                },
                imbalance_sell_prices=[f - 10 for f in fc],
            )
            worst = max(worst, abs(result["imbalance_pnl"]))
        assert worst < 1e-6, f"feasible schedule leaked imbalance: {worst}"
