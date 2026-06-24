import logging

import pulp

from src.bess.bess_asset import BESSAsset

logger = logging.getLogger(__name__)


def _compute_implied_soc(
    da_schedule: list[float],
    initial_soc_mwh: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    min_soc_mwh: float,
    max_soc_mwh: float,
    duration_h: float = 1.0,
) -> list[float]:
    soc = [initial_soc_mwh]
    for mw in da_schedule:
        if mw >= 0:
            next_soc = soc[-1] - mw * duration_h / discharge_efficiency
        else:
            next_soc = soc[-1] + abs(mw) * duration_h * charge_efficiency
        soc.append(max(min_soc_mwh, min(next_soc, max_soc_mwh)))
    return soc


def _reoptimize_schedule(
    da_schedule: list[float],
    sell_price: list[float],
    buy_price: list[float],
    start_soc_mwh: float,
    asset: BESSAsset,
    duration_h: float,
    exec_cost: float,
    deg_cost: float,
    cycle_budget_mwh: float | None,
) -> list[float]:
    """Re-solve the optimal *physical* schedule over the remaining horizon.

    The day-ahead financial position (``da_schedule``) is locked — it cleared at
    the D-1 11:00 auction and cannot be changed. What the intraday engine *can*
    do is deviate the battery's physical dispatch from that plan and settle the
    deviation in the continuous market. This LP picks the physical net dispatch
    ``P_h`` per period that maximises the value of those deviations:

        max Σ [ dev⁺_h · sell_price_h − dev⁻_h · buy_price_h          (intraday cash)
                − (dev⁺_h + dev⁻_h) · exec_cost                        (execution friction)
                − (charge_h + discharge_h) · deg_cost ] · duration_h   (battery wear)

    where ``dev_h = P_h − da_schedule_h`` is the intraday trade, split into a
    sell leg ``dev⁺`` (extra discharge) priced at ``sell_price`` and a buy leg
    ``dev⁻`` (extra charge) priced at ``buy_price``. ``sell_price``/``buy_price``
    are the **MID proxy**: the known cleared DA price minus/plus the configured
    ``margin_sell``/``margin_buy`` basis, so a deviation is only worth taking when
    the across-period DA spread beats the margins + execution + wear it costs.

    The locked DA revenue is constant and therefore dropped from the objective;
    maximising the deviation value is equivalent to maximising net PnL.
    """
    n = len(da_schedule)
    prob = pulp.LpProblem("Intraday_Reopt", pulp.LpMaximize)

    charge = [pulp.LpVariable(f"c_{h}", lowBound=0, upBound=asset.power_mw) for h in range(n)]
    discharge = [pulp.LpVariable(f"d_{h}", lowBound=0, upBound=asset.power_mw) for h in range(n)]
    soc = [
        pulp.LpVariable(f"s_{h}", lowBound=asset._min_soc_mwh, upBound=asset._max_soc_mwh)
        for h in range(n + 1)
    ]
    dev_pos = [pulp.LpVariable(f"dp_{h}", lowBound=0) for h in range(n)]  # extra discharge (sell)
    dev_neg = [pulp.LpVariable(f"dn_{h}", lowBound=0) for h in range(n)]  # extra charge (buy)

    prob += soc[0] == start_soc_mwh
    for h in range(n):
        prob += (
            soc[h + 1]
            == soc[h]
            - discharge[h] * duration_h / asset.discharge_efficiency
            + charge[h] * duration_h * asset.charge_efficiency
        )
        prob += (discharge[h] - charge[h]) - da_schedule[h] == dev_pos[h] - dev_neg[h]

    if cycle_budget_mwh is not None:
        prob += pulp.lpSum(discharge[h] * duration_h for h in range(n)) <= cycle_budget_mwh

    prob += pulp.lpSum(
        dev_pos[h] * sell_price[h] * duration_h
        - dev_neg[h] * buy_price[h] * duration_h
        - (dev_pos[h] + dev_neg[h]) * exec_cost * duration_h
        - (charge[h] + discharge[h]) * deg_cost * duration_h
        for h in range(n)
    )

    try:
        import highspy  # noqa: F401

        solver = pulp.HiGHS(msg=0)
    except ImportError:
        solver = pulp.PULP_CBC_CMD(msg=0)

    try:
        status = prob.solve(solver)
    except pulp.PulpSolverError:
        logger.warning("Intraday re-opt solver failed; falling back to the locked DA schedule")
        return list(da_schedule)

    if pulp.LpStatus[status] != "Optimal":
        logger.warning(
            "Intraday re-opt non-optimal (%s); falling back to the locked DA schedule",
            pulp.LpStatus[status],
        )
        return list(da_schedule)

    return [discharge[h].varValue - charge[h].varValue for h in range(n)]


def run_intraday_session(
    da_schedule: list[float],
    da_price_actual: list[float],
    mid_prices: list[float],
    asset: BESSAsset,
    config: dict,
) -> dict:
    """Rolling-horizon intraday engine — observed current MID, proxied future.

    Two-stage trader's model. The continuous intraday market means the *current*
    period's MID is visible before delivery, so it is observed, not guessed; only
    the not-yet-visible *future* periods are proxied from the DA curve.

      Stage 1 (D-1 10:30): the day-ahead LP schedules against the *forecast* and
        locks a financial position at the 11:00 auction. That schedule is the
        ``benchmark`` and is settled at the actual cleared DA prices.
      Stage 2 (delivery day, rolling period by period):
        - **Observe.** The current period's MID has become visible, so the engine
          re-optimises the *remaining* horizon pricing the current period at the
          real observed MID (``mid_prices[h]``) and every future period at a *DA
          proxy* — the cleared DA price ± a configurable basis
          (``margin_sell``/``margin_buy``). That hurdle is conservatism on the
          *proxy* only: it tempers netting the DA commitment or opening a new
          position on a still-*guessed* future price. The visible current period
          carries no hurdle.
        - **Execute & roll.** Only the current period is tradeable (its price is
          visible), so only its decision is executed and locked; SOC and the cycle
          budget advance and the engine rolls to the next period, where one more
          real MID has appeared. The executed deviation settles at the observed
          MID. Replacing the DA proxy for future periods with a genuine MID
          *forecast* is exactly the Phase-4 extension.

    mid_prices            — the real observed continuous-market MID. The current
                            period is decided and settled at it; future periods
                            (not yet visible) fall back to the DA proxy.
    """
    n_periods = len(da_schedule)
    duration_h = config.get("resolution_h", 1.0)
    degradation_cost = config["degradation_cost_per_mwh"]
    margin_buy = config.get("margin_buy", 0.0)
    margin_sell = config.get("margin_sell", 0.0)
    exec_cost = config.get("execution", {}).get("slippage", 0.5)

    target_daily_cycles = config.get("target_daily_cycles")
    cycle_cap_mwh = (
        target_daily_cycles * asset.capacity_mwh if target_daily_cycles is not None else None
    )

    # ── Decision prices: observed now, proxied (and hurdled) for the future ──
    # The continuous intraday market means the *current* period's MID is observed
    # before delivery — no guessing. Only the not-yet-visible *future* periods are
    # uncertain, so they are priced from a DA proxy with a conservative basis:
    # extra discharge clears at da − margin_sell, extra charge at da + margin_buy.
    # The hurdle (margin) is conservatism applied to the *proxy* only — it makes
    # the engine cautious about netting the DA commitment or opening a new position
    # on a *guessed* future price. The visible current period carries no hurdle.
    future_sell = [p - margin_sell for p in da_price_actual]
    future_buy = [p + margin_buy for p in da_price_actual]

    # ── Stage 1 benchmark ────────────────────────────────────────────────────
    # The locked DA schedule settled at the actual cleared DA prices — the
    # trader's benchmark, frozen before any intraday action.
    benchmark_da_revenue = sum(mw * duration_h * p for mw, p in zip(da_schedule, da_price_actual))

    # ── Stage 2: rolling-horizon re-optimisation ─────────────────────────────
    # Walk the day period by period. At each step the current period's MID has
    # just become visible, so re-optimise the *remaining* horizon — current period
    # at the observed MID (no hurdle), future periods at the hurdled DA proxy —
    # then execute and lock only the current period (the one whose price is visible
    # and therefore tradeable in the continuous market) and roll forward. One more
    # observed MID arrives each step, so the re-solve genuinely adapts.
    initial_deg = asset.degradation_cost
    intraday_da_improvement = 0.0
    execution_costs_paid = 0.0
    intraday_throughput_mwh = 0.0
    discharge_throughput_mwh = 0.0
    physical: list[float] = []
    dispatch_log: list[dict] = []

    for h in range(n_periods):
        s = da_schedule[h]
        da_p = da_price_actual[h]
        mid_p = mid_prices[h]
        soc_before = asset.soc_pct

        # Re-optimise from the current SOC over the remaining horizon: current
        # period priced at the observed MID, future periods at the hurdled proxy.
        # The (optional) cycle cap is reduced by the throughput already cycled.
        sub_sell = [mid_p] + future_sell[h + 1 :]
        sub_buy = [mid_p] + future_buy[h + 1 :]
        remaining_budget = (
            max(0.0, cycle_cap_mwh - discharge_throughput_mwh)
            if cycle_cap_mwh is not None
            else None
        )
        plan = _reoptimize_schedule(
            da_schedule=da_schedule[h:],
            sell_price=sub_sell,
            buy_price=sub_buy,
            start_soc_mwh=asset._soc_mwh,
            asset=asset,
            duration_h=duration_h,
            exec_cost=exec_cost,
            deg_cost=degradation_cost,
            cycle_budget_mwh=remaining_budget,
        )
        # Clamp the executed period to what is physically deliverable from the
        # current SOC. The sub-LP can pick a degenerate simultaneous charge+
        # discharge leg at negative prices whose net would overshoot a bound when
        # dispatched as a single leg; clamping keeps the executed position
        # feasible. In a continuous market the trader only ever commits what can
        # be delivered, so there is no imbalance — the deviation, whatever it ends
        # up being, settles at the observed MID.
        p_raw = plan[0]  # only the now-visible current period is executed
        if p_raw > 0:
            max_dis_mw = (
                (asset._soc_mwh - asset._min_soc_mwh) * asset.discharge_efficiency / duration_h
            )
            p = max(0.0, min(p_raw, max_dis_mw, asset.power_mw))
        elif p_raw < 0:
            max_chg_mw = (
                (asset._max_soc_mwh - asset._soc_mwh) / asset.charge_efficiency / duration_h
            )
            p = -max(0.0, min(-p_raw, max_chg_mw, asset.power_mw))
        else:
            p = 0.0
        dev = p - s

        # Settle the executed deviation at the observed MID, gross of execution.
        intraday_da_improvement += dev * duration_h * mid_p
        traded_mwh = abs(dev) * duration_h
        execution_costs_paid += traded_mwh * exec_cost
        intraday_throughput_mwh += traded_mwh

        # ── Physical dispatch of the executed (clamped) period ───────────────
        if p > 0:
            asset.discharge(p, duration_h)
            discharge_throughput_mwh += p * duration_h
            log_action = "discharge"
            log_mw = p
        elif p < 0:
            asset.charge(-p, duration_h)
            log_action = "charge"
            log_mw = -p
        else:
            log_action = "idle"
            log_mw = 0.0

        physical.append(p)

        if dev > 1e-9:
            trade_type = "reopt_sell"
            rule_label = f"Re-opt: sell extra at observed MID £{mid_p:.2f}/MWh"
        elif dev < -1e-9:
            trade_type = "reopt_buy"
            rule_label = f"Re-opt: buy extra at observed MID £{mid_p:.2f}/MWh"
        elif s != 0:
            trade_type = "physical_dispatch"
            rule_label = "Physical Dispatch (DA plan unchanged)"
        else:
            trade_type = "idle"
            rule_label = "Idle"

        dispatch_log.append(
            {
                "period": h,
                "action": log_action,
                "trade_type": trade_type,
                "mw": log_mw,
                "price": da_p,
                "da_price_actual": da_p,
                "mid_price": mid_p,
                "da_mw": s,
                "intraday_mw": dev,
                # Back-compat aliases for the dashboard trade tape: the intraday
                # deviation is a single physical re-optimisation leg (no separate
                # zero-wear netting leg exists under the LP), so spread_mw carries it
                # and netting_mw stays zero.
                "spread_mw": dev,
                "netting_mw": 0.0,
                "final_mw": p,
                "rule_label": rule_label,
                "soc_before": soc_before,
                "soc_after": asset.soc_pct,
            }
        )

    total_degradation = asset.degradation_cost - initial_deg

    # Wear avoided by re-optimising away from the benchmark plan (the rolling-LP
    # analogue of the old financial-netting "cycles saved"): benchmark throughput
    # minus the throughput the battery actually cycled.
    benchmark_throughput = sum(abs(s) for s in da_schedule) * duration_h
    actual_throughput = sum(abs(p) for p in physical) * duration_h
    cycles_saved_mwh = max(0.0, benchmark_throughput - actual_throughput)

    net_pnl = (
        benchmark_da_revenue + intraday_da_improvement - execution_costs_paid - total_degradation
    )

    return {
        # Trader's-alpha ledger — buckets sum exactly to net_pnl:
        # benchmark + intraday improvement − execution − degradation.
        "benchmark_da_revenue": benchmark_da_revenue,
        "intraday_da_improvement": intraday_da_improvement,
        "execution_costs_paid": execution_costs_paid,
        "total_degradation_cost": total_degradation,
        "net_pnl": net_pnl,
        "accumulated_intraday_throughput_mwh": intraday_throughput_mwh,
        "cycles_saved_mwh": cycles_saved_mwh,
        # Legacy aliases retained so existing summaries keep resolving:
        "da_revenue": benchmark_da_revenue,
        "intraday_pnl": intraday_da_improvement,
        "dispatch_log": dispatch_log,
    }
