"""Build the tidy intermediate store behind notebook 05 (stress-response study).

The study window is ~1,050 days across eight public feeds, so the raw fetch is
thousands of day-cached HTTP calls — hours on a cold cache. This module does
that fetch once, day by day and failure-tolerant, and writes a handful of tidy
parquet tables the notebook's analysis cells load in seconds.

Acquisition, reshaping and coverage accounting only — no analysis. Every feed
reuses the repository's existing fetchers, so nothing re-implements HTTP or
caching:

  * ``system``         — :func:`live.fetch_live.get_day_system` + residual load
  * ``lolpdrm_prints`` — :func:`src.data.download.fetch_lolpdrm`, **every**
    forecast-horizon print (the notebook's foresight section needs all five)
  * ``fleet_pn/mels/mils`` — the per-BMU fleet streams, reshaped per site
  * ``sbp``            — B1770 cashout prices, assembled once for the window
  * ``cmn``            — the Capacity Market Notice register
  * ``coverage``       — one row per day per feed, so every later statistic can
    state what it is missing rather than silently averaging over gaps

Days that fail are recorded and skipped, never fatal: the day-file caches make
a re-run incremental, so the fix for a partial build is to run it again.

CLI::

    python scripts/build_stress_store.py --start 2023-10-01 --end 2026-08-16
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Callable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fleet import fetch_fleet  # noqa: E402
from fleet import performance as fleet_perf  # noqa: E402
from live import fetch_live, resilience  # noqa: E402
from src.data.download import (  # noqa: E402
    download_b1770,
    fetch_imbalance_price,
    fetch_lolpdrm,
)
from src.data.preprocess import process_imbalance_price  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_STORE = REPO_ROOT / "data" / "processed" / "stress_study"

# Tables written to the store. ``sbp``/``cmn`` are assembled once for the whole
# window rather than per day, so they are not in DAY_FEEDS below.
TABLES = (
    "system",
    "lolpdrm_prints",
    "fleet_pn",
    "fleet_mels",
    "fleet_mils",
    "sbp",
    "cmn",
    "coverage",
)


def window_days(start: dt.date, end: dt.date) -> list[dt.date]:
    """Inclusive list of settlement days in ``[start, end]``."""
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _day_system(date: dt.date) -> pd.DataFrame:
    """Half-hourly demand / wind / solar plus residual load for one day."""
    system = fetch_live.get_day_system(date)
    if system.empty:
        raise ValueError("no system data")
    out = pd.DataFrame(index=system.index)
    for col in ("demand_actual", "gen_WIND", "solar_mw"):
        out[col] = system[col] if col in system.columns else float("nan")
    out["residual_mw"] = resilience.residual_load(system)
    return out.rename_axis("time").reset_index()


def _day_lolpdrm_prints(date: dt.date) -> pd.DataFrame:
    """Every LoLP/DRM print for one day — one row per (period, horizon)."""
    raw = fetch_lolpdrm(date.isoformat(), date.isoformat())
    if raw.empty:
        raise ValueError("no LoLP/DRM prints")
    return pd.DataFrame(
        {
            "time": pd.to_datetime(raw["startTime"], utc=True),
            "publish_time": pd.to_datetime(raw["publishTime"], utc=True),
            "settlement_period": pd.to_numeric(raw["settlementPeriod"], errors="coerce"),
            "horizon": pd.to_numeric(raw["forecastHorizon"], errors="coerce"),
            "lolp": pd.to_numeric(raw["lossOfLoadProbability"], errors="coerce"),
            "drm_mw": pd.to_numeric(raw["deratedMargin"], errors="coerce"),
        }
    )


def _require(profile: pd.DataFrame, what: str) -> pd.DataFrame:
    if profile.empty:
        raise ValueError(f"no {what}")
    return profile


def _day_pn(date: dt.date) -> pd.DataFrame:
    return _require(fleet_perf.site_profile(fetch_fleet.fetch_fleet_pn(date)), "PN")


def _day_mels(date: dt.date) -> pd.DataFrame:
    return _require(
        fleet_perf.site_limit_profile(fetch_fleet.fetch_fleet_mels(date)), "MELS"
    )


def _day_mils(date: dt.date) -> pd.DataFrame:
    return _require(
        fleet_perf.site_limit_profile(fetch_fleet.fetch_fleet_mils(date)), "MILS"
    )


# Per-day feeds: table name → (fetch function, parquet table).
DAY_FEEDS: dict[str, tuple[Callable[[dt.date], pd.DataFrame], str]] = {
    "system": (_day_system, "system"),
    "lolpdrm": (_day_lolpdrm_prints, "lolpdrm_prints"),
    "pn": (_day_pn, "fleet_pn"),
    "mels": (_day_mels, "fleet_mels"),
    "mils": (_day_mils, "fleet_mils"),
}


def _assemble_sbp(days: list[dt.date]) -> pd.DataFrame:
    """Cashout prices for the window, clipped to it.

    ``download_b1770`` is day-cached and swallows per-day failures itself, so
    it is called once for the range. ``fetch_imbalance_price`` then globs the
    *whole* ``B1770/`` cache (which may hold unrelated pipeline years), hence
    the explicit clip back to the study window.
    """
    start, end = days[0], days[-1]
    download_b1770(start.isoformat(), end.isoformat())
    raw = fetch_imbalance_price("ELEXON", start.isoformat(), end.isoformat())
    if raw.empty:
        return pd.DataFrame(columns=["time", "system_buy_price", "niv"])
    prices = process_imbalance_price(raw)
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    prices = prices[(prices.index >= lo) & (prices.index < hi)]
    cols = [c for c in ("system_buy_price", "niv") if c in prices.columns]
    return prices[cols].rename_axis("time").reset_index()


def _assemble_cmn(days: list[dt.date]) -> pd.DataFrame:
    """Issued Capacity Market Notices overlapping the window.

    An issued notice normally carries no end time (the register stamps that on
    cancellation), so an open notice is treated as covering its target
    settlement period — the same rule as :func:`live.resilience.cmn_flags`.
    """
    notices = fetch_live.get_cmn_notices()
    if notices.empty:
        return notices
    issued = notices[notices["type_id"] == fetch_live.CMN_ISSUE_TYPE].copy()
    if issued.empty:
        return issued
    lo = pd.Timestamp(days[0], tz="UTC")
    hi = pd.Timestamp(days[-1], tz="UTC") + pd.Timedelta(days=1)
    eff_end = issued["end_utc"].fillna(issued["start_utc"] + pd.Timedelta(minutes=30))
    return issued[(issued["start_utc"] < hi) & (eff_end > lo)].reset_index(drop=True)


def store_is_current(store: Path, days: list[dt.date]) -> bool:
    """True when ``store`` already holds a complete build for this window."""
    manifest = store / "manifest.json"
    if not manifest.exists():
        return False
    try:
        meta = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return False
    return (
        meta.get("window_start") == days[0].isoformat()
        and meta.get("window_end") == days[-1].isoformat()
        and all((store / f"{t}.parquet").exists() for t in TABLES)
    )


def build_store(
    days: list[dt.date],
    store: Path = DEFAULT_STORE,
    force: bool = False,
    progress_every: int = 25,
    log: Callable[[str], None] = print,
) -> dict:
    """Fetch every feed over ``days`` and write the tidy store.

    Returns a summary dict (row counts, failures, coverage shape). Existing
    complete stores are reused unless ``force`` is set; the underlying day-file
    caches mean a re-run after a partial build only re-hits the failed days.
    """
    store = Path(store)
    if not force and store_is_current(store, days):
        log(f"Store already current for {days[0]} → {days[-1]} — nothing to do.")
        return {"skipped": True, "store": str(store)}

    store.mkdir(parents=True, exist_ok=True)
    parts: dict[str, list[pd.DataFrame]] = {name: [] for name in DAY_FEEDS}
    coverage_rows: list[dict] = []
    failures: list[tuple[str, str, str]] = []

    log(f"Building store for {len(days)} days: {days[0]} → {days[-1]}")
    for i, date in enumerate(days):
        row: dict = {"date": date.isoformat()}
        for feed, (fetch, _table) in DAY_FEEDS.items():
            try:
                frame = fetch(date)
                parts[feed].append(frame)
                row[feed] = True
            except Exception as exc:  # one bad feed never stops the build
                failures.append((date.isoformat(), feed, repr(exc)))
                row[feed] = False
        coverage_rows.append(row)
        if progress_every and i % progress_every == 0:
            done = {f: sum(r[f] for r in coverage_rows) for f in DAY_FEEDS}
            log(f"  {date}  [{i + 1}/{len(days)}]  ok={done}  failures={len(failures)}")

    for feed, (_fetch, table) in DAY_FEEDS.items():
        frames = parts[feed]
        combined = (
            pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        )
        combined.to_parquet(store / f"{table}.parquet", index=False)
        log(f"  wrote {table}.parquet  rows={len(combined):,}")

    sbp = _assemble_sbp(days)
    sbp.to_parquet(store / "sbp.parquet", index=False)
    log(f"  wrote sbp.parquet  rows={len(sbp):,}")

    cmn = _assemble_cmn(days)
    cmn.to_parquet(store / "cmn.parquet", index=False)
    log(f"  wrote cmn.parquet  rows={len(cmn):,}")

    coverage = pd.DataFrame(coverage_rows)
    # SBP/CMN are window-level assemblies, so their coverage is per-day derived
    # from the assembled frames rather than from the fetch loop.
    sbp_days = set(pd.to_datetime(sbp["time"]).dt.date) if not sbp.empty else set()
    coverage["sbp"] = [dt.date.fromisoformat(d) in sbp_days for d in coverage["date"]]
    coverage.to_parquet(store / "coverage.parquet", index=False)

    manifest = {
        "window_start": days[0].isoformat(),
        "window_end": days[-1].isoformat(),
        "built_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "days": len(days),
        "failures": len(failures),
        "rows": {t: int(len(pd.read_parquet(store / f"{t}.parquet"))) for t in TABLES},
    }
    (store / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if failures:
        (store / "failures.json").write_text(json.dumps(failures, indent=2))
    log(f"Done. failures={len(failures)}  store={store}")
    # The manifest records a failure *count*; the returned summary carries the
    # detail, so it is spread first and then overridden.
    return {"skipped": False, "store": str(store), **manifest, "failures": failures}


def load_store(store: Path = DEFAULT_STORE) -> dict[str, pd.DataFrame]:
    """Load the tidy tables. ``system``/``sbp`` come back time-indexed."""
    store = Path(store)
    out: dict[str, pd.DataFrame] = {}
    for table in TABLES:
        frame = pd.read_parquet(store / f"{table}.parquet")
        if table in ("system", "sbp") and "time" in frame.columns:
            frame = frame.set_index(pd.DatetimeIndex(frame["time"], name="time"))
            frame = frame.drop(columns=["time"]).sort_index()
            frame = frame[~frame.index.duplicated(keep="first")]
        out[table] = frame
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-10-01", help="First settlement day")
    parser.add_argument(
        "--end",
        default=(dt.date.today() - dt.timedelta(days=1)).isoformat(),
        help="Last settlement day (inclusive)",
    )
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    days = window_days(
        dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    )
    build_store(days, Path(args.store), force=args.force)


if __name__ == "__main__":
    main()
