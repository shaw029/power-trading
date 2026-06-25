import pytest

from src.bess.bess_asset import BESSAsset
from src.bess.da_optimizer import optimize_da_schedule
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


def _unit_asset(soc=0.5, power=50.0, deg=0.0):
    """Lossless 100 MWh / `power` MW battery for arithmetic-clean LP checks."""
    return BESSAsset(
        capacity_mwh=100,
        power_mw=power,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        degradation_cost_per_mwh=deg,
        initial_soc_pct=soc,
        min_soc_pct=0.0,
        max_soc_pct=1.0,
    )


class TestBenchmarkUnchanged:
    """When the locked DA plan is already optimal on the realised prices, the
    re-optimisation has nothing to improve: it returns the same schedule, so the
    improvement bucket is ~zero and the benchmark settles at the actual prices."""

    def test_flat_prices_no_deviation(self):
        # A whiff of degradation makes any flat-price cycle strictly unprofitable,
        # so the re-optimisation stays put (no degenerate zero-profit churn).
        result = run_intraday_session(
            da_schedule=[0.0, 0.0, 0.0],
            da_price_actual=[40.0, 40.0, 40.0],
            mid_prices=[40.0, 40.0, 40.0],
            asset=_unit_asset(soc=0.0, deg=1.0),
            config={"degradation_cost_per_mwh": 1.0},
        )
        assert result["intraday_da_improvement"] == pytest.approx(0.0, abs=1e-6)
        assert result["execution_costs_paid"] == pytest.approx(0.0, abs=1e-6)
        assert result["net_pnl"] == pytest.approx(0.0, abs=1e-6)
        assert all(e["intraday_mw"] == pytest.approx(0.0, abs=1e-6) for e in result["dispatch_log"])

    def test_da_optimal_plan_is_left_alone(self):
        asset = _unit_asset(soc=0.5, deg=2.0)
        prices = [30.0, 80.0, 20.0, 90.0]
        schedule = optimize_da_schedule(prices, asset, duration_h=1.0)
        asset.reset()
        result = run_intraday_session(
            da_schedule=schedule,
            da_price_actual=prices,
            mid_prices=prices,
            asset=asset,
            config={"degradation_cost_per_mwh": 2.0},
        )
        # The DA LP already optimised against these very prices, so re-optimising
        # against them (margins/exec zero) cannot beat it — no deviation.
        assert result["intraday_da_improvement"] == pytest.approx(0.0, abs=1e-6)
        assert result["benchmark_da_revenue"] == pytest.approx(
            sum(s * p for s, p in zip(schedule, prices))
        )


class TestReoptimizationCapturesSpread:
    """When realised prices reward a trade the benchmark didn't take, the LP
    deviates: buy low, sell high. The decision is made on the DA proxy; the trade
    is then settled at the real MID."""

    def test_buy_low_sell_high(self):
        # Empty battery, benchmark idle: charge cheap (h0 £10) to discharge dear (h1 £100).
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[10.0, 100.0],
            mid_prices=[10.0, 100.0],
            asset=_unit_asset(soc=0.0),
            config={"degradation_cost_per_mwh": 0.0, "execution": {"slippage": 0.0}},
        )
        log = result["dispatch_log"]
        assert log[0]["final_mw"] == pytest.approx(-50.0)  # charge 50 MW
        assert log[1]["final_mw"] == pytest.approx(50.0)  # discharge 50 MW
        # bought 50 MWh @10, sold 50 MWh @100 (MID == DA here)
        assert result["intraday_da_improvement"] == pytest.approx(50 * 100 - 50 * 10)
        assert result["accumulated_intraday_throughput_mwh"] == pytest.approx(100.0)
        assert result["net_pnl"] == pytest.approx(4500.0)

    def test_settles_at_real_mid_not_proxy(self):
        # Decision uses the DA proxy (10 / 100) → still charge h0, discharge h1.
        # But the real MID at h1 turns out to be 80, so the sale settles at 80, not
        # the proxy's 100: improvement = -50*10 + 50*80 = 3500.
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[10.0, 100.0],
            mid_prices=[10.0, 80.0],
            asset=_unit_asset(soc=0.0),
            config={"degradation_cost_per_mwh": 0.0, "execution": {"slippage": 0.0}},
        )
        log = result["dispatch_log"]
        assert log[0]["final_mw"] == pytest.approx(-50.0)
        assert log[1]["final_mw"] == pytest.approx(50.0)
        assert result["intraday_da_improvement"] == pytest.approx(50 * 80 - 50 * 10)
        assert result["net_pnl"] == pytest.approx(3500.0)

    def test_execution_cost_charged_on_deviation(self):
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[10.0, 100.0],
            mid_prices=[10.0, 100.0],
            asset=_unit_asset(soc=0.0),
            config={"degradation_cost_per_mwh": 0.0, "execution": {"slippage": 1.0}},
        )
        # 100 MWh traded (50 buy + 50 sell) at £1/MWh slippage.
        assert result["execution_costs_paid"] == pytest.approx(100.0)
        assert result["net_pnl"] == pytest.approx(4500.0 - 100.0)


class TestHurdlesBlockMarginalTrades:
    """In the default (rolling, no-lookahead) engine a deviation must clear three
    frictions to be worth taking: the DA-proxy basis on the not-yet-visible future
    leg, the execution buffer on both legs, and the battery wear."""

    def test_future_hurdle_blocks_thin_spread(self):
        # Charging now (observed MID 40) to sell into the future is only worth it
        # if the future proxy sell price beats 40. A 10 basis pulls the future
        # sell proxy to 45-10=35 < 40, so the arb never clears → no deviation.
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[40.0, 45.0],
            mid_prices=[40.0, 45.0],
            asset=_unit_asset(soc=0.0),
            config={"degradation_cost_per_mwh": 0.0, "margin_buy": 10.0, "margin_sell": 10.0},
        )
        assert result["intraday_da_improvement"] == pytest.approx(0.0, abs=1e-6)
        assert all(e["intraday_mw"] == pytest.approx(0.0, abs=1e-6) for e in result["dispatch_log"])

    def test_execution_buffer_blocks_thin_spread(self):
        # The 40 -> 45 spread is real, but slippage is charged on both legs:
        # buying 50 then selling 50 costs (50+50)*3 = 300 of friction against a
        # 250 gross gain, so the LP leaves the DA plan alone.
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[40.0, 45.0],
            mid_prices=[40.0, 45.0],
            asset=_unit_asset(soc=0.0),
            config={"degradation_cost_per_mwh": 0.0, "execution": {"slippage": 3.0}},
        )
        assert result["intraday_da_improvement"] == pytest.approx(0.0, abs=1e-6)
        assert all(e["intraday_mw"] == pytest.approx(0.0, abs=1e-6) for e in result["dispatch_log"])

    def test_degradation_blocks_thin_spread(self):
        # Round-trip wear 3+3=6 > spread 5 → idle.
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[40.0, 45.0],
            mid_prices=[40.0, 45.0],
            asset=_unit_asset(soc=0.0, deg=3.0),
            config={"degradation_cost_per_mwh": 3.0},
        )
        assert result["intraday_da_improvement"] == pytest.approx(0.0, abs=1e-6)

    def test_thin_spread_trades_when_wear_low(self):
        # Round-trip wear 1+1=2 < spread 5 → the LP takes the arb.
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[40.0, 45.0],
            mid_prices=[40.0, 45.0],
            asset=_unit_asset(soc=0.0, deg=1.0),
            config={"degradation_cost_per_mwh": 1.0},
        )
        assert result["dispatch_log"][1]["final_mw"] > 0
        assert result["intraday_da_improvement"] > 0


class TestCycleCap:
    """target_daily_cycles caps total discharge throughput of the re-optimised
    physical schedule."""

    def test_cap_limits_discharge(self):
        asset = _unit_asset(soc=1.0, power=10.0)
        result = run_intraday_session(
            da_schedule=[0.0, 0.0, 0.0, 0.0],
            # Each period is a strong sell vs the next; uncapped the LP would
            # discharge 10 MW every period (40 MWh). Cap = 0.25*100 = 25 MWh.
            da_price_actual=[100.0, 80.0, 60.0, 40.0],
            mid_prices=[100.0, 80.0, 60.0, 40.0],
            asset=asset,
            config={"degradation_cost_per_mwh": 0.0, "target_daily_cycles": 0.25},
        )
        total_discharge_mwh = sum(
            e["final_mw"] for e in result["dispatch_log"] if e["final_mw"] > 0
        )
        assert total_discharge_mwh <= 25.0 + 1e-6


class TestLedgerReconciles:
    def test_buckets_sum_to_net(self):
        asset = _unit_asset(soc=0.5, deg=2.0)
        prices = [30.0, 80.0, 20.0, 90.0, 50.0]
        mid = [33.0, 76.0, 25.0, 95.0, 48.0]
        schedule = optimize_da_schedule(prices, asset, duration_h=1.0)
        asset.reset()
        result = run_intraday_session(
            da_schedule=schedule,
            da_price_actual=prices,
            mid_prices=mid,
            asset=asset,
            config={"degradation_cost_per_mwh": 2.0, "margin_buy": 1.0, "margin_sell": 1.0},
        )
        recomputed = (
            result["benchmark_da_revenue"]
            + result["intraday_da_improvement"]
            - result["execution_costs_paid"]
            - result["total_degradation_cost"]
        )
        assert recomputed == pytest.approx(result["net_pnl"])


class TestHalfHourlyResolution:
    def test_half_hourly_session(self):
        result = run_intraday_session(
            da_schedule=[0.0, 0.0],
            da_price_actual=[10.0, 100.0],
            mid_prices=[10.0, 100.0],
            asset=_unit_asset(soc=0.0, power=10.0),
            config={"degradation_cost_per_mwh": 0.0, "resolution_h": 0.5},
        )
        # power 10 MW over 0.5 h = 5 MWh per period.
        assert result["dispatch_log"][0]["final_mw"] == pytest.approx(-10.0)
        assert result["dispatch_log"][1]["final_mw"] == pytest.approx(10.0)
        assert result["intraday_da_improvement"] == pytest.approx(5 * 100 - 5 * 10)


class TestLedgerReconcilesOverRandomDays:
    """The LP keeps the physical schedule inside the SOC/power envelope, so a
    re-optimised day always reconciles: the ledger buckets sum to net PnL."""

    def test_buckets_reconcile_over_random_days(self):
        import random

        random.seed(7)
        worst = 0.0
        for _ in range(100):
            asset = BESSAsset(
                capacity_mwh=20.0,
                power_mw=10.0,
                charge_efficiency=0.92,
                discharge_efficiency=0.92,
                degradation_cost_per_mwh=2.0,
                initial_soc_pct=random.uniform(0.1, 0.9),
                min_soc_pct=0.05,
                max_soc_pct=0.95,
            )
            fc = [random.uniform(-50, 200) for _ in range(24)]
            mid = [f + random.uniform(-30, 30) for f in fc]
            sched = optimize_da_schedule(fc, asset, duration_h=1.0)
            asset.reset()
            result = run_intraday_session(
                da_schedule=sched,
                da_price_actual=fc,
                mid_prices=mid,
                asset=asset,
                config={
                    "degradation_cost_per_mwh": 2.0,
                    "resolution_h": 1.0,
                    "margin_buy": 1.0,
                    "margin_sell": 1.0,
                },
            )
            recomputed = (
                result["benchmark_da_revenue"]
                + result["intraday_da_improvement"]
                - result["execution_costs_paid"]
                - result["total_degradation_cost"]
            )
            worst = max(worst, abs(recomputed - result["net_pnl"]))
        assert worst < 1e-6, f"ledger failed to reconcile: {worst}"


class TestPerfectForesightMode:
    """The live benchmark opts into ``perfect_foresight=True``: a single LP over
    the realised MID curve. Because following the DA plan is always feasible, it
    can never do worse than the benchmark — and being the global optimum, never
    worse than the rolling heuristic."""

    def test_never_worse_than_da_plan(self):
        import random

        random.seed(11)
        for _ in range(50):
            asset = BESSAsset(
                capacity_mwh=20.0,
                power_mw=10.0,
                charge_efficiency=0.92,
                discharge_efficiency=0.92,
                degradation_cost_per_mwh=2.0,
                initial_soc_pct=random.uniform(0.1, 0.9),
                min_soc_pct=0.05,
                max_soc_pct=0.95,
            )
            da = [random.uniform(-50, 200) for _ in range(24)]
            mid = [f + random.uniform(-40, 80) for f in da]
            sched = optimize_da_schedule(da, asset, duration_h=1.0)
            asset.reset()
            result = run_intraday_session(
                da_schedule=sched,
                da_price_actual=da,
                mid_prices=mid,
                asset=asset,
                config={"degradation_cost_per_mwh": 2.0, "resolution_h": 1.0},
                perfect_foresight=True,
            )
            # Following the DA plan (zero deviation) is feasible, so net is bounded
            # below by it. The tolerance only absorbs LP/clamp rounding.
            follow_da_net = result["benchmark_da_revenue"] - sum(abs(s) for s in sched) * 2.0
            assert result["net_pnl"] >= follow_da_net - (1e-3 * abs(follow_da_net) + 1.0)

    def test_delivers_committed_discharge_into_a_late_spike(self):
        # DA commits a discharge at the final, highest-price hour. A tempting but
        # lower MID earlier would lure the rolling engine into discharging early
        # and being unable to deliver the committed hour; perfect foresight holds
        # the energy and delivers it. Start full so there is energy to misallocate.
        asset = _unit_asset(soc=0.95)
        da_schedule = [0.0, 0.0, 50.0]  # DA discharge committed in the last hour
        da_price_actual = [50.0, 50.0, 60.0]
        mid_prices = [80.0, 40.0, 200.0]  # early lure (80), then a late spike (200)
        result = run_intraday_session(
            da_schedule=da_schedule,
            da_price_actual=da_price_actual,
            mid_prices=mid_prices,
            asset=asset,
            config={"degradation_cost_per_mwh": 0.0, "resolution_h": 1.0},
            perfect_foresight=True,
        )
        # The committed discharge is delivered at the spike, not bought back.
        assert result["dispatch_log"][2]["final_mw"] > 0
        assert result["intraday_da_improvement"] >= -1e-6
