import pytest

from src.bess.bess_asset import BESSAsset


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


class TestChargeDischarge:
    def test_charge_updates_soc(self, battery: BESSAsset) -> None:
        battery.charge(mw=50, duration_h=0.5)
        expected = 50.0 + (50 * 0.5 * 0.9)
        assert battery._soc_mwh == pytest.approx(expected)

    def test_discharge_updates_soc(self, battery: BESSAsset) -> None:
        battery.discharge(mw=25, duration_h=1.0)
        expected = 50.0 - 25.0 / 0.95
        assert battery._soc_mwh == pytest.approx(expected)

    def test_charge_then_discharge_round_trip(self, battery: BESSAsset) -> None:
        battery.discharge(mw=47.5, duration_h=1.0)
        assert battery._soc_mwh == pytest.approx(0.0)
        battery.charge(mw=50, duration_h=1.0)
        assert battery._soc_mwh == pytest.approx(45.0)

    def test_soc_pct_property(self, battery: BESSAsset) -> None:
        assert battery.soc_pct == pytest.approx(0.5)
        battery.discharge(mw=25, duration_h=1.0)
        assert battery.soc_pct == pytest.approx((50.0 - 25.0 / 0.95) / 100.0)


class TestSplitEfficiency:
    def test_charge_efficiency_applied_on_charge(self, battery: BESSAsset) -> None:
        battery.charge(mw=10, duration_h=1.0)
        assert battery._soc_mwh == pytest.approx(50.0 + 9.0)

    def test_discharge_efficiency_applied_on_discharge(self, battery: BESSAsset) -> None:
        battery.discharge(mw=10, duration_h=1.0)
        assert battery._soc_mwh == pytest.approx(50.0 - 10.0 / 0.95)

    def test_charge_with_88_pct_efficiency(self) -> None:
        asset = BESSAsset(
            capacity_mwh=100.0,
            power_mw=50.0,
            charge_efficiency=0.88,
            discharge_efficiency=1.0,
            degradation_cost_per_mwh=0.50,
            initial_soc_pct=0.5,
        )
        asset.charge(mw=10, duration_h=1.0)
        assert asset._soc_mwh == pytest.approx(50.0 + 8.8)


class TestLimitEnforcement:
    def test_charge_exceeds_power_limit(self, battery: BESSAsset) -> None:
        with pytest.raises(ValueError, match="exceeds limit"):
            battery.charge(mw=51, duration_h=1.0)

    def test_discharge_exceeds_power_limit(self, battery: BESSAsset) -> None:
        with pytest.raises(ValueError, match="exceeds limit"):
            battery.discharge(mw=51, duration_h=1.0)

    def test_charge_exceeds_capacity(self, battery: BESSAsset) -> None:
        with pytest.raises(ValueError, match="exceed max SOC"):
            battery.charge(mw=50, duration_h=2.0)

    def test_discharge_below_zero(self, battery: BESSAsset) -> None:
        with pytest.raises(ValueError, match="breach min SOC"):
            battery.discharge(mw=50, duration_h=1.5)

    def test_charge_at_exact_power_limit(self, battery: BESSAsset) -> None:
        battery.charge(mw=50, duration_h=0.5)
        assert battery._soc_mwh == pytest.approx(50.0 + 25.0 * 0.9)

    def test_float_tolerance_near_full_and_empty(self, battery: BESSAsset) -> None:
        battery._soc_mwh = battery.capacity_mwh - 4e-11
        battery.charge(mw=1e-10, duration_h=1.0)
        assert battery._soc_mwh == battery.capacity_mwh

        battery.reset()

        battery._soc_mwh = 4e-11
        battery.discharge(mw=1e-10, duration_h=1.0)
        assert battery._soc_mwh == 0.0


class TestDegradation:
    def test_charge_accumulates_degradation(self, battery: BESSAsset) -> None:
        battery.charge(mw=10, duration_h=1.0)
        assert battery.degradation_cost == pytest.approx(10.0 * 0.50)

    def test_discharge_accumulates_degradation(self, battery: BESSAsset) -> None:
        battery.discharge(mw=10, duration_h=1.0)
        assert battery.degradation_cost == pytest.approx(10.0 * 0.50)

    def test_multiple_ops_accumulate(self, battery: BESSAsset) -> None:
        battery.charge(mw=10, duration_h=1.0)
        battery.discharge(mw=10, duration_h=1.0)
        assert battery.degradation_cost == pytest.approx(10.0 * 0.50 + 10.0 * 0.50)


class TestCanChargeDischarge:
    def test_can_charge_within_limits(self, battery: BESSAsset) -> None:
        assert battery.can_charge(mw=50, duration_h=0.5) is True

    def test_can_charge_over_power(self, battery: BESSAsset) -> None:
        assert battery.can_charge(mw=51, duration_h=0.5) is False

    def test_can_charge_over_capacity(self, battery: BESSAsset) -> None:
        assert battery.can_charge(mw=50, duration_h=2.0) is False

    def test_can_discharge_within_limits(self, battery: BESSAsset) -> None:
        assert battery.can_discharge(mw=40, duration_h=1.0) is True

    def test_can_discharge_over_power(self, battery: BESSAsset) -> None:
        assert battery.can_discharge(mw=51, duration_h=1.0) is False

    def test_can_discharge_below_zero(self, battery: BESSAsset) -> None:
        assert battery.can_discharge(mw=50, duration_h=1.5) is False


class TestReset:
    def test_reset_restores_soc(self, battery: BESSAsset) -> None:
        battery.charge(mw=10, duration_h=1.0)
        battery.reset()
        assert battery.soc_pct == pytest.approx(0.5)

    def test_reset_clears_degradation(self, battery: BESSAsset) -> None:
        battery.charge(mw=10, duration_h=1.0)
        battery.reset()
        assert battery.degradation_cost == pytest.approx(0.0)
