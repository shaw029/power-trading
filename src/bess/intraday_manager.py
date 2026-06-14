from src.bess.bess_asset import BESSAsset


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


def run_intraday_session(
    da_schedule: list[float],
    da_price_actual: list[float],
    mid_prices: list[float],
    imbalance_prices: list[float],
    asset: BESSAsset,
    config: dict,
    imbalance_sell_prices: list[float] | None = None,
) -> dict:
    """Dynamic Opportunity-Cost intraday engine.

    Each period is processed sequentially through three rules, all bounded by
    forward-looking physical guardrails derived solely from the already-cleared
    day-ahead schedule and prices (zero look-ahead onto live market data):

      Rule 1 — Physical Envelope Setup: the Required Reserve (R_h) and Available
        Headroom (H_h) that intraday actions must respect so the remaining DA
        commitments can always be served. A live cycle cap freezes the envelope
        once intraday throughput exhausts the daily budget.
      Rule 2 — Financial Netting: capture the DA–MID spread without moving the
        battery when the current MID beats the locked DA price for the period.
      Rule 4 — Opportunity-Cost Arbitrage: trade physically at MID whenever it
        beats the best/cheapest reachable future DA price (net of degradation),
        clamped to the R_h / H_h envelope.

    imbalance_prices      — SBP (system buy price): cost when the BESS is short
                            (couldn't deliver scheduled discharge volume).
    imbalance_sell_prices — SSP (system sell price): credit when the BESS is long
                            (couldn't absorb scheduled charging volume).
                            Defaults to imbalance_prices when not supplied.
    """
    n_periods = len(da_schedule)
    duration_h = config.get("resolution_h", 1.0)
    degradation_cost = config["degradation_cost_per_mwh"]
    margin_buy = config.get("margin_buy", 0.0)
    margin_sell = config.get("margin_sell", 0.0)
    exec_cost = config.get("execution", {}).get("slippage", 0.5)

    target_daily_cycles = config.get("target_daily_cycles")
    cycle_cap_mwh = (
        target_daily_cycles * asset.capacity_mwh
        if target_daily_cycles is not None
        else None
    )

    da_revenue_delivered = 0.0
    da_revenue_netted = 0.0
    financial_netting_pnl = 0.0
    physical_dispatch_pnl = 0.0
    imbalance_pnl = 0.0
    accumulated_intraday_throughput_mwh = 0.0
    initial_deg = asset.degradation_cost
    dispatch_log: list[dict] = []

    # ── Trader's Alpha ledger ────────────────────────────────────────────────
    # The frozen day-ahead schedule is the benchmark; each intraday rule is an
    # additive alpha layer on top of it and execution friction is its own bucket,
    # so DA Benchmark + Rule 2 + Rule 4 − Execution + Imbalance − Degradation ties
    # back exactly to Net PnL.
    #   benchmark_da_revenue — DA schedule value actually delivered against the
    #     frozen plan (the netted volume's spread is broken out as Rule 2 Alpha,
    #     so the DA credit is never counted in both the benchmark and the spread).
    #   rule2_alpha          — gross DA–MID spread captured by Rule 2 netting.
    #   execution_costs_paid — slippage paid on every Rule 2 / Rule 4 traded MWh.
    benchmark_da_revenue = 0.0
    rule2_alpha = 0.0
    execution_costs_paid = 0.0

    for h in range(n_periods):
        mw = da_schedule[h]
        da_p = da_price_actual[h]
        mid_p = mid_prices[h]
        soc_before = asset.soc_pct

        # Decision-delta tracking: how the locked DA plan is transformed into the
        # final physical position. da_mw is the original commitment; netting_mw is
        # the signed volume Rule 2 nets financially; spread_mw is Rule 4's physical
        # arbitrage trade; final_mw is the physically dispatched DA volume.
        da_mw = mw
        netting_mw = 0.0
        spread_mw = 0.0
        rule_label = "Physical Dispatch"
        log_action = "idle"
        log_mw = 0.0
        log_price = 0.0
        log_netted_mwh = 0.0
        trade_type = "physical_dispatch" if mw != 0 else "idle"

        # ── Rule 1: Physical Envelope Setup ──────────────────────────────────
        # Required Reserve (R_h): SOC to hold so every remaining DA discharge can
        #   be served without breaching min SOC (assuming no future charge help).
        # Available Headroom (H_h): SOC ceiling so every remaining DA charge can
        #   be absorbed without breaching max SOC (assuming no future discharge).
        future_schedule = da_schedule[h + 1:]
        future_discharge_mwh = sum(f for f in future_schedule if f > 0) * duration_h
        future_charge_mwh = sum(-f for f in future_schedule if f < 0) * duration_h
        required_reserve = asset._min_soc_mwh + future_discharge_mwh / asset.discharge_efficiency
        available_headroom = asset._max_soc_mwh - future_charge_mwh * asset.charge_efficiency
        required_reserve = min(required_reserve, asset._max_soc_mwh)
        available_headroom = max(available_headroom, asset._min_soc_mwh)

        # Cycle cap: once intraday throughput hits the daily budget, freeze the
        # envelope at the current SOC so no further intraday movement is allowed.
        if cycle_cap_mwh is not None and accumulated_intraday_throughput_mwh >= cycle_cap_mwh:
            required_reserve = available_headroom = asset._soc_mwh

        # ── Rule 2: Financial Netting (zero physical movement) ───────────────
        # Capture the DA–MID spread financially when the MID price beats the
        # locked DA price for this period; the netted volume settles at MID with
        # a net-zero physical position, so only un-netted DA volume is dispatched.
        physical_mw = mw
        if mw > 0 and mid_p <= da_p - margin_buy - exec_cost:
            netted = mw * duration_h
            financial_netting_pnl -= netted * mid_p     # buy the volume back at MID
            da_revenue_netted += netted * da_p          # keep the DA sale credit
            rule2_alpha += netted * abs(da_p - mid_p)   # gross spread captured
            physical_mw = 0.0
            netting_mw = -mw
            log_netted_mwh = netted
            trade_type = "financial_netting"
            rule_label = f"Rule 2: Buy-Back at £{mid_p:.2f}/MWh"
        elif mw < 0 and mid_p >= da_p + margin_sell + exec_cost:
            netted = abs(mw) * duration_h
            financial_netting_pnl += netted * mid_p     # sell the volume at MID
            da_revenue_netted -= netted * da_p          # offset the DA charge cost
            rule2_alpha += netted * abs(da_p - mid_p)   # gross spread captured
            physical_mw = 0.0
            netting_mw = -mw
            log_netted_mwh = netted
            trade_type = "financial_netting"
            rule_label = f"Rule 2: Sell-Back at £{mid_p:.2f}/MWh"

        # ── Physical execution of the un-netted DA volume ────────────────────
        # The DA contract settles regardless of any clamping shortfall, which is
        # priced separately into imbalance_pnl. Base DA execution is bounded only
        # by the absolute SOC limits; the intraday R_h / H_h envelope is reserved
        # for Rule 4 so honouring the day-ahead plan is never starved.
        da_revenue_delivered += physical_mw * duration_h * da_p
        benchmark_da_revenue += physical_mw * duration_h * da_p
        if physical_mw > 0:
            allowed_mwh = (asset._soc_mwh - asset._min_soc_mwh) * asset.discharge_efficiency
            max_mw = max(0.0, min(physical_mw, allowed_mwh / duration_h, asset.power_mw))
            if max_mw > 0:
                asset.discharge(max_mw, duration_h)
            shortfall = physical_mw - max_mw
            if shortfall > 0:
                imbalance_pnl -= shortfall * duration_h * imbalance_prices[h]
            log_action = "discharge"
            log_mw = max_mw
            log_price = da_p
        elif physical_mw < 0:
            target = abs(physical_mw)
            allowed_mwh = (asset._max_soc_mwh - asset._soc_mwh) / asset.charge_efficiency
            max_mw = max(0.0, min(target, allowed_mwh / duration_h, asset.power_mw))
            if max_mw > 0:
                asset.charge(max_mw, duration_h)
            shortfall = target - max_mw
            if shortfall > 0:
                # Charging shortfall: BESS is long — receives SSP (system sell price).
                ssp = imbalance_sell_prices[h] if imbalance_sell_prices is not None else imbalance_prices[h]
                imbalance_pnl += shortfall * duration_h * ssp
            log_action = "charge"
            log_mw = max_mw
            log_price = da_p

        # ── Rule 4: Opportunity-Cost Arbitrage (physical movement) ───────────
        # Opportunity cost is the best/cheapest price reachable in the remaining
        # cleared DA schedule, net of degradation. Trade at MID whenever it beats
        # that hurdle, using the power left after the DA leg and clamping SOC to
        # the R_h / H_h envelope so future DA commitments are never breached.
        future_prices = da_price_actual[h + 1:]
        if future_prices:
            oc_discharge = max(future_prices) - degradation_cost
            oc_charge = min(future_prices) + degradation_cost
        else:
            # Final period: No future DA position exists.
            # To justify a standalone cycle, MID must beat the current DA price
            # by MORE than the cost of degradation.
            oc_discharge = da_p + degradation_cost
            oc_charge = da_p - degradation_cost

        remaining_mw = asset.power_mw - abs(log_mw)
        if remaining_mw > 1e-9:
            allow_discharge = physical_mw >= 0  # never reverse a scheduled charge
            allow_charge = physical_mw <= 0     # never reverse a scheduled discharge
            if allow_discharge and mid_p > oc_discharge + exec_cost:
                allowed_mwh = (asset._soc_mwh - required_reserve) * asset.discharge_efficiency
                extra_mw = max(0.0, min(remaining_mw, allowed_mwh / duration_h))
                if extra_mw > 0:
                    asset.discharge(extra_mw, duration_h)
                    physical_dispatch_pnl += extra_mw * duration_h * mid_p
                    accumulated_intraday_throughput_mwh += extra_mw * duration_h
                    spread_mw = extra_mw
                    trade_type = "opportunity_arb"
                    rule_label = f"Rule 4: OC Discharge at £{mid_p:.2f}/MWh"
            elif allow_charge and mid_p < oc_charge - exec_cost:
                allowed_mwh = (available_headroom - asset._soc_mwh) / asset.charge_efficiency
                extra_mw = max(0.0, min(remaining_mw, allowed_mwh / duration_h))
                if extra_mw > 0:
                    asset.charge(extra_mw, duration_h)
                    physical_dispatch_pnl -= extra_mw * duration_h * mid_p
                    accumulated_intraday_throughput_mwh += extra_mw * duration_h
                    spread_mw = -extra_mw
                    trade_type = "opportunity_arb"
                    rule_label = f"Rule 4: OC Charge at £{mid_p:.2f}/MWh"

        # Execution friction on every traded MWh this period — the Rule 2 netting
        # leg and the Rule 4 physical leg — isolated into its own bucket rather
        # than netted into the rule alphas (which stay gross).
        traded_mwh = abs(netting_mw * duration_h) + abs(spread_mw * duration_h)
        execution_costs_paid += traded_mwh * exec_cost

        dispatch_log.append({
            "period": h,
            "action": log_action,
            "trade_type": trade_type,
            "mw": log_mw,
            "netted_mwh": log_netted_mwh,
            "price": log_price,
            "da_mw": da_mw,
            "netting_mw": netting_mw,
            "spread_mw": spread_mw,
            "final_mw": physical_mw,
            "rule_label": rule_label,
            "required_reserve_mwh": required_reserve,
            "available_headroom_mwh": available_headroom,
            "soc_before": soc_before,
            "soc_after": asset.soc_pct,
        })

    total_degradation = asset.degradation_cost - initial_deg
    intraday_pnl = financial_netting_pnl + physical_dispatch_pnl
    cycles_saved_mwh = sum(
        entry["netted_mwh"] for entry in dispatch_log
        if entry["trade_type"] == "financial_netting"
    )

    da_revenue = da_revenue_delivered + da_revenue_netted

    return {
        "da_revenue_delivered": da_revenue_delivered,
        "da_revenue_netted": da_revenue_netted,
        "financial_spread_captured": da_revenue_netted + financial_netting_pnl,
        "intraday_pnl": intraday_pnl,
        "financial_netting_pnl": financial_netting_pnl,
        "physical_dispatch_pnl": physical_dispatch_pnl,
        "cycles_saved_mwh": cycles_saved_mwh,
        "accumulated_intraday_throughput_mwh": accumulated_intraday_throughput_mwh,
        "imbalance_pnl": imbalance_pnl,
        "total_degradation_cost": total_degradation,
        # Trader's Alpha buckets — sum to net_pnl with imbalance and degradation:
        # benchmark + rule2 + rule4 − execution + imbalance − degradation.
        "benchmark_da_revenue": benchmark_da_revenue,
        "rule2_alpha": rule2_alpha,
        "rule4_alpha": physical_dispatch_pnl,  # gross of execution costs
        "execution_costs_paid": execution_costs_paid,
        "net_pnl": da_revenue + intraday_pnl + imbalance_pnl - total_degradation - execution_costs_paid,
        "dispatch_log": dispatch_log,
    }
