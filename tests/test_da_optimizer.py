from unittest.mock import patch

import pulp
import pytest

from src.bess.bess_asset import BESSAsset
from src.bess.da_optimizer import optimize_da_schedule


@pytest.fixture
def battery() -> BESSAsset:
    return BESSAsset(
        capacity_mwh=100.0,
        power_mw=50.0,
        charge_efficiency=0.9,
        discharge_efficiency=0.95,
        degradation_cost_per_mwh=0.50,
        initial_soc_pct=0.5,
    )


class TestDAOptimizer:
    def test_returns_24_elements(self, battery: BESSAsset) -> None:
        prices = [40.0] * 24
        schedule = optimize_da_schedule(prices, battery)
        assert len(schedule) == 24

    def test_charges_low_discharges_high(self, battery: BESSAsset) -> None:
        prices = [20.0] * 12 + [80.0] * 12
        schedule = optimize_da_schedule(prices, battery)

        low_period = schedule[:12]
        high_period = schedule[12:]

        assert sum(low_period) < 0, "Should net charge during low-price hours"
        assert sum(high_period) > 0, "Should net discharge during high-price hours"

    def test_respects_power_limit(self, battery: BESSAsset) -> None:
        prices = [0.0] * 12 + [100.0] * 12
        schedule = optimize_da_schedule(prices, battery)

        for mw in schedule:
            assert abs(mw) <= battery.power_mw + 1e-6

    def test_respects_soc_bounds(self, battery: BESSAsset) -> None:
        prices = [0.0] * 12 + [100.0] * 12
        schedule = optimize_da_schedule(prices, battery)

        soc = battery.capacity_mwh * battery.initial_soc_pct
        for h in range(24):
            dispatch = schedule[h]
            if dispatch > 0:
                soc -= dispatch / battery.discharge_efficiency
            else:
                soc += (-dispatch) * battery.charge_efficiency
            assert soc >= -1e-6, f"SOC went negative at hour {h}"
            assert soc <= battery.capacity_mwh + 1e-6, f"SOC exceeded capacity at hour {h}"

    def test_flat_prices_no_trade(self) -> None:
        empty_battery = BESSAsset(
            capacity_mwh=100.0,
            power_mw=50.0,
            charge_efficiency=0.9,
            discharge_efficiency=0.95,
            degradation_cost_per_mwh=0.50,
            initial_soc_pct=0.0,
        )
        prices = [50.0] * 24
        schedule = optimize_da_schedule(prices, empty_battery)

        total_activity = sum(abs(mw) for mw in schedule)
        assert total_activity < 1e-6, "No trade expected with flat prices and empty battery"

    def test_degradation_cost_prevents_unprofitable_trade(self) -> None:
        prices = [30.0] * 12 + [60.0] * 12

        asset_no_deg = BESSAsset(
            capacity_mwh=100.0,
            power_mw=50.0,
            charge_efficiency=0.9,
            discharge_efficiency=0.95,
            degradation_cost_per_mwh=0.0,
            initial_soc_pct=0.5,
        )
        schedule_no_deg = optimize_da_schedule(prices, asset_no_deg)
        activity_no_deg = sum(abs(mw) for mw in schedule_no_deg)
        assert activity_no_deg > 1e-6, "Trade expected when spread covers efficiency loss"

        asset_with_deg = BESSAsset(
            capacity_mwh=100.0,
            power_mw=50.0,
            charge_efficiency=0.9,
            discharge_efficiency=0.95,
            degradation_cost_per_mwh=15.0,
            initial_soc_pct=0.5,
        )
        schedule_with_deg = optimize_da_schedule(prices, asset_with_deg)
        activity_with_deg = sum(abs(mw) for mw in schedule_with_deg)
        assert activity_with_deg < 1e-6, "No trade expected when degradation cost eliminates profit"

    def test_revenue_is_positive(self, battery: BESSAsset) -> None:
        prices = [10.0] * 12 + [90.0] * 12
        schedule = optimize_da_schedule(prices, battery)

        revenue = sum(schedule[h] * prices[h] for h in range(24))
        assert revenue > 0, "Optimizer should generate positive revenue"

    def test_terminal_soc_is_not_less_than_initial(self, battery: BESSAsset) -> None:
        prices = [10.0] * 12 + [90.0] * 12
        schedule = optimize_da_schedule(prices, battery)

        soc = battery.capacity_mwh * battery.initial_soc_pct
        for dispatch in schedule:
            if dispatch > 0:
                soc -= dispatch / battery.discharge_efficiency
            else:
                soc += (-dispatch) * battery.charge_efficiency

        initial_soc = battery.capacity_mwh * battery.initial_soc_pct
        assert soc >= initial_soc - 1e-6, (
            f"Final SOC {soc:.4f} must not be less than initial SOC {initial_soc:.4f}"
        )

    def test_solver_failure_returns_zero_dispatch(self, battery: BESSAsset) -> None:
        prices = [40.0] * 24
        with patch("pulp.LpProblem.solve", side_effect=pulp.PulpSolverError("solver crashed")):
            schedule = optimize_da_schedule(prices, battery)

        assert schedule == [0.0] * 24

    def test_negative_prices_trigger_charging(self, battery: BESSAsset) -> None:
        prices = [-20.0] * 12 + [80.0] * 12
        schedule = optimize_da_schedule(prices, battery)

        neg_period = schedule[:12]
        pos_period = schedule[12:]

        assert sum(neg_period) < 0, "Should net charge during negative-price hours"
        assert sum(pos_period) > 0, "Should net discharge during positive-price hours"

        revenue = sum(schedule[h] * prices[h] for h in range(24))
        assert revenue > 0, "Revenue must be positive when buying at negative and selling at positive prices"

    def test_all_negative_prices_charges_only(self, battery: BESSAsset) -> None:
        prices = [-50.0] * 12 + [-10.0] * 12
        schedule = optimize_da_schedule(prices, battery)

        total_activity = sum(abs(mw) for mw in schedule)
        assert total_activity > 1e-6, "Should trade when prices are negative"

        net_dispatch = sum(schedule)
        assert net_dispatch < 0, "Should net charge when all prices are negative (paid to consume)"

    def test_terminal_soc_equals_initial(self, battery: BESSAsset) -> None:
        prices = [15.0, 85.0, 20.0, 90.0, 10.0, 80.0] * 4
        schedule = optimize_da_schedule(prices, battery)

        total_activity = sum(abs(mw) for mw in schedule)
        assert total_activity > 1.0, "Volatile prices should trigger trading"

        soc = battery.capacity_mwh * battery.initial_soc_pct
        for dispatch in schedule:
            if dispatch > 0:
                soc -= dispatch / battery.discharge_efficiency
            else:
                soc += (-dispatch) * battery.charge_efficiency

        initial_soc = battery.capacity_mwh * battery.initial_soc_pct
        assert soc == pytest.approx(initial_soc, abs=1e-3)
