import logging

import pulp

from src.bess.bess_asset import BESSAsset

logger = logging.getLogger(__name__)


def optimize_da_schedule(
    da_prices: list[float],
    asset: BESSAsset,
) -> list[float]:
    n_hours = len(da_prices)
    hours = range(n_hours)

    prob = pulp.LpProblem("DA_BESS_Schedule", pulp.LpMaximize)

    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=asset.power_mw) for h in hours]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=asset.power_mw) for h in hours]
    soc = [pulp.LpVariable(f"soc_{h}", lowBound=0, upBound=asset.capacity_mwh) for h in range(n_hours + 1)]

    prob += pulp.lpSum(
        (discharge[h] - charge[h]) * da_prices[h]
        - (discharge[h] + charge[h]) * asset.degradation_cost_per_mwh
        for h in hours
    )

    initial_soc = asset.capacity_mwh * asset.initial_soc_pct
    prob += soc[0] == initial_soc
    prob += soc[n_hours] >= initial_soc

    for h in hours:
        prob += soc[h + 1] == soc[h] - discharge[h] + charge[h] * asset.round_trip_efficiency

    try:
        prob.solve(pulp.HiGHS(msg=0))
    except Exception:
        logger.warning("DA solver failed; returning zero-dispatch fallback schedule")
        return [0.0] * n_hours

    return [discharge[h].varValue - charge[h].varValue for h in hours]
