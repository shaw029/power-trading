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
    """
    imbalance_prices      — SBP (system buy price): cost when the BESS is short
                            (couldn't deliver scheduled discharge volume).
    imbalance_sell_prices — SSP (system sell price): credit when the BESS is long
                            (couldn't absorb scheduled charging volume).
                            Defaults to imbalance_prices when not supplied.
    """
    n_periods = len(da_schedule)
    duration_h = config.get("resolution_h", 1.0)
    degradation_cost = config["degradation_cost_per_mwh"]

    da_revenue = 0.0
    intraday_pnl = 0.0
    imbalance_pnl = 0.0
    initial_deg = asset.degradation_cost
    dispatch_log: list[dict] = []

    for h in range(n_periods):
        mw = da_schedule[h]
        log_action = "idle"
        log_mw = 0.0
        log_price = 0.0

        da_revenue += mw * duration_h * da_price_actual[h]

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

        # Physical Execution: dispatch the DA schedule for this period, clamping the
        # volume so the resulting SOC stays within [required_reserve, available_headroom].
        if mw > 0:
            allowed_mwh = (asset._soc_mwh - required_reserve) * asset.discharge_efficiency
            max_mw = max(0.0, min(mw, allowed_mwh / duration_h, asset.power_mw))
            if max_mw > 0:
                asset.discharge(max_mw, duration_h)
            shortfall = mw - max_mw
            if shortfall > 0:
                imbalance_pnl -= shortfall * duration_h * imbalance_prices[h]
            log_action = "discharge"
            log_mw = max_mw
            log_price = da_price_actual[h]

        elif mw < 0:
            target = abs(mw)
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

        # Rule 3: spread improvement
        if mw != 0:
            remaining_mw = asset.power_mw - abs(mw)
            if remaining_mw > 0:
                if mw > 0 and mid_prices[h] > da_price_actual[h] + degradation_cost:
                    if asset.can_discharge(remaining_mw, duration_h):
                        asset.discharge(remaining_mw, duration_h)
                        intraday_pnl += remaining_mw * duration_h * mid_prices[h]
                elif mw < 0 and mid_prices[h] < da_price_actual[h] - degradation_cost:
                    if asset.can_charge(remaining_mw, duration_h):
                        asset.charge(remaining_mw, duration_h)
                        intraday_pnl -= remaining_mw * duration_h * mid_prices[h]

        dispatch_log.append({
            "period": h,
            "action": log_action,
            "mw": log_mw,
            "price": log_price,
            "required_reserve_mwh": required_reserve,
            "available_headroom_mwh": available_headroom,
            "soc_after": asset.soc_pct,
        })

    total_degradation = asset.degradation_cost - initial_deg

    return {
        "da_revenue": da_revenue,
        "intraday_pnl": intraday_pnl,
        "imbalance_pnl": imbalance_pnl,
        "total_degradation_cost": total_degradation,
        "net_pnl": da_revenue + intraday_pnl + imbalance_pnl - total_degradation,
        "dispatch_log": dispatch_log,
    }
