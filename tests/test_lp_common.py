"""Tests for src/bess/lp_common.py — the physics guard on the LP relaxation."""

import pulp
import pytest

from src.bess.bess_asset import BESSAsset
from src.bess.da_optimizer import optimize_da_schedule
from src.bess.lp_common import add_mutual_exclusion, net_dispatch, solve, validate_schedule


def _asset(**kw):
    base = dict(
        capacity_mwh=100.0,
        power_mw=50.0,
        charge_efficiency=0.94,
        discharge_efficiency=0.94,
        degradation_cost_per_mwh=5.0,
        initial_soc_pct=0.50,
        min_soc_pct=0.10,
        max_soc_pct=0.90,
    )
    base.update(kw)
    return BESSAsset(**base)


class TestSolve:
    def test_names_the_outcome(self):
        prob = pulp.LpProblem("t", pulp.LpMaximize)
        x = prob.add_variable("x", lowBound=0, upBound=1)
        prob += x
        assert solve(prob) == "Optimal"

    def test_missing_highs_raises_instead_of_idling(self, monkeypatch):
        monkeypatch.setattr(pulp.HiGHS, "available", lambda self: False)
        with pytest.raises(RuntimeError, match="highspy"):
            solve(pulp.LpProblem("t", pulp.LpMaximize))


class TestNetDispatch:
    def test_discharge_minus_charge(self):
        prob = pulp.LpProblem("t", pulp.LpMaximize)
        d = [prob.add_variable(f"d{h}", lowBound=v, upBound=v) for h, v in enumerate([5, 0])]
        c = [prob.add_variable(f"c{h}", lowBound=v, upBound=v) for h, v in enumerate([0, 3])]
        prob += pulp.lpSum(d + c)
        assert solve(prob) == "Optimal"
        assert net_dispatch(d, c) == pytest.approx([5.0, -3.0])

    def test_an_unsolved_variable_raises_rather_than_reading_as_zero(self):
        prob = pulp.LpProblem("t", pulp.LpMaximize)
        with pytest.raises(ValueError, match="no value"):
            net_dispatch([prob.add_variable("d0")], [prob.add_variable("c0")])


class TestAddMutualExclusion:
    def test_only_one_leg_can_be_non_zero(self):
        prob = pulp.LpProblem("t", pulp.LpMaximize)
        c = [prob.add_variable("c0", lowBound=0, upBound=10)]
        d = [prob.add_variable("d0", lowBound=0, upBound=10)]
        add_mutual_exclusion(prob, c, d, 10.0)
        prob += c[0] + d[0]  # both at once would score 20
        assert solve(prob) == "Optimal"
        assert min(c[0].varValue, d[0].varValue) == pytest.approx(0.0)
        assert c[0].varValue + d[0].varValue == pytest.approx(10.0)

    def test_length_mismatch_raises(self):
        prob = pulp.LpProblem("t", pulp.LpMaximize)
        with pytest.raises(ValueError, match="same length"):
            add_mutual_exclusion(prob, [prob.add_variable("a")], [], 1.0)


class TestValidateSchedule:
    def test_a_feasible_schedule_passes(self):
        a = _asset()
        r = validate_schedule([10.0, -10.0], a, duration_h=1.0)
        assert r["feasible"] and not r["violations"]

    def test_charging_through_the_ceiling_is_caught(self):
        a = _asset(initial_soc_pct=0.90)
        r = validate_schedule([-50.0], a, duration_h=1.0)
        assert not r["feasible"]
        assert any("above ceiling" in v for v in r["violations"])

    def test_discharging_through_the_floor_is_caught(self):
        a = _asset(initial_soc_pct=0.10)
        r = validate_schedule([50.0], a, duration_h=1.0)
        assert not r["feasible"]
        assert any("below floor" in v for v in r["violations"])

    def test_power_limit_is_caught(self):
        r = validate_schedule([500.0], _asset(), duration_h=1.0)
        assert any("exceeds" in v and "MW limit" in v for v in r["violations"])

    def test_cycle_budget_is_caught(self):
        a = _asset(initial_soc_pct=0.90, min_soc_pct=0.0)
        r = validate_schedule([50.0, 50.0], a, duration_h=1.0, target_daily_cycles=0.5)
        assert any("cycle budget" in v for v in r["violations"])


class TestNegativePriceChurn:
    """The relaxation used to be paid to dissipate energy at deeply negative prices."""

    def test_schedule_at_minus_1000_is_physically_executable(self):
        # Starting pinned at the ceiling, the old LP returned net [0, -11.64],
        # which executed as charging ended at 100.94 MWh against a 90 MWh cap:
        # it had charged and discharged at once and burned the difference in
        # round-trip losses, because at -£1,000/MWh being paid to charge more
        # than covered the wear on both legs.
        a = _asset(initial_soc_pct=0.90)
        schedule = optimize_da_schedule([-1000.0, -1000.0], a, duration_h=1.0)
        report = validate_schedule(schedule, a, duration_h=1.0)
        assert report["feasible"], report["violations"]
        assert report["max_soc_mwh"] <= a._max_soc_mwh + 1e-6
        assert report["min_soc_mwh"] >= a._min_soc_mwh - 1e-6

    def test_ordinary_prices_still_arbitrage(self):
        a = _asset(initial_soc_pct=0.50)
        schedule = optimize_da_schedule([10.0, 200.0], a, duration_h=1.0)
        assert schedule[0] < 0  # charge cheap
        assert schedule[1] > 0  # discharge dear
        assert validate_schedule(schedule, a, duration_h=1.0)["feasible"]


class TestStrictRejection:
    """Reporting is not a guard — strict mode has to actually refuse."""

    def test_strict_raises_on_an_impossible_schedule(self):
        a = _asset(initial_soc_pct=0.90)
        with pytest.raises(ValueError, match="not physically executable"):
            validate_schedule([-50.0], a, duration_h=1.0, strict=True)

    def test_non_strict_still_only_reports(self):
        a = _asset(initial_soc_pct=0.90)
        assert validate_schedule([-50.0], a, duration_h=1.0)["feasible"] is False

    def test_non_finite_dispatch_is_a_violation(self):
        # A NaN passes every inequality silently, so it has to be caught by name.
        r = validate_schedule([float("nan")], _asset(), duration_h=1.0)
        assert not r["feasible"]
        assert any("finite" in v for v in r["violations"])

    def test_optimisers_refuse_rather_than_return_an_unexecutable_plan(self):
        a = _asset(initial_soc_pct=0.90)
        schedule = optimize_da_schedule([-1000.0, -1000.0], a, duration_h=1.0)
        # Reaching here at all means the optimiser's own strict check passed.
        assert validate_schedule(schedule, a, duration_h=1.0, strict=True)["feasible"]
