from src.bess.bess_asset import BESSAsset


def _compute_implied_soc(
    da_schedule: list[float],
    initial_soc_mwh: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    capacity_mwh: float,
    duration_h: float = 1.0,
) -> list[float]:
    soc = [initial_soc_mwh]
    for mw in da_schedule:
        if mw >= 0:
            next_soc = soc[-1] - mw * duration_h / discharge_efficiency
        else:
            next_soc = soc[-1] + abs(mw) * duration_h * charge_efficiency
        soc.append(max(0.0, min(next_soc, capacity_mwh)))
    return soc


def run_intraday_session(
    da_schedule: list[float],
    da_price_actual: list[float],
    mid_prices: list[float],
    imbalance_prices: list[float],
    asset: BESSAsset,
    config: dict,
) -> dict:
    n_periods = len(da_schedule)
    duration_h = config.get("resolution_h", 1.0)
    degradation_cost = config["degradation_cost_per_mwh"]
    soc_drift_tolerance = config.get("soc_drift_tolerance", 0.05)

    implied_soc = _compute_implied_soc(
        da_schedule, asset._soc_mwh, asset.charge_efficiency, asset.discharge_efficiency, asset.capacity_mwh,
        duration_h,
    )

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

        # Rule 1: execute DA schedule dispatch
        if mw > 0:
            max_mw = max(0.0, min(mw, asset._soc_mwh * asset.discharge_efficiency / duration_h, asset.power_mw))
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
            headroom = asset.capacity_mwh - asset._soc_mwh
            max_mw = max(
                0.0,
                min(
                    target,
                    headroom / (asset.charge_efficiency * duration_h),
                    asset.power_mw,
                ),
            )
            if max_mw > 0:
                asset.charge(max_mw, duration_h)
            shortfall = target - max_mw
            if shortfall > 0:
                imbalance_pnl += shortfall * duration_h * imbalance_prices[h]
            log_action = "charge"
            log_mw = max_mw
            log_price = da_price_actual[h]

        # Rule 2: SOC drift rebalance
        actual_pct = asset.soc_pct
        implied_pct = implied_soc[h + 1] / asset.capacity_mwh
        drift = actual_pct - implied_pct

        if abs(drift) > soc_drift_tolerance:
            drift_mwh = abs(drift) * asset.capacity_mwh
            if drift > 0:
                rebal_mw = min(drift_mwh / duration_h, asset.power_mw)
                if asset.can_discharge(rebal_mw, duration_h):
                    asset.discharge(rebal_mw, duration_h)
                    intraday_pnl += rebal_mw * duration_h * mid_prices[h]
            else:
                rebal_mw = min(drift_mwh / duration_h, asset.power_mw)
                if asset.can_charge(rebal_mw, duration_h):
                    asset.charge(rebal_mw, duration_h)
                    intraday_pnl -= rebal_mw * duration_h * mid_prices[h]

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
