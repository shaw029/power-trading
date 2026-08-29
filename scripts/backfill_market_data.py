"""Backfill the raw feed caches over a long analysis window.

The notebooks and the live dashboard read the same day-file caches under
``RAW_DATA_DIR``, but they need very different amounts of them. The live
dashboard runs on a rolling ~60 days, so its feeds have only ever been fetched
for ~60 days; the research notebooks reach back to 2023-10-01. The result is a
window where the fleet's Physical Notifications span three years while the MID
price they are valued against spans three months — and a capture spread
averaged over that pair is silently averaged over the three months.

This script closes that gap. It fetches only the days a feed is actually
missing, reusing the repository's existing fetchers so nothing re-implements
HTTP, caching or pagination:

  * ``MID``, ``WINDFOR``      — :func:`src.data.download.download_elexon_dataset`
  * ``B1770``                 — :func:`src.data.download.download_b1770`
  * ``NESO_NDFD``             — :func:`src.data.download.download_neso_ndfd_range`
  * ``LOLPDRM``               — :func:`src.data.download.fetch_lolpdrm`
  * ``PVLIVE_SOLAR``          — :func:`src.data.download.fetch_solar_actual`
  * ``ITSDO``, ``FUELHH``     — :func:`src.data.download.download_elexon_dataset`
  * ``FLEET_*``               — the per-BMU fleet streams in :mod:`fleet.fetch_fleet`

Three properties matter for a run measured in hours:

**Resumable.** Work is derived from :mod:`src.data.coverage`, which reads the
filesystem, so an interrupted run re-planned on the next invocation costs
nothing but the days it had not reached.

**Failure-tolerant.** A day that fails is recorded and skipped, never fatal.
A feed publishes late, an endpoint rate-limits, a settlement day is genuinely
absent — none of those should cost the other thousand days.

**Honest.** Coverage is printed before and after, per feed, so the run ends
with a statement of what the analysis window actually contains rather than an
assumption that it is now complete.

The per-BMU fleet feeds are fetched for whichever population
``fleet.fetch_fleet`` is pointed at, so this script does not need to change when
a tier's population does. The dashboard's own ``REGISTRY`` day-files are fetched
by the dashboard on demand and are not backfilled here.

CLI::

    python scripts/backfill_market_data.py --report-only
    python scripts/backfill_market_data.py --start 2023-10-01 --end 2026-08-19
    python scripts/backfill_market_data.py --feeds MID,WINDFOR,NESO_NDFD
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fleet import fetch_fleet  # noqa: E402
from fleet.curated import CURATED  # noqa: E402
from fleet.population import Population, census_population  # noqa: E402
from src.data import coverage as cov  # noqa: E402
from src.data.download import (  # noqa: E402
    download_b1770,
    download_elexon_dataset,
    download_neso_ndfd_range,
    fetch_lolpdrm,
    fetch_solar_actual,
)

logger = logging.getLogger("backfill")


class FeedResult(TypedDict):
    """What one feed's backfill did: how many days it asked for, and what failed."""

    feed: str
    requested: int
    failures: list[str]


DEFAULT_START = dt.date(2023, 10, 1)


def _elexon_day(dataset: str) -> Callable[..., Any]:
    """Day-at-a-time wrapper around the range-based Elexon downloader.

    ``download_elexon_dataset`` loops over dates itself and raises on the first
    HTTP failure. Driving it one day per call turns that into a per-day failure
    the caller can record and step over.
    """

    def fetch(day: dt.date) -> None:
        download_elexon_dataset(dataset, day.isoformat(), day.isoformat())

    return fetch


def _b1770_day(day: dt.date) -> None:
    download_b1770(day.isoformat(), day.isoformat())


def _lolpdrm_day(day: dt.date) -> None:
    fetch_lolpdrm(day.isoformat(), day.isoformat())


def _pvlive_day(day: dt.date) -> None:
    fetch_solar_actual(day.isoformat(), day.isoformat())


#: Feeds fetched one settlement day per call. Every value takes a date and
#: writes that day's cache file; the caller decides which days to ask for.
DAY_FETCHERS: dict[str, Callable[..., Any]] = {
    "MID": _elexon_day("MID"),
    "WINDFOR": _elexon_day("WINDFOR"),
    "ITSDO": _elexon_day("ITSDO"),
    "FUELHH": _elexon_day("FUELHH"),
    "B1770": _b1770_day,
    "LOLPDRM": _lolpdrm_day,
    "PVLIVE_SOLAR": _pvlive_day,
    "FLEET_PN": fetch_fleet.fetch_fleet_pn,
    "FLEET_BOALF": fetch_fleet.fetch_fleet_boalf,
    "FLEET_EBOCF": fetch_fleet.fetch_fleet_bm_cashflows,
    "FLEET_MELS": fetch_fleet.fetch_fleet_mels,
    "FLEET_MILS": fetch_fleet.fetch_fleet_mils,
}

#: Feeds cheaper to fetch as a range than day by day. NDFD's whole resource is
#: only tens of thousands of rows, so a thousand serial day calls would spend
#: all their time on latency.
RANGE_FETCHERS: dict[str, Callable[..., Any]] = {
    "NESO_NDFD": download_neso_ndfd_range,
}

#: Fetched by default. NORDPOOL_DA is excluded deliberately: the Nord Pool
#: portal only serves a rolling ~65-day window, so its history cannot be
#: backfilled at all and asking would just log a thousand failures.
DEFAULT_FEEDS = tuple(DAY_FETCHERS) + tuple(RANGE_FETCHERS)

#: The per-BMU feeds, which are the only ones whose content depends on the
#: population. Everything else (prices, system state, forecasts) is market-wide
#: and identical whichever fleet is being analysed, so it is never re-fetched.
PER_BMU_FEEDS = ("FLEET_PN", "FLEET_BOALF", "FLEET_EBOCF", "FLEET_MELS", "FLEET_MILS")


def population_fetchers(population: Population) -> dict[str, Callable[..., Any]]:
    """Day fetchers bound to ``population``, keyed by that population's feed names.

    For the curated registry this is the module-level table unchanged. For the
    census it binds the population into each fetcher and renames the feeds to the
    ``*_CENSUS`` cache directories, so coverage accounting never confuses one
    population's day-files for the other's.
    """
    if population is CURATED or not population.cache_suffix:
        return dict(DAY_FETCHERS)

    bound: dict[str, Callable[..., Any]] = {
        f"{feed}{population.cache_suffix}": functools.partial(
            DAY_FETCHERS[feed], population=population
        )
        for feed in PER_BMU_FEEDS
    }
    return bound


def backfill_feed(
    feed: str,
    start: dt.date,
    end: dt.date,
    pause_s: float = 0.0,
    fetchers: dict[str, Callable[..., Any]] | None = None,
) -> FeedResult:
    """Fetch every missing day of one feed. Returns a per-feed result record.

    Days already cached are never re-requested, and a day that raises is
    recorded in ``failures`` rather than propagating.
    """
    fetchers = fetchers or DAY_FETCHERS
    if feed in RANGE_FETCHERS:
        missing = cov.missing_days(feed, start, end)
        if not missing:
            logger.info("%-14s complete — nothing to fetch", feed)
            return {"feed": feed, "requested": 0, "failures": []}
        logger.info("%-14s %d missing days — fetching as a range", feed, len(missing))
        try:
            RANGE_FETCHERS[feed](start.isoformat(), end.isoformat())
        except Exception as exc:  # noqa: BLE001 - one feed must not sink the run
            logger.error("%-14s range fetch failed: %s", feed, exc)
            return {"feed": feed, "requested": len(missing), "failures": [str(exc)]}
        return {"feed": feed, "requested": len(missing), "failures": []}

    missing = cov.missing_days(feed, start, end)
    if not missing:
        logger.info("%-14s complete — nothing to fetch", feed)
        return {"feed": feed, "requested": 0, "failures": []}

    logger.info("%-14s %d missing days — fetching", feed, len(missing))
    fetch = (fetchers or DAY_FETCHERS)[feed]
    failures: list[str] = []
    started = time.monotonic()

    for i, day in enumerate(missing, start=1):
        try:
            fetch(day)
        except Exception as exc:  # noqa: BLE001 - a late-publishing day is normal
            failures.append(f"{day.isoformat()}: {exc}")
            logger.warning("%-14s %s failed: %s", feed, day, exc)
        if pause_s:
            time.sleep(pause_s)
        if i % 50 == 0 or i == len(missing):
            rate = i / max(time.monotonic() - started, 1e-9)
            remaining = (len(missing) - i) / rate if rate else 0
            logger.info(
                "%-14s %d/%d days (%.1f/s, ~%.0f min left, %d failed)",
                feed,
                i,
                len(missing),
                rate,
                remaining / 60,
                len(failures),
            )

    return {"feed": feed, "requested": len(missing), "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=DEFAULT_START.isoformat())
    parser.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    parser.add_argument(
        "--feeds",
        default=",".join(DEFAULT_FEEDS),
        help="Comma-separated feed names; default is every backfillable feed.",
    )
    parser.add_argument(
        "--population",
        choices=("curated", "census"),
        default="curated",
        help=(
            "Which battery population to fetch per-BMU feeds for. 'registry' is "
            "the curated 23 sites the dashboard uses; 'census' is every "
            "BM-registered battery, for the research notebooks."
        ),
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print the coverage table and exit without fetching anything.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.0,
        help="Seconds to sleep between day requests, if an endpoint rate-limits.",
    )
    parser.add_argument(
        "--failures-out",
        default=str(REPO_ROOT / "data" / "processed" / "backfill_failures.json"),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("src.data.download").setLevel(logging.WARNING)
    logging.getLogger("fleet.fetch_fleet").setLevel(logging.WARNING)

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)

    population = CURATED if args.population == "curated" else census_population()
    fetchers = population_fetchers(population)
    logger.info(
        "Population '%s': %d sites, %d BM Units", population.name,
        len(population), len(population.bmu_ids()),
    )

    if args.feeds == parser.get_default("feeds") and population.cache_suffix:
        # A census run defaults to the per-BMU feeds only; the market-wide ones
        # are population-independent and already complete.
        feeds = list(fetchers)
    else:
        feeds = [f.strip() for f in args.feeds.split(",") if f.strip()]

    known = set(fetchers) | set(RANGE_FETCHERS)
    unknown = [f for f in feeds if f not in known]
    if unknown:
        raise SystemExit(f"Unknown feed(s): {unknown}. Known: {sorted(known)}")

    print(f"\nCoverage before — {start} to {end} ({(end - start).days + 1} days)\n")
    print(cov.coverage_summary(start, end).to_string())

    if args.report_only:
        return

    results: list[FeedResult] = []
    for feed in feeds:
        results.append(
            backfill_feed(feed, start, end, pause_s=args.pause, fetchers=fetchers)
        )

    print(f"\nCoverage after — {start} to {end}\n")
    print(cov.coverage_summary(start, end).to_string())

    failures: dict[str, list[str]] = {
        r["feed"]: r["failures"] for r in results if r["failures"]
    }
    out = Path(args.failures_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(failures, indent=2))
    total = sum(len(v) for v in failures.values())
    print(f"\n{total} day-level failures across {len(failures)} feed(s) — detail in {out}")


if __name__ == "__main__":
    main()
