import pytest

from src.bess.bess_asset import BESSAsset
from src.bess.intraday_manager import (
    _compute_implied_soc,
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


class TestBaseExecution:
    """Un-netted DA volume dispatches physically when no rule fires. Prices are
    chosen so MID sits inside the no-netting / no-arbitrage window each period.
    On the final period (no future DA position) the opportunity-cost hurdle is a
    neutral deadzone around the current DA price — MID must beat it by more than
    degradation for the opportunity-cost leg to trade — so a flat MID == DA leaves the battery idle."""

    def test_clean_execution(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=5.0, initial_soc_pct=0.5,
        )
        result = run_intraday_session(
            da_schedule=[10.0, -10.0, 0.0],
            da_price_actual=[50.0, 60.0, 40.0],
            mid_prices=[52.0, 50.0, 40.0],   # h0: 50<52<=55; h1: 45<=50<60; h2: ==DA
            imbalance_prices=[48.0, 55.0, 40.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 5.0},
        )

        # h0 discharges 10 MWh and h1 charges 10 MWh as a clean DA dispatch. On
        # the final period the deadzone hurdles are oc_discharge = da_p + deg = 45
        # and oc_charge = da_p - deg = 35, so MID 40 falls inside and the opportunity-cost leg stays
        # idle: no intraday PnL, no extra throughput, degradation only on the DA legs.
        assert result["da_revenue_delivered"] == pytest.approx(10 * 50 - 10 * 60)
        assert result["intraday_pnl"] == pytest.approx(0.0)
        assert result["imbalance_pnl"] == pytest.approx(0.0)
        assert result["accumulated_intraday_throughput_mwh"] == pytest.approx(0.0)
        assert result["total_degradation_cost"] == pytest.approx(5 * (10 + 10))
        assert [e["action"] for e in result["dispatch_log"]] == ["discharge", "charge", "idle"]
        assert [e["trade_type"] for e in result["dispatch_log"]] == [
            "physical_dispatch", "physical_dispatch", "idle",
        ]


class TestForwardGuardrails:
    """R_h = min_soc + sum(future discharge MWh)/discharge_eff;
    H_h = max_soc - sum(future charge MWh)*charge_eff, each clamped to SOC bounds."""

    def _unit_asset(self):
        return BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=1.0,
            discharge_efficiency=1.0, degradation_cost_per_mwh=0.0, initial_soc_pct=0.5,
            min_soc_pct=0.0, max_soc_pct=1.0,
        )

    def test_reserve_and_headroom(self):
        result = run_intraday_session(
            da_schedule=[0.0, 30.0, -20.0],
            da_price_actual=[40.0, 40.0, 40.0],
            mid_prices=[40.0, 40.0, 40.0],
            imbalance_prices=[40.0, 40.0, 40.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0},
        )
        log = result["dispatch_log"]
        # h0 future = [30 (discharge), -20 (charge)]: reserve 30, headroom 100-20.
        assert log[0]["required_reserve_mwh"] == pytest.approx(30.0)
        assert log[0]["available_headroom_mwh"] == pytest.approx(80.0)
        # h1 future = [-20]: no reserve, headroom 80.
        assert log[1]["required_reserve_mwh"] == pytest.approx(0.0)
        assert log[1]["available_headroom_mwh"] == pytest.approx(80.0)
        # h2 last period: reserve floors at min SOC, headroom at max SOC.
        assert log[2]["required_reserve_mwh"] == pytest.approx(0.0)
        assert log[2]["available_headroom_mwh"] == pytest.approx(100.0)

    def test_efficiency_scales_envelope(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.8,
            discharge_efficiency=0.5, degradation_cost_per_mwh=0.0, initial_soc_pct=0.5,
            min_soc_pct=0.0, max_soc_pct=1.0,
        )
        result = run_intraday_session(
            da_schedule=[0.0, 10.0, -10.0],
            da_price_actual=[40.0, 40.0, 40.0],
            mid_prices=[40.0, 40.0, 40.0],
            imbalance_prices=[40.0, 40.0, 40.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 0.0},
        )
        log = result["dispatch_log"]
        # reserve = 0 + 10/0.5 = 20; headroom = 100 - 10*0.8 = 92.
        assert log[0]["required_reserve_mwh"] == pytest.approx(20.0)
        assert log[0]["available_headroom_mwh"] == pytest.approx(92.0)


class TestOpportunityArbitrage:
    """Opportunity-cost arbitrage: physical MID trade when MID beats the best/cheapest reachable
    future DA price net of degradation, clamped to the R_h / H_h envelope."""

    def _unit_asset(self, soc=0.5):
        return BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=1.0,
            discharge_efficiency=1.0, degradation_cost_per_mwh=0.0, initial_soc_pct=soc,
            min_soc_pct=0.0, max_soc_pct=1.0,
        )

    def test_discharge_when_mid_beats_future(self):
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[40.0, 30.0],
            mid_prices=[50.0, 30.0],   # h0: OC_discharge = 30; 50 > 30 → discharge
            imbalance_prices=[40.0, 30.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0},
        )
        entry = result["dispatch_log"][0]
        assert entry["trade_type"] == "opportunity_arb"
        assert entry["spread_mw"] == pytest.approx(50.0)
        assert result["physical_dispatch_pnl"] == pytest.approx(50.0 * 50.0)
        assert result["intraday_pnl"] == pytest.approx(50.0 * 50.0)
        assert result["accumulated_intraday_throughput_mwh"] == pytest.approx(50.0)

    def test_charge_when_mid_below_future(self):
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[40.0, 60.0],
            mid_prices=[30.0, 60.0],   # h0: OC_charge = 60; 30 < 60 → charge
            imbalance_prices=[40.0, 60.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0},
        )
        entry = result["dispatch_log"][0]
        assert entry["trade_type"] == "opportunity_arb"
        assert entry["spread_mw"] == pytest.approx(-50.0)
        assert result["physical_dispatch_pnl"] == pytest.approx(-50.0 * 30.0)
        assert result["accumulated_intraday_throughput_mwh"] == pytest.approx(50.0)

    def test_reserve_clamps_arbitrage_to_protect_future_da(self):
        # h0 idle but a future DA discharge of 30 must be reserved: the MID
        # discharge can only draw SOC down to R_h = 30, i.e. 20 MWh of throughput,
        # leaving the h1 commitment fully serviceable with zero imbalance.
        result = run_intraday_session(
            da_schedule=[0.0, 30.0],
            da_price_actual=[40.0, 20.0],
            mid_prices=[50.0, 25.0],
            imbalance_prices=[40.0, 20.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 0.0},
        )
        assert result["dispatch_log"][0]["spread_mw"] == pytest.approx(20.0)
        assert result["accumulated_intraday_throughput_mwh"] == pytest.approx(20.0)
        assert result["imbalance_pnl"] == pytest.approx(0.0)

    def test_degradation_widens_no_trade_deadzone(self):
        # OC_discharge = max(future) + degradation = 50 + 10 = 60: a standalone
        # intraday cycle must beat the best reachable future price by MORE than the
        # wear it incurs. MID 45 is below the future reference, so it must NOT trade
        # — discharging here would lock in a worse price and still pay degradation.
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[40.0, 50.0],
            mid_prices=[45.0, 50.0],
            imbalance_prices=[40.0, 50.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 10.0},
        )
        assert result["dispatch_log"][0]["trade_type"] != "opportunity_arb"
        assert result["dispatch_log"][0]["spread_mw"] == pytest.approx(0.0)

        # A MID that clears max(future) + degradation (+ the exec buffer) does trade.
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[40.0, 50.0],
            mid_prices=[62.0, 50.0],   # 62 > 50 + 10 + 0.5 → discharge
            imbalance_prices=[40.0, 50.0],
            asset=self._unit_asset(),
            config={"degradation_cost_per_mwh": 10.0},
        )
        assert result["dispatch_log"][0]["trade_type"] == "opportunity_arb"
        assert result["dispatch_log"][0]["spread_mw"] > 0


class TestFinancialNetting:
    """Financial netting: capture the DA-MID spread financially without moving the battery."""

    def test_buyback_when_mid_below_da(self):
        # Final period at full SOC: the buyback nets the discharge, and the OC
        # charge that would otherwise follow is blocked by zero headroom.
        asset = BESSAsset(
            capacity_mwh=100, power_mw=20, charge_efficiency=1.0,
            discharge_efficiency=1.0, degradation_cost_per_mwh=0.0, initial_soc_pct=1.0,
            min_soc_pct=0.0, max_soc_pct=1.0,
        )
        result = run_intraday_session(
            da_schedule=[20.0],
            da_price_actual=[40.0],
            mid_prices=[35.0],
            imbalance_prices=[40.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 0.0},
        )
        entry = result["dispatch_log"][0]
        assert entry["trade_type"] == "financial_netting"
        assert entry["netted_mwh"] == pytest.approx(20.0)
        assert result["financial_netting_pnl"] == pytest.approx(-20.0 * 35.0)
        assert result["da_revenue_netted"] == pytest.approx(20.0 * 40.0)
        assert result["financial_spread_captured"] == pytest.approx(20.0 * (40.0 - 35.0))
        assert result["physical_dispatch_pnl"] == pytest.approx(0.0)
        assert result["cycles_saved_mwh"] == pytest.approx(20.0)
        assert result["accumulated_intraday_throughput_mwh"] == pytest.approx(0.0)

    def test_sellback_when_mid_above_da(self):
        # Final period at empty SOC: the sellback nets the charge, and the OC
        # discharge that would otherwise follow is blocked by zero reserve.
        asset = BESSAsset(
            capacity_mwh=100, power_mw=20, charge_efficiency=1.0,
            discharge_efficiency=1.0, degradation_cost_per_mwh=0.0, initial_soc_pct=0.0,
            min_soc_pct=0.0, max_soc_pct=1.0,
        )
        result = run_intraday_session(
            da_schedule=[-20.0],
            da_price_actual=[40.0],
            mid_prices=[45.0],
            imbalance_prices=[40.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 0.0},
        )
        entry = result["dispatch_log"][0]
        assert entry["trade_type"] == "financial_netting"
        assert result["financial_netting_pnl"] == pytest.approx(20.0 * 45.0)
        assert result["da_revenue_netted"] == pytest.approx(-20.0 * 40.0)
        assert result["financial_spread_captured"] == pytest.approx(20.0 * (45.0 - 40.0))
        assert result["cycles_saved_mwh"] == pytest.approx(20.0)

    def test_no_netting_when_mid_above_da(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=20, charge_efficiency=1.0,
            discharge_efficiency=1.0, degradation_cost_per_mwh=0.0, initial_soc_pct=0.5,
            min_soc_pct=0.0, max_soc_pct=1.0,
        )
        result = run_intraday_session(
            da_schedule=[20.0],
            da_price_actual=[40.0],
            mid_prices=[45.0],
            imbalance_prices=[40.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 0.0},
        )
        assert result["dispatch_log"][0]["trade_type"] == "physical_dispatch"
        assert result["financial_netting_pnl"] == pytest.approx(0.0)
        assert result["cycles_saved_mwh"] == pytest.approx(0.0)

    def test_margin_buy_blocks_marginal_netting(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=20, charge_efficiency=1.0,
            discharge_efficiency=1.0, degradation_cost_per_mwh=0.0, initial_soc_pct=0.5,
            min_soc_pct=0.0, max_soc_pct=1.0,
        )
        result = run_intraday_session(
            da_schedule=[20.0],
            da_price_actual=[40.0],
            mid_prices=[35.0],   # below DA, but inside the 10 buy margin
            imbalance_prices=[40.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 0.0, "margin_buy": 10.0},
        )
        assert result["dispatch_log"][0]["trade_type"] == "physical_dispatch"
        assert result["financial_netting_pnl"] == pytest.approx(0.0)


class TestCycleCap:
    """accumulated_intraday_throughput_mwh tracks physical intraday volume; once it
    reaches target_daily_cycles * capacity the envelope freezes at current SOC."""

    def test_cap_freezes_further_arbitrage(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=10, charge_efficiency=1.0,
            discharge_efficiency=1.0, degradation_cost_per_mwh=0.0, initial_soc_pct=0.5,
            min_soc_pct=0.0, max_soc_pct=1.0,
        )
        result = run_intraday_session(
            da_schedule=[0.0, 0.0, 0.0, 0.0],
            da_price_actual=[40.0, 40.0, 40.0, 40.0],
            mid_prices=[50.0, 50.0, 50.0, 50.0],
            imbalance_prices=[40.0, 40.0, 40.0, 40.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 0.0, "target_daily_cycles": 0.25},
        )
        log = result["dispatch_log"]
        # cap = 0.25 * 100 = 25 MWh; 10 MWh fires each of the first three periods
        # (throughput 10, 20, 30) then the fourth is frozen.
        assert [e["spread_mw"] for e in log] == pytest.approx([10.0, 10.0, 10.0, 0.0])
        assert result["accumulated_intraday_throughput_mwh"] == pytest.approx(30.0)
        # Once frozen the envelope collapses onto the current SOC.
        assert log[3]["required_reserve_mwh"] == pytest.approx(log[3]["soc_before"] * 100)
        assert log[3]["available_headroom_mwh"] == pytest.approx(log[3]["soc_before"] * 100)


class TestImbalanceFallback:
    def test_discharge_shortfall_settles_at_imbalance(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=1.0, initial_soc_pct=0.2,
        )
        result = run_intraday_session(
            da_schedule=[30.0],
            da_price_actual=[50.0],
            mid_prices=[55.0],   # above DA, so no buyback netting
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
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=1.0, initial_soc_pct=0.9,
        )
        result = run_intraday_session(
            da_schedule=[-40.0],
            da_price_actual=[35.0],
            mid_prices=[30.0],             # below DA, so no sellback netting
            imbalance_prices=[25.0],       # SBP
            asset=asset,
            config={"degradation_cost_per_mwh": 1.0},
            imbalance_sell_prices=[18.0],  # SSP — distinct value to confirm it is used
        )
        max_charge = 10.0 / 0.9
        shortfall = 40.0 - max_charge
        assert result["da_revenue_delivered"] == pytest.approx(-40.0 * 35.0)
        assert result["imbalance_pnl"] == pytest.approx(shortfall * 18.0)  # uses SSP=18.0


class TestHalfHourlyResolution:
    def test_half_hourly_session(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=10, charge_efficiency=0.88,
            discharge_efficiency=1.0, degradation_cost_per_mwh=5.0, initial_soc_pct=0.5,
        )
        result = run_intraday_session(
            da_schedule=[10.0, -10.0],
            da_price_actual=[50.0, 30.0],
            mid_prices=[55.0, 25.0],   # no netting; power is fully used by the DA leg
            imbalance_prices=[48.0, 32.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 5.0, "resolution_h": 0.5},
        )
        assert result["da_revenue_delivered"] == pytest.approx(10 * 0.5 * 50 + (-10) * 0.5 * 30)
        assert result["intraday_pnl"] == pytest.approx(0.0)
        assert result["imbalance_pnl"] == pytest.approx(0.0)
        assert result["total_degradation_cost"] == pytest.approx(5.0 * 5.0 + 5.0 * 5.0)
        assert result["dispatch_log"][0]["action"] == "discharge"
        assert result["dispatch_log"][1]["action"] == "charge"
        assert result["dispatch_log"][1]["soc_after"] == pytest.approx(0.494)


class TestGuardrailsPreventImbalance:
    """With netting disabled (huge margins), base DA execution plus the opportunity-cost
    leg must settle a feasible schedule with zero imbalance: that leg always stays inside
    the R_h / H_h envelope, so it can never starve a future DA commitment."""

    def test_arbitrage_never_leaks_imbalance(self):
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
                    "margin_buy": 1e9, "margin_sell": 1e9,
                },
                imbalance_sell_prices=[f - 10 for f in fc],
            )
            worst = max(worst, abs(result["imbalance_pnl"]))
        assert worst < 1e-6, f"feasible schedule leaked imbalance: {worst}"
