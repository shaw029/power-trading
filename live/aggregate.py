"""Rebuild the history-level artifacts and figures from all stored day files.

This module is the roll-up layer for the live GB BESS benchmark. The per-day
artifacts under ``docs/data/days/*.json`` are the single source of truth; this
CLI scans every one of them and rebuilds, from scratch on each run:

  * ``docs/data/history.json`` — one compact summary row per day (Appendix A).
  * ``docs/data/manifest.json`` — the available dates, durations and the shared
    reference-asset parameters.
  * the four history-level Plotly figures under ``docs/data/figs/_history/``
    (equity curve, duration comparison, day-type scatter, day-type profiles).

The history/manifest artifacts are written through :mod:`live.io_store`
(``write_history`` / ``write_manifest``), so they inherit its atomic
write-validate-replace guarantee; the figures are written with the same
temp-file-plus-``os.replace`` pattern here.

The CLI is idempotent: it always rebuilds from the day files and emits a stable,
ascending-by-date ordering regardless of the order the filesystem lists them, so
repeated runs over an unchanged ``days/`` tree produce identical output.
"""

import os
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.io as pio

from dashboard.charts import (
    chart_daytype_profiles,
    chart_daytype_scatter,
    chart_duration_comparison,
    chart_equity_curve,
)
from live import io_store
from live.assets import REFERENCE_DURATIONS, REFERENCE_POWER_MW, bess_config

# Duration whose per-day figures (scatter, profiles) the history charts key off.
# Mirrors :data:`live.figures.DEFAULT_DURATION` so the day-level and
# history-level views describe the same reference battery.
REFERENCE_DURATION: str = "2h"

# Day-type bucket used when a day carries no descriptive labels.
_UNTAGGED: str = "untagged"


# --------------------------------------------------------------------------- #
# Paths and atomic figure write
# --------------------------------------------------------------------------- #
def _history_figs_dir() -> Path:
    """Directory holding the history-level figures.

    Derived from :data:`live.io_store.DATA_DIR` at call time so redirecting that
    attribute (e.g. to a ``tmp_path`` in tests) also redirects the figures.
    """
    return io_store.DATA_DIR / "figs" / "_history"


def _atomic_write_figure(path: Path, fig_json: str) -> None:
    """Write ``fig_json`` to ``<path>.tmp``, re-load it to validate, then replace.

    On any failure the temp file is removed and ``path`` is left untouched, so a
    valid existing figure is never overwritten by a malformed one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(fig_json)
        with open(tmp, "r", encoding="utf-8") as handle:
            pio.from_json(handle.read())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


# --------------------------------------------------------------------------- #
# Load day artifacts
# --------------------------------------------------------------------------- #
def _load_days() -> list[dict[str, Any]]:
    """Read and validate every ``days/*.json`` artifact, sorted ascending by date.

    Sorting is on the artifact's own ``date`` field rather than the filesystem
    listing, so the ordering is stable across runs and platforms.
    """
    days_dir = io_store.DATA_DIR / "days"
    if not days_dir.exists():
        return []
    days = [io_store.read_day(path.stem) for path in days_dir.glob("*.json")]
    return sorted(days, key=lambda day: day["date"])


def _ordered_durations(days: list[dict[str, Any]]) -> list[str]:
    """Durations present across all days, ordered by the canonical reference order.

    Any duration not in :data:`live.assets.REFERENCE_DURATIONS` is appended after
    the known ones, sorted by name, so the ordering stays deterministic.
    """
    present = {duration for day in days for duration in day["assets"]}
    known = [d for d in REFERENCE_DURATIONS if d in present]
    extra = sorted(present.difference(REFERENCE_DURATIONS))
    return known + extra


def _da_spread(day: dict[str, Any]) -> float | None:
    """Peak-to-trough day-ahead price spread for a day, or ``None`` if no prices."""
    da = day["prices"]["da"]
    if not da:
        return None
    return float(max(da)) - float(min(da))


def _day_type(labels: list[str]) -> str:
    """Single categorical day-type for grouping: first label, else ``untagged``."""
    return labels[0] if labels else _UNTAGGED


# --------------------------------------------------------------------------- #
# history.json / manifest.json
# --------------------------------------------------------------------------- #
def _history_rows(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build one compact history row per day (Appendix A ``history.json`` shape)."""
    rows: list[dict[str, Any]] = []
    for day in days:
        assets = day["assets"]
        context = day["context"]
        rows.append(
            {
                "date": day["date"],
                "da_spread": _da_spread(day),
                "labels": list(day["labels"]),
                "wind_share": context.get("wind_share"),
                "demand_gwh": context.get("demand_gwh"),
                "net_pnl": {dur: assets[dur]["pnl"]["net_pnl"] for dur in assets},
                "cycles": {dur: assets[dur]["metrics"]["cycles"] for dur in assets},
            }
        )
    return rows


def _reference_asset() -> dict[str, Any]:
    """Shared reference-battery parameters for ``manifest.json`` (Appendix A)."""
    cfg = bess_config()
    return {
        "power_mw": REFERENCE_POWER_MW,
        "round_trip_eff": cfg["charge_efficiency"] * cfg["discharge_efficiency"],
        "soc_band": [cfg["min_soc_pct"], cfg["max_soc_pct"]],
        "degradation_cost_per_mwh": cfg["degradation_cost_per_mwh"],
        "target_daily_cycles": cfg["target_daily_cycles"],
    }


# --------------------------------------------------------------------------- #
# History-level figure frames
# --------------------------------------------------------------------------- #
def _equity_frame(days: list[dict[str, Any]]) -> pd.DataFrame:
    """One row per (date, duration) carrying that day's net PnL."""
    rows = [
        {"date": day["date"], "duration": dur, "net_pnl": asset["pnl"]["net_pnl"]}
        for day in days
        for dur, asset in day["assets"].items()
    ]
    return pd.DataFrame(rows, columns=["date", "duration", "net_pnl"])


def _duration_frame(days: list[dict[str, Any]], durations: list[str]) -> pd.DataFrame:
    """One row per duration: net PnL summed over every day."""
    totals = {dur: 0.0 for dur in durations}
    for day in days:
        for dur, asset in day["assets"].items():
            totals[dur] += asset["pnl"]["net_pnl"]
    rows = [{"duration": dur, "net_pnl": totals[dur]} for dur in durations]
    return pd.DataFrame(rows, columns=["duration", "net_pnl"])


def _scatter_frame(days: list[dict[str, Any]]) -> pd.DataFrame:
    """One point per day: DA spread vs the reference duration's net PnL, by day-type.

    Days without the reference duration are skipped so every point compares the
    same battery.
    """
    rows = [
        {
            "da_spread": _da_spread(day),
            "net_pnl": day["assets"][REFERENCE_DURATION]["pnl"]["net_pnl"],
            "day_type": _day_type(day["labels"]),
        }
        for day in days
        if REFERENCE_DURATION in day["assets"]
    ]
    return pd.DataFrame(rows, columns=["da_spread", "net_pnl", "day_type"])


def _profiles_frame(days: list[dict[str, Any]]) -> pd.DataFrame:
    """Per (day, hour) SOC for the reference duration, tagged with the day-type.

    Hour-of-day is read from the price timestamps so partial days line up on the
    same clock. The chart builder averages SOC across days within each day-type.
    """
    rows: list[dict[str, Any]] = []
    for day in days:
        if REFERENCE_DURATION not in day["assets"]:
            continue
        day_type = _day_type(day["labels"])
        timestamps = pd.to_datetime(day["prices"]["timestamps"])
        track = day["assets"][REFERENCE_DURATION]["soc"]["track"]
        for ts, soc in zip(timestamps, track):
            rows.append({"hour": int(ts.hour), "soc": soc, "day_type": day_type})
    return pd.DataFrame(rows, columns=["hour", "soc", "day_type"])


def _write_history_figures(days: list[dict[str, Any]], durations: list[str]) -> dict[str, Path]:
    """Rebuild and atomically write the four history-level figures."""
    figs_dir = _history_figs_dir()
    figures = {
        "equity": (figs_dir / "equity.json", chart_equity_curve(_equity_frame(days))),
        "duration_comparison": (
            figs_dir / "duration_comparison.json",
            chart_duration_comparison(_duration_frame(days, durations)),
        ),
        "daytype_scatter": (
            figs_dir / "daytype_scatter.json",
            chart_daytype_scatter(_scatter_frame(days)),
        ),
        "daytype_profiles": (
            figs_dir / "daytype_profiles.json",
            chart_daytype_profiles(_profiles_frame(days)),
        ),
    }
    outputs: dict[str, Path] = {}
    for name, (path, fig) in figures.items():
        _atomic_write_figure(path, fig.to_json())
        outputs[name] = path
    return outputs


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def aggregate() -> dict[str, Any]:
    """Rebuild ``history.json``, ``manifest.json`` and the history-level figures.

    Returns a small summary: the dates rolled up, the durations seen and the
    figure paths written.
    """
    days = _load_days()
    durations = _ordered_durations(days)
    dates = [day["date"] for day in days]

    io_store.write_history(_history_rows(days))
    io_store.write_manifest(
        available_dates=dates,
        durations=durations,
        reference_asset=_reference_asset(),
    )
    figures = _write_history_figures(days, durations)

    return {"dates": dates, "durations": durations, "figures": figures}


def main() -> None:
    """CLI entry point: rebuild every roll-up artifact and report what was built."""
    summary = aggregate()
    n_days = len(summary["dates"])
    print(f"Aggregated {n_days} day(s) over durations {summary['durations']}.")
    print("Wrote history.json, manifest.json and history-level figures:")
    for name, path in summary["figures"].items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
