"""Rebuild a single day's dispatch and PnL-waterfall figures from a stored artifact.

This module is the figure-export layer for the live GB BESS benchmark. It reads a
committed per-day artifact (via :func:`live.io_store.read_day`), reshapes its
``assets.<duration>`` and ``prices`` blocks into the frames the *existing*
``dashboard.charts`` builders already expect, calls those unchanged builders, and
writes each figure to ``docs/data/figs/<date>/`` as Plotly JSON.

It performs no calculation and no network IO: given a day artifact the output is
fully deterministic. Each figure is written atomically — serialised to a sibling
``.tmp`` file, re-loaded with :func:`plotly.io.from_json` to prove it is valid,
and only then ``os.replace``-d over the target — so a malformed figure is never
published.

The artifact stores no ex-ante day-ahead *price* forecast (the live pipeline
settles against realised prices), so the explorer's "DA Forecast" line is fed the
realised day-ahead price; the dashed forecast therefore overlays the solid line.
"""

import os
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.io as pio

from dashboard.charts import chart_operation_explorer, chart_pnl_waterfall
from live import io_store

# Duration whose dispatch the figures are rebuilt for, unless overridden.
DEFAULT_DURATION: str = "2h"


# --------------------------------------------------------------------------- #
# Paths and atomic write
# --------------------------------------------------------------------------- #
def _figs_dir(date: str) -> Path:
    """Directory holding one delivery day's exported figures.

    Derived from :data:`live.io_store.DATA_DIR` at call time so that redirecting
    that attribute (e.g. to a ``tmp_path`` in tests) also redirects the figures.
    """
    return io_store.DATA_DIR / "figs" / date


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
# Artifact -> chart-builder frames
# --------------------------------------------------------------------------- #
def _prices_hourly(prices: dict[str, Any]) -> pd.DataFrame:
    """Timestamp-indexed price frame the builders expect (``day_ahead_price`` / ``mid_price``)."""
    index = pd.to_datetime(prices["timestamps"])
    return pd.DataFrame(
        {"day_ahead_price": prices["da"], "mid_price": prices["mid"]},
        index=index,
    )


def _dispatch_df(asset: dict[str, Any], timestamps: list[str]) -> pd.DataFrame:
    """Per-period dispatch frame keyed by timestamp via each entry's ``period`` index."""
    rows = [
        {
            "timestamp": timestamps[entry["period"]],
            "da_mw": entry["da_mw"],
            "intraday_mw": entry["intraday_mw"],
            "soc_after": entry["soc_after"],
        }
        for entry in asset["dispatch"]
    ]
    return pd.DataFrame(rows)


def _da_sched_df(asset: dict[str, Any], prices: dict[str, Any]) -> pd.DataFrame:
    """Day-ahead schedule frame: committed MW plus the (realised) day-ahead price line."""
    timestamps = prices["timestamps"]
    rows = [
        {
            "timestamp": timestamps[period],
            "da_mw": mw,
            "da_price_pred": prices["da"][period],
        }
        for period, mw in enumerate(asset["schedule_mw"])
    ]
    return pd.DataFrame(rows)


def _results_df(asset: dict[str, Any]) -> pd.DataFrame:
    """Single-row results frame the waterfall builder sums over."""
    return pd.DataFrame([asset["pnl"]])


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def write_day_figures(
    date: str,
    duration: str = DEFAULT_DURATION,
) -> dict[str, Path]:
    """Rebuild and export one day's dispatch and PnL-waterfall figures.

    Reads ``docs/data/days/<date>.json``, reshapes the chosen ``duration``'s
    asset block into the frames the existing chart builders expect, and writes
    ``docs/data/figs/<date>/dispatch.json`` and ``.../waterfall.json``.

    Returns a mapping of figure name to the path it was written to.
    """
    day = io_store.read_day(date)
    date_str = day["date"]

    assets = day["assets"]
    if duration not in assets:
        raise KeyError(f"day {date_str} has no '{duration}' asset; available: {sorted(assets)}")
    asset = assets[duration]
    prices = day["prices"]
    timestamps = prices["timestamps"]

    dispatch_fig = chart_operation_explorer(
        prices_hourly=_prices_hourly(prices),
        dispatch_df=_dispatch_df(asset, timestamps),
        da_sched_df=_da_sched_df(asset, prices),
    )
    waterfall_fig = chart_pnl_waterfall(_results_df(asset))

    figs_dir = _figs_dir(date_str)
    outputs = {
        "dispatch": figs_dir / "dispatch.json",
        "waterfall": figs_dir / "waterfall.json",
    }
    _atomic_write_figure(outputs["dispatch"], dispatch_fig.to_json())
    _atomic_write_figure(outputs["waterfall"], waterfall_fig.to_json())
    return outputs
