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
* **Tier ladder** — stress severity in three independent tiers. Tier 1
  (relative): top-decile residual load, as above. Tier 2 (system-confirmed):
  Elexon's loss-of-load probability is positive OR the de-rated margin is
  below ``DRM_TIGHT_MW`` — tight by the operator's own absolute measure, not
  relative to the window on screen. Tier 3 (declared): the half-hour overlaps
  an active Capacity Market Notice window. Periods without a LoLP/DRM print
  are *unknown* at tier 2 — excluded from every tier-2 denominator, never
  assumed calm.

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

# Tier-2 absolute de-rated margin floor (MW). ~2,000 MW is roughly one large
# CCGT plus operating reserve — the territory where NESO has historically
# issued margin notices. Absolute by design: tier 2 must mean tight in MW
# terms, not tight relative to the window on screen (that is tier 1's job).
DRM_TIGHT_MW = 2000.0


def residual_load(system: pd.DataFrame) -> pd.Series:
    """Residual load (MW) from a whole-system snapshot frame.

    ``system`` is the half-hourly frame from
    :func:`live.fetch_live.get_day_system` (or several concatenated days).
    Missing data propagates as NaN rather than being zero-filled: a period
    without a wind or solar print would otherwise read as demand-minus-nothing
    — an inflated residual that can raise false stress flags downstream.
    Periods (or whole days) with any component missing therefore come back as
    NaN and are excluded from classification, never fabricated.
    """
    nan = pd.Series(float("nan"), index=system.index)
    demand = system.get("demand_actual", nan)
    wind = system.get("gen_WIND", nan)
    solar = system.get("solar_mw", nan)
    return (demand - wind - solar).rename("residual_mw")


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

    Periods whose residual is NaN (missing demand, wind or solar data) are
    dropped from the output entirely: they are *unclassifiable*, which is
    different from being not-stressed, and must not enter the quantiles or
    the flags.
    """
    residual = residual.dropna()
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
    # Reindexing a boolean Series introduces NaN and promotes it to object.
    # Filling then downcasting back is deprecated, so the missing periods are
    # named False as part of the cast instead.
    aligned = aligned.astype("boolean").fillna(False).astype(bool)
    onset = aligned & ~aligned.shift(1, fill_value=False)
    values = soc_before[onset]
    return float(values.mean()) if len(values) else None


def cmn_flags(
    index: pd.DatetimeIndex,
    cmn_windows: pd.DataFrame | None,
    period: pd.Timedelta = pd.Timedelta(minutes=30),
) -> pd.Series:
    """Boolean per grid timestamp: does ``[ts, ts + period)`` overlap a CMN window?

    ``cmn_windows`` carries one row per notice with tz-aware ``start_utc`` /
    ``end_utc`` columns (:func:`live.fetch_live.get_cmn_notices` rows). Both
    intervals are half-open, so a notice ending exactly at a period's start
    does not flag it. Rows with a missing start are skipped; a missing *end*
    is the register's normal shape for an issued-and-still-open notice, so it
    defaults to ``start + period`` — the targeted settlement period is always
    flagged, never silently dropped. An empty or ``None`` frame yields
    all-False — the normal case, CMNs are rare.
    """
    flags = pd.Series(False, index=index, name="cmn")
    if cmn_windows is None or cmn_windows.empty:
        return flags
    for _, row in cmn_windows.iterrows():
        start, end = row.get("start_utc"), row.get("end_utc")
        if pd.isna(start):
            continue
        if pd.isna(end) or end <= start:
            end = start + period
        flags |= (index < end) & ((index + period) > start)
    return flags


def classify_tiers(
    flags: pd.DataFrame,
    lolpdrm: pd.DataFrame | None = None,
    cmn_windows: pd.DataFrame | None = None,
    drm_tight_mw: float = DRM_TIGHT_MW,
) -> pd.DataFrame:
    """Layer the tier ladder onto :func:`classify_periods` output.

    ``lolpdrm`` is the half-hourly ``lolp``/``drm_mw`` frame (latest print per
    period); it is reindexed onto the flags' grid with no fill — a period
    without a print stays NaN and is *unknown* at tier 2 (``tier2_known``
    False), which is different from calm. ``cmn_windows`` as in
    :func:`cmn_flags`. Returns an index-aligned frame with columns ``lolp``,
    ``drm_mw``, ``tier1`` (= the relative stress flag), ``tier2``,
    ``tier2_known``, ``tier3`` and ``tier`` (0–3, the highest active tier).
    """
    tiers = pd.DataFrame(index=flags.index)
    nan = pd.Series(float("nan"), index=flags.index)
    if lolpdrm is not None and not lolpdrm.empty:
        aligned = lolpdrm.reindex(flags.index)
        tiers["lolp"] = aligned["lolp"] if "lolp" in aligned.columns else nan
        tiers["drm_mw"] = aligned["drm_mw"] if "drm_mw" in aligned.columns else nan
    else:
        tiers["lolp"] = nan
        tiers["drm_mw"] = nan
    tiers["tier1"] = flags["stress"].astype(bool)
    tiers["tier2_known"] = tiers["lolp"].notna() | tiers["drm_mw"].notna()
    # NaN comparisons are False, so unknown periods land False here; the
    # tier2_known mask is what keeps them out of every denominator.
    tiers["tier2"] = (tiers["lolp"] > 0.0) | (tiers["drm_mw"] < drm_tight_mw)
    tiers["tier3"] = cmn_flags(flags.index, cmn_windows)
    tiers["tier"] = (
        tiers["tier1"].astype(int)
        .where(~tiers["tier2"], 2)
        .where(~tiers["tier3"], 3)
    )
    return tiers


def tier_metrics(
    tiers: pd.DataFrame,
    dispatch_mw: pd.Series | None = None,
    soc_before: pd.Series | None = None,
) -> dict:
    """Window-level tightness metrics from a :func:`classify_tiers` frame.

    Dispatch-dependent entries use the same inner-join-and-drop rule as
    :func:`alignment_scores`; every share is ``None`` when its denominator is
    zero or the underlying feed is absent, so callers can render "—" instead
    of a fabricated number. ``tier2_coverage`` is computed over *known*
    periods only.
    """
    drm = tiers["drm_mw"].dropna()
    min_drm_mw = float(drm.min()) if len(drm) else None
    min_drm_time = drm.idxmin() if len(drm) else None
    n_lolp_positive = int((tiers["lolp"] > 0.0).sum())
    n_tier2 = int(tiers["tier2"].sum())
    n_tier2_known = int(tiers["tier2_known"].sum())

    tier2_coverage = None
    min_drm_at_discharge = None
    if dispatch_mw is not None:
        joined = tiers.join(dispatch_mw.rename("mw"), how="inner").dropna(subset=["mw"])
        known = joined[joined["tier2_known"]]
        discharge = known["mw"].clip(lower=0.0)
        total_discharge = float(discharge.sum())
        if total_discharge > 0:
            tier2_coverage = float(discharge[known["tier2"]].sum()) / total_discharge
        discharging_drm = joined.loc[joined["mw"] > 0, "drm_mw"].dropna()
        if len(discharging_drm):
            min_drm_at_discharge = float(discharging_drm.min())

    tier2_confirm_rate = None
    confirmable = tiers[tiers["tier1"] & tiers["tier2_known"]]
    if len(confirmable):
        tier2_confirm_rate = float(confirmable["tier2"].mean())

    readiness_at_cmn = None
    if soc_before is not None:
        readiness_at_cmn = readiness_at_stress(soc_before, tiers["tier3"])

    return {
        "min_drm_mw": min_drm_mw,
        "min_drm_time": min_drm_time,
        "n_lolp_positive": n_lolp_positive,
        "n_tier2": n_tier2,
        "n_tier2_known": n_tier2_known,
        "tier2_coverage": tier2_coverage,
        "min_drm_at_discharge": min_drm_at_discharge,
        "tier2_confirm_rate": tier2_confirm_rate,
        "readiness_at_cmn": readiness_at_cmn,
    }


def optimize_resilience_dispatch(
    stress: list[bool],
    surplus: list[bool],
    asset: BESSAsset,
    duration_h: float = 1.0,
    target_daily_cycles: float | None = None,
) -> list[float]:
    """Resilience-optimal dispatch: same physics, system-value objective.

    Maximises energy discharged in stress periods (priority weight 2) plus
    energy charged in surplus periods (weight 1), subject to the identical SOC
    window, power limit, efficiencies and cycle cap the profit LP faces.

    The weights are chosen so that no charge/discharge *churn* loop is ever
    profitable. Crediting gross surplus charging invites gaming: dump energy
    off-flag for a token penalty, then re-charge in surplus for fresh credit —
    each dumped MWh frees ``1/(ηc·ηd)`` MWh of creditable charging (≈1.13 at
    0.94² round trip), so any dump penalty below that is exploitable, and
    under a cycle cap the whole discharge budget flows to churn instead of
    stress delivery. Discharge outside stress and charge during stress are
    therefore penalised at weight 2 (> ``1/(ηc·ηd)`` for any round-trip
    efficiency above 50%), which makes every loop strictly negative while
    leaving the legitimate pattern — charge cheaply off-flag or in surplus,
    deliver in stress — essentially free (off-flag charging costs only a
    tie-break). Returns MW per period (positive = discharge).
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

    w_stress, w_surplus, w_block, tie_break = 2.0, 1.0, 2.0, 1e-3

    def _coeff_discharge(h: int) -> float:
        return w_stress if stress[h] else -w_block

    def _coeff_charge(h: int) -> float:
        if surplus[h]:
            return w_surplus
        return -w_block if stress[h] else -tie_break

    prob += pulp.lpSum(
        discharge[h] * duration_h * _coeff_discharge(h)
        + charge[h] * duration_h * _coeff_charge(h)
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
