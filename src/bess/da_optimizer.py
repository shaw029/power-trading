import logging

import pulp

from src.bess.bess_asset import BESSAsset

logger = logging.getLogger(__name__)


def _project_to_feasible(
    schedule: list[float], asset: BESSAsset, duration_h: float
) -> list[float]:
    """Clamp each period's dispatch so the implied SOC trajectory respects the
    asset's strict ``[min, max]`` SOC bounds.

    LP solvers satisfy the SOC equality/bound constraints only to within their
    feasibility tolerance, so the raw schedule can overshoot the bounds by a small
    sliver (e.g. charging to 19.06 MWh against a 19.0 MWh ceiling). The intraday
    engine enforces the bounds exactly, so any overshoot would otherwise spill into
    imbalance. Projecting here keeps the locked schedule physically executable.
    """
    soc = asset.initial_soc_pct * asset.capacity_mwh
    projected: list[float] = []
    for mw in schedule:
        if mw > 0:  # discharge
            max_drawn = max(0.0, soc - asset._min_soc_mwh)
            drawn = min(mw * duration_h / asset.discharge_efficiency, max_drawn)
            mw = drawn * asset.discharge_efficiency / duration_h
            soc -= drawn
        elif mw < 0:  # charge
            max_stored = max(0.0, asset._max_soc_mwh - soc)
            stored = min(-mw * duration_h * asset.charge_efficiency, max_stored)
            mw = -(stored / asset.charge_efficiency / duration_h)
            soc += stored
        projected.append(mw)
    return projected


def optimize_da_schedule(
    da_price_forecast: list[float],
    asset: BESSAsset,
    duration_h: float = 1.0,
    target_daily_cycles: float | None = None,
) -> list[float]:
    n_periods = len(da_price_forecast)
    periods = range(n_periods)

    prob = pulp.LpProblem("DA_BESS_Schedule", pulp.LpMaximize)

    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=asset.power_mw) for h in periods]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=asset.power_mw) for h in periods]
    min_soc_mwh = asset.min_soc_pct * asset.capacity_mwh
    max_soc_mwh = asset.max_soc_pct * asset.capacity_mwh
    soc = [pulp.LpVariable(f"soc_{h}", lowBound=min_soc_mwh, upBound=max_soc_mwh) for h in range(n_periods + 1)]

    prob += pulp.lpSum(
        (discharge[h] - charge[h]) * da_price_forecast[h] * duration_h
        - (discharge[h] + charge[h]) * asset.degradation_cost_per_mwh * duration_h
        for h in periods
    )

    initial_soc = asset.capacity_mwh * asset.initial_soc_pct
    prob += soc[0] == initial_soc

    for h in periods:
        prob += (
            soc[h + 1]
            == soc[h]
            - discharge[h] * duration_h / asset.discharge_efficiency
            + charge[h] * duration_h * asset.charge_efficiency
        )

    if target_daily_cycles is not None:
        prob += pulp.lpSum(discharge[h] * duration_h for h in periods) <= target_daily_cycles * asset.capacity_mwh

    try:
        import highspy  # noqa: F401
        solver = pulp.HiGHS(msg=0)
    except ImportError:
        solver = pulp.PULP_CBC_CMD(msg=0)

    try:
        status = prob.solve(solver)
    except pulp.PulpSolverError:
        logger.warning("DA solver failed; returning zero-dispatch fallback schedule")
        return [0.0] * n_periods

    if pulp.LpStatus[status] != "Optimal":
        logger.warning("DA solver non-optimal (%s); returning zero-dispatch fallback", pulp.LpStatus[status])
        return [0.0] * n_periods

    schedule = [discharge[h].varValue - charge[h].varValue for h in periods]
    return _project_to_feasible(schedule, asset, duration_h)
