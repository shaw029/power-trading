import pytest

from src.bess.bess_asset import BESSAsset
from src.bess.intraday_manager import _compute_implied_soc, run_intraday_session


class TestComputeImpliedSocClamping:
    def test_soc_clamped_above_capacity(self):
        soc = _compute_implied_soc(
            da_schedule=[-200.0, -200.0],
            initial_soc_mwh=80.0,
            charge_efficiency=0.9,
            discharge_efficiency=0.95,
            capacity_mwh=100.0,
        )
        assert all(s <= 100.0 for s in soc)
        assert soc[-1] == pytest.approx(100.0)

    def test_soc_clamped_below_zero(self):
        soc = _compute_implied_soc(
            da_schedule=[200.0, 200.0],
            initial_soc_mwh=20.0,
            charge_efficiency=0.9,
            discharge_efficiency=0.95,
            capacity_mwh=100.0,
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

        assert result["da_revenue"] == pytest.approx(200.0)
        assert result["intraday_pnl"] == pytest.approx(0.0)
        assert result["imbalance_pnl"] == pytest.approx(0.0)
        assert result["total_degradation_cost"] == pytest.approx(100.0)
        assert result["net_pnl"] == pytest.approx(100.0)
        assert len(result["dispatch_log"]) == 3
        assert result["dispatch_log"][0]["action"] == "discharge"
        assert result["dispatch_log"][1]["action"] == "charge"
        assert result["dispatch_log"][2]["action"] == "idle"


class TestSOCDrift:
    def test_drift_triggers_charge_rebalance(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=20, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=1.0, initial_soc_pct=0.5,
        )
        result = run_intraday_session(
            da_schedule=[-30.0],
            da_price_actual=[40.0],
            mid_prices=[42.0],
            imbalance_prices=[38.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 5.0},
        )

        assert result["intraday_pnl"] == pytest.approx(-9.0 * 42.0)
        assert result["imbalance_pnl"] == pytest.approx(10.0 * 38.0)

    def test_large_drift_tolerance_suppresses_rebalance(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=20, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=1.0, initial_soc_pct=0.5,
        )
        result = run_intraday_session(
            da_schedule=[-30.0],
            da_price_actual=[40.0],
            mid_prices=[42.0],
            imbalance_prices=[38.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 5.0, "soc_drift_tolerance": 0.5},
        )

        assert result["intraday_pnl"] == pytest.approx(0.0)

    def test_small_drift_tolerance_triggers_rebalance(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=20, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=1.0, initial_soc_pct=0.5,
        )
        result = run_intraday_session(
            da_schedule=[-30.0],
            da_price_actual=[40.0],
            mid_prices=[42.0],
            imbalance_prices=[38.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 5.0, "soc_drift_tolerance": 0.01},
        )

        assert result["intraday_pnl"] == pytest.approx(-9.0 * 42.0)


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

        assert result["da_revenue"] == pytest.approx(46.0 * 40.0)
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
        assert result["da_revenue"] == pytest.approx(30.0 * 50.0)
        assert result["imbalance_pnl"] == pytest.approx(-shortfall * 60.0)
        assert result["dispatch_log"][0]["mw"] == pytest.approx(max_mw)

    def test_charge_shortfall_settles_at_imbalance(self):
        asset = BESSAsset(
            capacity_mwh=100, power_mw=50, charge_efficiency=0.9,
            discharge_efficiency=0.95, degradation_cost_per_mwh=1.0, initial_soc_pct=0.9,
        )
        result = run_intraday_session(
            da_schedule=[-40.0],
            da_price_actual=[30.0],
            mid_prices=[30.0],
            imbalance_prices=[25.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 1.0},
        )

        max_charge = 10.0 / 0.9
        shortfall = 40.0 - max_charge
        assert result["da_revenue"] == pytest.approx(-40.0 * 30.0)
        assert result["imbalance_pnl"] == pytest.approx(shortfall * 25.0)
