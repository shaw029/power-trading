"""Shared LP machinery for the battery optimisers.

Three optimisers in this repo — the day-ahead schedule, the intraday
re-optimisation and the resilience/blended dispatch — all model a battery with
separate non-negative charge and discharge variables and then hand back only the
net. That relaxation is only safe while the objective makes running both at once
unprofitable, and there is a whole price regime where it is not.

At sufficiently negative prices, charging *earns* money. Once the state of charge
is pinned at its ceiling the solver cannot charge any further on net — but it can
charge and discharge simultaneously, letting round-trip losses swallow the
difference, and get paid for the privilege. The net schedule that comes back
looks like ordinary charging, and executing it as ordinary charging puts more
energy into the battery than the LP ever modelled.

A worked case with the shipped defaults (100 MWh / 50 MW, 0.94 each way, £5/MWh
degradation) starting at the 90 MWh ceiling and priced at -£1,000/MWh: the raw
net schedule is ``[0, -11.64]``, which executed as net charging ends the day at
100.94 MWh — 10.94 MWh above a ceiling the LP believed it was respecting.

:func:`add_mutual_exclusion` closes that off with one binary per period, at the
cost of turning the LP into a MILP. :func:`validate_schedule` is the belt to that
braces: it replays the extracted schedule through the same physics the execution
engine uses and refuses anything that does not fit.
"""

from __future__ import annotations

import logging
import math

import pulp

from src.bess.bess_asset import BESSAsset

logger = logging.getLogger(__name__)

# Tolerance for replaying a solved schedule. Solvers satisfy bounds only to
# within their own feasibility tolerance, so an exact comparison would trip on
# arithmetic noise rather than on real infeasibility.
SOC_TOLERANCE_MWH = 1e-6


def add_mutual_exclusion(
    prob: pulp.LpProblem,
    charge: list,
    discharge: list,
    power_mw: float,
    tag: str = "",
) -> list:
    """Forbid charging and discharging in the same period.

    Adds one binary per period and the pair of indicator constraints that bind it
    to the two power variables, so at most one of them can be non-zero.

    Args:
        prob:      The problem being built.
        charge:    Per-period charge variables (non-negative).
        discharge: Per-period discharge variables (non-negative).
        power_mw:  Upper bound on either leg — the big-M for the indicators, so
                   it must be a genuine bound or the constraint does nothing.
        tag:       Suffix for variable names, to keep them unique when several
                   models are built in one process.

    Returns:
        The binary mode variables (1 = charging allowed, 0 = discharging allowed),
        in case the caller wants to constrain them further.
    """
    if len(charge) != len(discharge):
        raise ValueError(
            f"charge and discharge must be the same length, got {len(charge)} and {len(discharge)}"
        )

    mode = [pulp.LpVariable(f"mode{tag}_{h}", cat="Binary") for h in range(len(charge))]
    for h in range(len(charge)):
        prob += charge[h] <= power_mw * mode[h]
        prob += discharge[h] <= power_mw * (1 - mode[h])
    return mode


def validate_schedule(
    schedule: list[float],
    asset: BESSAsset,
    duration_h: float = 1.0,
    target_daily_cycles: float | None = None,
    commit_fraction: float = 1.0,
    label: str = "schedule",
    start_soc_mwh: float | None = None,
    strict: bool = False,
) -> dict:
    """Replay a net schedule through the asset's physics and report what it does.

    The optimisers return net MW per period. This walks that net dispatch the way
    the execution engine will — charging at ``charge_efficiency``, discharging at
    ``1 / discharge_efficiency`` — and reports the state of charge it actually
    reaches, so a schedule that only balances inside the solver's own relaxation
    is caught before it is executed.

    ``start_soc_mwh`` defaults to the asset's *live* state of charge, which is
    what a mid-day re-optimisation starts from. Anchoring on ``initial_soc_pct``
    instead would replay a rolling re-solve from the morning's opening charge and
    report floor breaches that never happen.

    With ``strict``, a schedule that does not fit is raised rather than logged.
    Reporting alone is not a guard: a caller that logs a warning and returns the
    schedule anyway still hands an unexecutable plan to the engine, which is the
    failure the check exists to prevent. Non-finite dispatch is always a
    violation — a NaN silently passes every inequality below.

    Returns:
        ``{"feasible": bool, "min_soc_mwh", "max_soc_mwh", "end_soc_mwh",
        "discharge_mwh", "throughput_mwh", "violations": [str, ...]}``

    Raises:
        ValueError: if ``strict`` and the schedule is not physically executable.
    """
    soc = asset._soc_mwh if start_soc_mwh is None else start_soc_mwh
    lo, hi = asset._min_soc_mwh, asset._max_soc_mwh
    seen_min = seen_max = soc
    discharge_mwh = throughput_mwh = 0.0
    violations: list[str] = []

    for h, mw in enumerate(schedule):
        if not math.isfinite(mw):
            violations.append(f"period {h}: dispatch is {mw!r}, not a finite MW value")
            continue
        if mw > 0:
            released = mw * duration_h
            soc -= released / asset.discharge_efficiency
            discharge_mwh += released
            throughput_mwh += released
        elif mw < 0:
            gross = -mw * duration_h
            soc += gross * asset.charge_efficiency
            throughput_mwh += gross

        if abs(mw) > asset.power_mw + SOC_TOLERANCE_MWH:
            violations.append(f"period {h}: |{mw:.4f}| MW exceeds {asset.power_mw} MW limit")
        if soc < lo - SOC_TOLERANCE_MWH:
            violations.append(f"period {h}: SOC {soc:.4f} MWh below floor {lo:.4f}")
        if soc > hi + SOC_TOLERANCE_MWH:
            violations.append(f"period {h}: SOC {soc:.4f} MWh above ceiling {hi:.4f}")

        seen_min, seen_max = min(seen_min, soc), max(seen_max, soc)

    if target_daily_cycles is not None:
        budget = target_daily_cycles * asset.capacity_mwh * commit_fraction
        if discharge_mwh > budget + SOC_TOLERANCE_MWH:
            violations.append(
                f"discharge {discharge_mwh:.4f} MWh exceeds cycle budget {budget:.4f} MWh"
            )

    if violations:
        detail = "; ".join(violations[:5])
        if strict:
            raise ValueError(f"{label} is not physically executable: {detail}")
        logger.warning("%s is not physically executable: %s", label, detail)

    return {
        "feasible": not violations,
        "min_soc_mwh": seen_min,
        "max_soc_mwh": seen_max,
        "end_soc_mwh": soc,
        "discharge_mwh": discharge_mwh,
        "throughput_mwh": throughput_mwh,
        "violations": violations,
    }
