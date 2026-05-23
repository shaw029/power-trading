import pulp

from src.bess.bess_asset import BESSAsset


def optimize_da_schedule(
    da_prices: list[float],
    asset: BESSAsset,
) -> list[float]:
    hours = range(24)

    prob = pulp.LpProblem("DA_BESS_Schedule", pulp.LpMaximize)

    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=asset.power_mw) for h in hours]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=asset.power_mw) for h in hours]
    soc = [pulp.LpVariable(f"soc_{h}", lowBound=0, upBound=asset.capacity_mwh) for h in range(25)]

    prob += pulp.lpSum(
        (discharge[h] - charge[h]) * da_prices[h] for h in hours
    )

    initial_soc = asset.capacity_mwh * asset.initial_soc_pct
    prob += soc[0] == initial_soc

    for h in hours:
        prob += soc[h + 1] == soc[h] - discharge[h] + charge[h] * asset.round_trip_efficiency

    prob.solve(pulp.HiGHS(msg=0))

    return [discharge[h].varValue - charge[h].varValue for h in hours]
