"""Atomic JSON persistence for the live GB BESS benchmark artifacts.

This module is the single read/write layer for the project's committed JSON
artifacts under ``docs/data/`` (Appendix A of the spec). It performs no fetching
and no calculation: it serialises the in-memory :class:`live.settle.DayResult`
(plus its context and labels) and the small roll-up artifacts to disk, and reads
them back.

Every write is atomic and validated:

  1. The artifact dict is built and its floats rounded to three decimals.
  2. It is written to a sibling ``<target>.tmp`` file.
  3. The bytes are read back and validated with :mod:`live.schema`.
  4. Only then is the temp file ``os.replace``-d over the target.

If any step fails the temp file is removed and the existing target — if any — is
left untouched, so a partially written or malformed artifact is never published.
"""

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Callable

from live import schema
from live.assets import REFERENCE_POWER_MW, RESOLUTION_H
from live.settle import DayResult
from src.utils.config import PROJECT_ROOT

# Root of the committed artifact tree. Module-level so tests can redirect it
# (e.g. to a ``tmp_path``) by monkeypatching this attribute; all paths are
# derived from it at call time.
DATA_DIR: Path = PROJECT_ROOT / "docs" / "data"

# Decimal places kept for every float written, to bound artifact size.
_ROUND_NDIGITS: int = 3


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def _duration_hours(duration: str) -> int:
    """Parse a duration key like ``"4h"`` into its integer hour count."""
    return int(duration.removesuffix("h"))


def _days_dir() -> Path:
    return DATA_DIR / "days"


def _date_str(date: dt.date | str) -> str:
    """Normalise a date to its ``YYYY-MM-DD`` ISO string."""
    return date if isinstance(date, str) else date.isoformat()


def _day_path(date: dt.date | str) -> Path:
    return _days_dir() / f"{_date_str(date)}.json"


def _latest_path() -> Path:
    return DATA_DIR / "latest.json"


def _history_path() -> Path:
    return DATA_DIR / "history.json"


def _manifest_path() -> Path:
    return DATA_DIR / "manifest.json"


# --------------------------------------------------------------------------- #
# Atomic write helpers
# --------------------------------------------------------------------------- #
def _round_floats(obj: Any) -> Any:
    """Recursively round every float to :data:`_ROUND_NDIGITS` decimals."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return round(obj, _ROUND_NDIGITS)
    if isinstance(obj, dict):
        return {key: _round_floats(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(value) for value in obj]
    return obj


def _atomic_write(path: Path, obj: dict, validate: Callable[[Any], None]) -> None:
    """Round, write to ``<path>.tmp``, validate the bytes, then replace ``path``.

    On any failure the temp file is removed and ``path`` is left as it was, so an
    existing valid artifact is never corrupted by a failed write.
    """
    rounded = _round_floats(obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            # allow_nan=False: NaN/Inf serialise to the bare tokens NaN/Infinity,
            # which are valid to Python's json but rejected by the browser's strict
            # JSON.parse (docs/app.js). Refuse them here so a non-finite value (e.g.
            # a missing MID price) aborts the write and leaves the good target in
            # place rather than publishing an artifact that blanks the dashboard.
            json.dump(rounded, handle, indent=2, allow_nan=False)
        with open(tmp, "r", encoding="utf-8") as handle:
            written = json.load(handle)
        validate(written)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _read_json(path: Path, validate: Callable[[Any], None]) -> dict | None:
    """Read and validate a JSON artifact, or return ``None`` if absent."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        obj = json.load(handle)
    validate(obj)
    assert isinstance(obj, dict)
    return obj


# --------------------------------------------------------------------------- #
# Per-day artifact
# --------------------------------------------------------------------------- #
def _timestamps(date: dt.date | str, n_periods: int) -> list[str]:
    """UTC ISO timestamps stepping by :data:`RESOLUTION_H` from the day's start."""
    iso = _date_str(date)
    base = dt.datetime.fromisoformat(iso).replace(tzinfo=dt.timezone.utc)
    step = dt.timedelta(hours=RESOLUTION_H)
    return [(base + step * i).isoformat().replace("+00:00", "Z") for i in range(n_periods)]


def _asset_block(
    dispatch_log: list[dict],
    schedule_mw: list[float],
    end_soc: float,
    capacity_mwh: float,
    power_mw: float,
    benchmark_da_revenue: float,
    intraday_da_improvement: float,
    execution_costs_paid: float,
    degradation_cost: float,
    net_pnl: float,
    cycles: float,
    capture: float,
) -> dict:
    """Build one duration's asset block for the per-day artifact."""
    dispatch = [
        {
            "period": entry["period"],
            "da_mw": entry["da_mw"],
            "intraday_mw": entry["intraday_mw"],
            "final_mw": entry["final_mw"],
            "soc_after": entry["soc_after"],
            "da_price": entry["da_price_actual"],
            "mid_price": entry["mid_price"],
            "trade_type": entry["trade_type"],
            "rule_label": entry["rule_label"],
        }
        for entry in dispatch_log
    ]
    track = [entry["soc_after"] for entry in dispatch_log]
    start_soc = dispatch_log[0]["soc_before"] if dispatch_log else end_soc
    return {
        "capacity_mwh": capacity_mwh,
        "power_mw": power_mw,
        "schedule_mw": list(schedule_mw),
        "dispatch": dispatch,
        "soc": {"start": start_soc, "end": end_soc, "track": track},
        "pnl": {
            "benchmark_da_revenue": benchmark_da_revenue,
            "intraday_da_improvement": intraday_da_improvement,
            "execution_costs_paid": execution_costs_paid,
            "degradation_cost": degradation_cost,
            "net_pnl": net_pnl,
        },
        "metrics": {"cycles": cycles, "capture": capture},
    }


def write_day(
    date: dt.date | str,
    day_result: DayResult,
    context: dict[str, float | None],
    labels: list[str],
) -> None:
    """Write ``docs/data/days/<YYYY-MM-DD>.json`` for one settled delivery day.

    Prices are reconstructed from the per-period dispatch log (the day-ahead and
    MID prices the engine settled against are identical across durations), and
    timestamps are generated from the date on the hourly grid.
    """
    durations = day_result.durations
    if not durations:
        raise ValueError("day_result has no durations to write")

    # Prices are the same across durations; take them from the first one.
    reference_log = next(iter(durations.values())).dispatch_log
    n_periods = len(reference_log)
    prices = {
        "timestamps": _timestamps(date, n_periods),
        "da": [entry["da_price_actual"] for entry in reference_log],
        "mid": [entry["mid_price"] for entry in reference_log],
    }

    assets: dict[str, dict] = {}
    for duration, result in durations.items():
        # Power is fixed across the reference batteries; capacity scales with the
        # storage duration (e.g. "4h" -> 4 * power MWh).
        assets[duration] = _asset_block(
            dispatch_log=result.dispatch_log,
            schedule_mw=result.da_schedule,
            end_soc=result.end_soc,
            capacity_mwh=REFERENCE_POWER_MW * _duration_hours(duration),
            power_mw=REFERENCE_POWER_MW,
            benchmark_da_revenue=result.benchmark_da_revenue,
            intraday_da_improvement=result.intraday_da_improvement,
            execution_costs_paid=result.execution_costs_paid,
            degradation_cost=result.degradation_cost,
            net_pnl=result.net_pnl,
            cycles=result.cycles,
            capture=result.capture,
        )

    artifact = {
        "schema_version": schema.SCHEMA_VERSION,
        "date": _date_str(date),
        "resolution_h": RESOLUTION_H,
        "prices": prices,
        "context": {
            "wind_gwh": context.get("wind_gwh"),
            "solar_gwh": context.get("solar_gwh"),
            "demand_gwh": context.get("demand_gwh"),
            "wind_share": context.get("wind_share"),
        },
        "labels": list(labels),
        "assets": assets,
    }
    _atomic_write(_day_path(date), artifact, schema.validate_day)


def read_day(date: dt.date | str) -> dict:
    """Read and validate ``docs/data/days/<YYYY-MM-DD>.json``."""
    day = _read_json(_day_path(date), schema.validate_day)
    if day is None:
        raise FileNotFoundError(f"no day artifact for {_date_str(date)}")
    return day


def list_day_dates() -> list[str]:
    """ISO dates of every stored day artifact, ascending.

    The dates double as the artifact stems, so callers can pass them straight to
    :func:`read_day`. Derived from :data:`DATA_DIR` at call time so a redirected
    data dir (e.g. a ``tmp_path`` in tests) is respected.
    """
    days_dir = _days_dir()
    if not days_dir.exists():
        return []
    return sorted(path.stem for path in days_dir.glob("*.json"))


# --------------------------------------------------------------------------- #
# latest.json
# --------------------------------------------------------------------------- #
def read_latest() -> dict | None:
    """Read and validate ``docs/data/latest.json``, or ``None`` if absent."""
    return _read_json(_latest_path(), schema.validate_latest)


def write_latest(
    date: dt.date | str,
    end_soc: dict[str, float],
    cumulative_net_pnl: dict[str, float],
) -> None:
    """Write ``docs/data/latest.json`` (carry-over SOC + running PnL per duration)."""
    artifact = {
        "schema_version": schema.SCHEMA_VERSION,
        "date": _date_str(date),
        "end_soc": dict(end_soc),
        "cumulative_net_pnl": dict(cumulative_net_pnl),
    }
    _atomic_write(_latest_path(), artifact, schema.validate_latest)


# --------------------------------------------------------------------------- #
# history.json
# --------------------------------------------------------------------------- #
def read_history() -> dict | None:
    """Read and validate ``docs/data/history.json``, or ``None`` if absent."""
    return _read_json(_history_path(), schema.validate_history)


def write_history(rows: list[dict]) -> None:
    """Write ``docs/data/history.json`` from pre-built per-day summary rows."""
    artifact = {"schema_version": schema.SCHEMA_VERSION, "rows": list(rows)}
    _atomic_write(_history_path(), artifact, schema.validate_history)


# --------------------------------------------------------------------------- #
# manifest.json
# --------------------------------------------------------------------------- #
def write_manifest(
    available_dates: list[str],
    durations: list[str],
    reference_asset: dict,
) -> None:
    """Write ``docs/data/manifest.json`` describing the available history."""
    artifact = {
        "schema_version": schema.SCHEMA_VERSION,
        "available_dates": list(available_dates),
        "durations": list(durations),
        "reference_asset": dict(reference_asset),
    }
    _atomic_write(_manifest_path(), artifact, schema.validate_manifest)
