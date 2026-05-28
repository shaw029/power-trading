import logging

import pulp

from src.bess.bess_asset import BESSAsset

logger = logging.getLogger(__name__)


def optimize_da_schedule(
    da_price_forecast: list[float],
    asset: BESSAsset,
    duration_h: float = 1.0,
) -> list[float]:
    n_periods = len(da_price_forecast)
    periods = range(n_periods)

    prob = pulp.LpProblem("DA_BESS_Schedule", pulp.LpMaximize)

    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=asset.power_mw) for h in periods]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=asset.power_mw) for h in periods]
    soc = [pulp.LpVariable(f"soc_{h}", lowBound=0, upBound=asset.capacity_mwh) for h in range(n_periods + 1)]

    prob += pulp.lpSum(
        (discharge[h] - charge[h]) * da_price_forecast[h] * duration_h
        - (discharge[h] + charge[h]) * asset.degradation_cost_per_mwh * duration_h
        for h in periods
    )

    initial_soc = asset.capacity_mwh * asset.initial_soc_pct
    prob += soc[0] == initial_soc
    prob += soc[n_periods] >= initial_soc

    for h in periods:
        prob += (
            soc[h + 1]
            == soc[h]
            - discharge[h] * duration_h / asset.discharge_efficiency
            + charge[h] * duration_h * asset.charge_efficiency
        )

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

    return [discharge[h].varValue - charge[h].varValue for h in periods]
