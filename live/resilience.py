"""System-alignment metrics for the live GB BESS benchmark.

Quantifies how battery dispatch relates to system state — the bridge between
the profit-optimal benchmark and the resilience question: does the battery
discharge when the system is stressed and absorb energy when it is in surplus?

Definitions (all computed from the same public feeds the benchmark uses):

* **Residual load** — transmission demand minus wind minus embedded solar
  (MW, half-hourly). The system quantity the rest of the fleet must serve.
* **Stress period** — a half-hour whose residual load is in the top decile of
  the analysis window.
* **Surplus period** — a half-hour whose residual load is in the bottom decile
  of the window, or whose price is negative.
* **Alignment scores** — the share of a dispatch's discharged energy delivered
  in stress periods (stress coverage), the share of its charged energy drawn
  in surplus periods (surplus absorption), and the correlation between
  dispatch and residual load. One scorer for any dispatch series, so the
  simulated benchmark and the real fleet's Physical Notifications are measured
  with the same instrument.
* **Alignment gap** — the difference between the profit-optimal dispatch and a
  resilience-optimal counterfactual (same asset, same physics, objective =
  deliver in stress and absorb in surplus), valued both ways: profit forgone
  by full alignment and stress delivery forgone by pure arbitrage.

Pure pandas/PuLP — no HTTP and no Streamlit — so everything is unit-testable.
"""

import logging

import pandas as pd
import pulp

from src.bess.bess_asset import BESSAsset

logger = logging.getLogger(__name__)

# Decile thresholds for stress/surplus classification over the window.
STRESS_QUANTILE = 0.9
SURPLUS_QUANTILE = 0.1


def residual_load(system: pd.DataFrame) -> pd.Series:
    """Residual load (MW) from a whole-system snapshot frame.

    ``system`` is the half-hourly frame from
    :func:`live.fetch_live.get_day_system` (or several concatenated days).
    Missing columns contribute zero rather than failing, so a day without a
    solar print still classifies — the caller sees the coverage it has.
    """
    demand = system.get("demand_actual", pd.Series(0.0, index=system.index))
    wind = system.get("gen_WIND", pd.Series(0.0, index=system.index))
    solar = system.get("solar_mw", pd.Series(0.0, index=system.index))
    return (demand.fillna(0.0) - wind.fillna(0.0) - solar.fillna(0.0)).rename("residual_mw")


def classify_periods(
    residual: pd.Series,
    prices: pd.Series | None = None,
    stress_q: float = STRESS_QUANTILE,
    surplus_q: float = SURPLUS_QUANTILE,
) -> pd.DataFrame:
    """Stress / surplus flags per period over the whole window.

    Thresholds are quantiles of ``residual`` across the *window* (not per
    day), so a stressed half-hour means stressed relative to the whole
    analysis period. ``prices`` (aligned, any frequency reindexed by the
    caller) adds negative-price periods to the surplus set — being paid to
    consume is surplus by definition regardless of residual level.
    """
    stress_level = residual.quantile(stress_q)
    surplus_level = residual.quantile(surplus_q)
    flags = pd.DataFrame(index=residual.index)
    flags["residual_mw"] = residual
    flags["stress"] = residual >= stress_level
    flags["surplus"] = residual <= surplus_level
    if prices is not None:
        aligned = prices.reindex(residual.index).ffill()
        flags["surplus"] |= aligned < 0.0
    return flags


def alignment_scores(dispatch_mw: pd.Series, flags: pd.DataFrame) -> dict:
    """Alignment of one dispatch series (positive = discharge) with the flags.

    The dispatch is reindexed onto the flags' grid (no fill — only periods
    with both a dispatch value and a classification count). Returns
    ``stress_coverage``, ``surplus_absorption``, ``correlation`` and the
    underlying energy totals; shares are ``None`` when the denominator is
    zero (a battery that never discharged has no coverage to report).
    """
    joined = flags.join(dispatch_mw.rename("mw"), how="inner").dropna(subset=["mw"])
    discharge = joined["mw"].clip(lower=0.0)
    charge = (-joined["mw"]).clip(lower=0.0)

    total_discharge = float(discharge.sum())
    total_charge = float(charge.sum())
    stress_discharge = float(discharge[joined["stress"]].sum())
    surplus_charge = float(charge[joined["surplus"]].sum())

    correlation = None
    if joined["mw"].std() > 0 and joined["residual_mw"].std() > 0:
        correlation = float(joined["mw"].corr(joined["residual_mw"]))

    return {
        "stress_coverage": stress_discharge / total_discharge if total_discharge > 0 else None,
        "surplus_absorption": surplus_charge / total_charge if total_charge > 0 else None,
        "correlation": correlation,
        "total_discharge": total_discharge,
        "total_charge": total_charge,
        "stress_discharge": stress_discharge,
        "surplus_charge": surplus_charge,
        "n_periods": int(len(joined)),
    }


def readiness_at_stress(soc_before: pd.Series, stress: pd.Series) -> float | None:
    """Mean state of charge (fraction) at the onset of each stress block.

    A stress onset is a stressed period whose predecessor is not stressed.
    Readiness asks: when the system tightened, how much energy did the
    battery actually hold? ``None`` when the window contains no onset with a
    known SOC.
    """
    aligned = stress.reindex(soc_before.index)
    if aligned.isna().all():
        return None
    aligned = aligned.fillna(False)
    onset = aligned & ~aligned.shift(1, fill_value=False)
    values = soc_before[onset]
    return float(values.mean()) if len(values) else None


def optimize_resilience_dispatch(
    stress: list[bool],
    surplus: list[bool],
    asset: BESSAsset,
    duration_h: float = 1.0,
    target_daily_cycles: float | None = None,
) -> list[float]:
    """Resilience-optimal dispatch: same physics, system-value objective.

    Maximises energy discharged in stress periods plus energy charged in
    surplus periods, subject to the identical SOC window, power limit,
    efficiencies and cycle cap the profit LP faces. A small penalty on
    off-flag activity keeps the schedule quiet outside flagged periods
    instead of cycling on ties. Returns MW per period (positive = discharge).
    """
    n = len(stress)
    periods = range(n)
    prob = pulp.LpProblem("Resilience_Dispatch", pulp.LpMaximize)

    charge = [pulp.LpVariable(f"c_{h}", lowBound=0, upBound=asset.power_mw) for h in periods]
    discharge = [pulp.LpVariable(f"d_{h}", lowBound=0, upBound=asset.power_mw) for h in periods]
    min_soc = asset.min_soc_pct * asset.capacity_mwh
    max_soc = asset.max_soc_pct * asset.capacity_mwh
    soc = [
        pulp.LpVariable(f"s_{h}", lowBound=min_soc, upBound=max_soc) for h in range(n + 1)
    ]

    tie_break = 1e-3
    prob += pulp.lpSum(
        discharge[h] * duration_h * (1.0 if stress[h] else -tie_break)
        + charge[h] * duration_h * (1.0 if surplus[h] else -tie_break)
        for h in periods
    )

    prob += soc[0] == asset.capacity_mwh * asset.initial_soc_pct
    for h in periods:
        prob += (
            soc[h + 1]
            == soc[h]
            - discharge[h] * duration_h / asset.discharge_efficiency
            + charge[h] * duration_h * asset.charge_efficiency
        )
    if target_daily_cycles is not None:
        prob += (
            pulp.lpSum(discharge[h] * duration_h for h in periods)
            <= target_daily_cycles * asset.capacity_mwh
        )

    try:
        import highspy  # noqa: F401

        solver = pulp.HiGHS(msg=0)
    except ImportError:
        solver = pulp.PULP_CBC_CMD(msg=0)

    try:
        status = prob.solve(solver)
    except pulp.PulpSolverError:
        logger.warning("Resilience LP failed; returning idle dispatch")
        return [0.0] * n
    if pulp.LpStatus[status] != "Optimal":
        logger.warning("Resilience LP non-optimal (%s); returning idle dispatch",
                       pulp.LpStatus[status])
        return [0.0] * n

    return [discharge[h].varValue - charge[h].varValue for h in periods]


def alignment_gap(
    arb_dispatch_mw: list[float],
    day_ahead_prices: list[float],
    stress: list[bool],
    surplus: list[bool],
    asset: BESSAsset,
    duration_h: float = 1.0,
    target_daily_cycles: float | None = None,
) -> dict:
    """One day's alignment gap: profit-optimal vs resilience-optimal dispatch.

    Both dispatches are valued the same two ways — energy value at the cleared
    DA price (transparent, no intraday layer or fees) and stress-hour MWh
    delivered — giving the two sides of the gap:

    * ``profit_cost_of_alignment`` — DA energy value forgone by running the
      resilience-optimal schedule instead of the profit-optimal one.
    * ``stress_mwh_forgone`` — stress-hour energy the profit-optimal dispatch
      leaves undelivered relative to the resilience-optimal one.
    """
    res_dispatch = optimize_resilience_dispatch(
        stress, surplus, asset, duration_h, target_daily_cycles
    )

    # Terminal-inventory credit: energy still in the battery at day end is not
    # worthless — without this, a schedule that absorbs surplus and holds it
    # reads as pure cost. Both schedules get the same treatment: the SOC change
    # over the day is valued at the day's mean DA price.
    mean_price = (
        sum(day_ahead_prices) / len(day_ahead_prices) if day_ahead_prices else 0.0
    )

    def value(dispatch: list[float]) -> float:
        energy = sum(mw * p * duration_h for mw, p in zip(dispatch, day_ahead_prices))
        soc = asset.initial_soc_pct * asset.capacity_mwh
        for mw in dispatch:
            if mw > 0:
                soc -= mw * duration_h / asset.discharge_efficiency
            else:
                soc += -mw * duration_h * asset.charge_efficiency
        start = asset.initial_soc_pct * asset.capacity_mwh
        return energy + (soc - start) * mean_price

    def stress_mwh(dispatch: list[float]) -> float:
        return sum(max(mw, 0.0) * duration_h for mw, s in zip(dispatch, stress) if s)

    profit_arb = value(arb_dispatch_mw)
    profit_res = value(res_dispatch)
    stress_arb = stress_mwh(arb_dispatch_mw)
    stress_res = stress_mwh(res_dispatch)
    return {
        "profit_arb": profit_arb,
        "profit_res": profit_res,
        "profit_cost_of_alignment": profit_arb - profit_res,
        "stress_mwh_arb": stress_arb,
        "stress_mwh_res": stress_res,
        "stress_mwh_forgone": stress_res - stress_arb,
        "res_dispatch": res_dispatch,
    }
