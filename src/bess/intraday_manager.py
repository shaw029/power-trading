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


def _find_bottleneck_index(
    start_soc_mwh: float,
    future_schedule: list[float],
    charge_efficiency: float,
    discharge_efficiency: float,
    bound_mwh: float,
    duration_h: float,
    hitting_ceiling: bool,
) -> int:
    """Walk the implied SOC forward over ``future_schedule`` and return the offset of
    the first period whose SOC reaches ``bound_mwh`` — a ceiling when
    ``hitting_ceiling`` is True, otherwise a floor. Returns len(future_schedule)
    when the bound is never reached."""
    soc = start_soc_mwh
    for offset, future_mw in enumerate(future_schedule):
        if future_mw >= 0:
            soc -= future_mw * duration_h / discharge_efficiency
        else:
            soc += abs(future_mw) * duration_h * charge_efficiency
        if hitting_ceiling and soc >= bound_mwh:
            return offset
        if not hitting_ceiling and soc <= bound_mwh:
            return offset
    return len(future_schedule)


def run_intraday_session(
    da_schedule: list[float],
    da_price_actual: list[float],
    mid_prices: list[float],
    imbalance_prices: list[float],
    asset: BESSAsset,
    config: dict,
    imbalance_sell_prices: list[float] | None = None,
    volatility_array: list[float] | None = None,
) -> dict:
    """
    imbalance_prices      — SBP (system buy price): cost when the BESS is short
                            (couldn't deliver scheduled discharge volume).
    imbalance_sell_prices — SSP (system sell price): credit when the BESS is long
                            (couldn't absorb scheduled charging volume).
                            Defaults to imbalance_prices when not supplied.
    volatility_array      — per-period MID price volatility used to size the proxy
                            forward hedge in the alpha override rule. When omitted,
                            the alpha override rule is skipped.
    """
    n_periods = len(da_schedule)
    duration_h = config.get("resolution_h", 1.0)
    degradation_cost = config["degradation_cost_per_mwh"]

    da_revenue_delivered = 0.0
    da_revenue_netted = 0.0
    financial_netting_pnl = 0.0
    physical_dispatch_pnl = 0.0
    imbalance_pnl = 0.0
    initial_deg = asset.degradation_cost
    dispatch_log: list[dict] = []

    for h in range(n_periods):
        mw = da_schedule[h]
        log_action = "idle"
        log_mw = 0.0
        log_price = 0.0
        log_netted_mwh = 0.0

        # Decision-delta tracking: how the locked DA plan is transformed into the
        # final physical position by each rule. da_mw is the original commitment;
        # netting_mw/override_mw are the signed volume deltas applied when Rules 2
        # and 3 fire (0.0 otherwise); final_mw is the resulting physical position.
        da_mw = mw
        netting_mw = 0.0
        override_mw = 0.0
        spread_mw = 0.0
        rule_label = "Rule 4: Physical Dispatch"
        soc_before = asset.soc_pct

        # Forward-looking physical guardrails over the remaining locked DA schedule.
        # Required Reserve (R_h): the minimum SOC to hold at this period so every
        #   future DA discharge can be served without breaching min SOC.
        # Available Headroom (H_h): the maximum SOC to hold at this period so every
        #   future DA charge can be absorbed without breaching max SOC.
        required_reserve = asset._min_soc_mwh
        available_headroom = asset._max_soc_mwh
        for future_mw in reversed(da_schedule[h + 1:]):
            if future_mw > 0:
                # Future discharge draws energy from the pack.
                drawn = future_mw * duration_h / asset.discharge_efficiency
                required_reserve += drawn
                available_headroom = min(asset._max_soc_mwh, available_headroom + drawn)
            elif future_mw < 0:
                # Future charge stores energy into the pack.
                stored = abs(future_mw) * duration_h * asset.charge_efficiency
                required_reserve = max(asset._min_soc_mwh, required_reserve - stored)
                available_headroom -= stored

        # Rule 2: Constrained Financial Netting.
        # Capture the DA–MID spread financially — without physically moving the
        # battery — when the current MID price beats the best future DA price we
        # could reach while holding the eligible energy (discharge) or headroom
        # (charge). The netted volume is settled at MID and its net physical
        # position is zero; only the un-netted remainder is physically dispatched.
        margin_buy = config.get("margin_buy", 0.0)
        margin_sell = config.get("margin_sell", 0.0)
        future_schedule = da_schedule[h + 1:]
        physical_mw = mw
        trade_type = "physical_dispatch"

        if mw > 0:
            eligible = min(mw, available_headroom - asset._soc_mwh)
            if eligible > 0:
                offset = _find_bottleneck_index(
                    asset._soc_mwh, future_schedule,
                    asset.charge_efficiency, asset.discharge_efficiency,
                    asset._max_soc_mwh, duration_h, hitting_ceiling=True,
                )
                window = da_price_actual[h + 1: h + 1 + offset]
                if window and mid_prices[h] <= max(window) - margin_buy:
                    financial_netting_pnl -= eligible * duration_h * mid_prices[h]
                    da_revenue_netted += eligible * duration_h * da_price_actual[h]
                    physical_mw = mw - eligible
                    netting_mw = physical_mw - mw  # volume removed from physical
                    rule_label = f"Rule 2: Buy-Back at £{mid_prices[h]:.2f}/MWh"
                    trade_type = "financial_buyback"
                    log_netted_mwh = eligible * duration_h

        elif mw < 0:
            eligible = min(abs(mw), asset._soc_mwh - required_reserve)
            if eligible > 0:
                offset = _find_bottleneck_index(
                    asset._soc_mwh, future_schedule,
                    asset.charge_efficiency, asset.discharge_efficiency,
                    asset._min_soc_mwh, duration_h, hitting_ceiling=False,
                )
                window = da_price_actual[h + 1: h + 1 + offset]
                if window and mid_prices[h] >= min(window) + margin_sell:
                    financial_netting_pnl += eligible * duration_h * mid_prices[h]
                    # The netted leg is a scheduled charge — its DA value is a cost.
                    da_revenue_netted -= eligible * duration_h * da_price_actual[h]
                    physical_mw = mw + eligible
                    netting_mw = physical_mw - mw  # volume removed from physical
                    rule_label = f"Rule 2: Sell-Back at £{mid_prices[h]:.2f}/MWh"
                    trade_type = "financial_sellback"
                    log_netted_mwh = eligible * duration_h

        # Rule 3: High-Conviction Alpha Override.
        # When the MID price is rich enough to clear a hedged hurdle, aggressively
        # dump the available discharge volume now — even if it eats into the
        # forward reserve. Any reserve deficit is a naked short on the future floor
        # period; it is covered by a proxy forward hedge priced off that period's
        # DA price plus a volatility buffer. The hedge cost is booked now and the
        # hedged energy is restored, so the future floor is still served and no
        # imbalance penalty is charged for the deficit later.
        if volatility_array is not None and trade_type == "physical_dispatch":
            alpha_threshold = config.get("alpha_threshold", 5.0)
            vol_multiplier = config.get("vol_multiplier", 1.0)
            # dump_volume is pack energy; the power limit is on terminal output, so
            # the matching pack draw over the period is power_mw·dt / discharge_eff.
            # Without the efficiency term the dump under-draws the pack and leaves
            # SOC above H_h, overflowing a later DA charge (Rule 3 may break R_h but
            # not the headroom guardrail).
            max_pack_draw = asset.power_mw * duration_h / asset.discharge_efficiency
            dump_volume = min(max_pack_draw, asset._soc_mwh - asset._min_soc_mwh)
            if dump_volume > 0:
                hedge_cost = 0.0
                if asset._soc_mwh - dump_volume < required_reserve:
                    # The dump shorts a future floor period — price its proxy hedge.
                    offset = _find_bottleneck_index(
                        asset._soc_mwh, future_schedule,
                        asset.charge_efficiency, asset.discharge_efficiency,
                        asset._min_soc_mwh, duration_h, hitting_ceiling=False,
                    )
                    t_floor = h + 1 + offset
                    if t_floor < n_periods:
                        hedge_cost = (
                            da_price_actual[t_floor]
                            + vol_multiplier * volatility_array[h]
                        )
                if mid_prices[h] - hedge_cost - degradation_cost > alpha_threshold:
                    # Deliver the dumped pack energy (efficiency-adjusted) at MID.
                    released_mw = min(
                        asset.power_mw,
                        dump_volume * asset.discharge_efficiency / duration_h,
                    )
                    asset.discharge(released_mw, duration_h)
                    financial_netting_pnl += released_mw * duration_h * mid_prices[h]
                    # Neutralise the reserve deficit with the forward proxy hedge:
                    # pay its cost now and restore the hedged energy so downstream
                    # periods stay whole and incur no imbalance penalty for it.
                    deficit = max(0.0, required_reserve - asset._soc_mwh)
                    if deficit > 0:
                        financial_netting_pnl -= deficit * hedge_cost
                        asset._soc_mwh += deficit
                    # The scheduled DA position is resolved financially, not
                    # physically delivered — book its DA value as netted.
                    da_revenue_netted += physical_mw * duration_h * da_price_actual[h]
                    override_mw = -physical_mw  # entire DA volume resolved off-physical
                    rule_label = f"Rule 3: Alpha Override at £{mid_prices[h]:.2f}/MWh"
                    physical_mw = 0.0
                    trade_type = "alpha_override"
                    log_action = "discharge"
                    log_mw = released_mw
                    log_price = mid_prices[h]
                    log_netted_mwh = released_mw * duration_h

        # Physical Execution: dispatch the un-netted DA volume for this period,
        # clamping it so the resulting SOC stays within
        # [required_reserve, available_headroom]. The DA contract for the
        # scheduled volume settles regardless of any clamping shortfall (which is
        # priced separately into imbalance_pnl).
        da_revenue_delivered += physical_mw * duration_h * da_price_actual[h]
        if physical_mw > 0:
            allowed_mwh = (asset._soc_mwh - required_reserve) * asset.discharge_efficiency
            max_mw = max(0.0, min(physical_mw, allowed_mwh / duration_h, asset.power_mw))
            if max_mw > 0:
                asset.discharge(max_mw, duration_h)
            shortfall = physical_mw - max_mw
            if shortfall > 0:
                imbalance_pnl -= shortfall * duration_h * imbalance_prices[h]
            log_action = "discharge"
            log_mw = max_mw
            log_price = da_price_actual[h]

        elif physical_mw < 0:
            target = abs(physical_mw)
            allowed_mwh = (available_headroom - asset._soc_mwh) / asset.charge_efficiency
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
            log_price = da_price_actual[h]

        # Rule 4: spread improvement — opportunistically trade the leftover power
        # capacity at MID, clamped to the forward guardrails (required_reserve /
        # available_headroom), not just the absolute SOC bounds. Clamping keeps any
        # energy or headroom the locked DA schedule still needs, so this never
        # surfaces as an imbalance shortfall later.
        #
        # It can open a position on idle periods too (mw == 0): there the direction
        # is set purely by MID vs DA. On periods that already hold a DA position it
        # only extends in that same direction (the battery can't charge and
        # discharge at once).
        remaining_mw = asset.power_mw - abs(mw)
        if remaining_mw > 0:
            allow_discharge = mw >= 0  # idle or scheduled discharge
            allow_charge = mw <= 0     # idle or scheduled charge
            if allow_discharge and mid_prices[h] > da_price_actual[h] + degradation_cost:
                allowed_mwh = (asset._soc_mwh - required_reserve) * asset.discharge_efficiency
                extra_mw = max(0.0, min(remaining_mw, allowed_mwh / duration_h))
                if extra_mw > 0:
                    asset.discharge(extra_mw, duration_h)
                    physical_dispatch_pnl += extra_mw * duration_h * mid_prices[h]
                    spread_mw = extra_mw  # extra discharge sold at MID
            elif allow_charge and mid_prices[h] < da_price_actual[h] - degradation_cost:
                allowed_mwh = (available_headroom - asset._soc_mwh) / asset.charge_efficiency
                extra_mw = max(0.0, min(remaining_mw, allowed_mwh / duration_h))
                if extra_mw > 0:
                    asset.charge(extra_mw, duration_h)
                    physical_dispatch_pnl -= extra_mw * duration_h * mid_prices[h]
                    spread_mw = -extra_mw  # extra charge bought at MID

        dispatch_log.append({
            "period": h,
            "action": log_action,
            "trade_type": trade_type,
            "mw": log_mw,
            "netted_mwh": log_netted_mwh,
            "price": log_price,
            "da_mw": da_mw,
            "netting_mw": netting_mw,
            "override_mw": override_mw,
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
        if entry["trade_type"] in ("financial_buyback", "financial_sellback", "alpha_override")
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
        "imbalance_pnl": imbalance_pnl,
        "total_degradation_cost": total_degradation,
        "net_pnl": da_revenue + intraday_pnl + imbalance_pnl - total_degradation,
        "dispatch_log": dispatch_log,
    }
