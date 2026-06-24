"""Bulk backfill CLI for the live GB BESS benchmark.

This module replays a contiguous range of historical delivery days into the
committed ``docs/data/`` store, reusing the exact per-day logic of
:func:`live.run_day.run_day`. It exists so a fresh history (or a gap in an
existing one) can be populated in a single bounded pass instead of one
scheduled run per day.

Two properties make the replay correct and cheap:

  * **SOC continuity.** Days are processed strictly oldest-to-newest. Each day
    advances ``latest.json``, so the next day reads the carried-over state of
    charge and running PnL exactly as the live scheduler would — the backfilled
    series is indistinguishable from one built a day at a time.
  * **One roll-up.** :func:`live.aggregate.aggregate` is run once at the very
    end rather than after every day, since it rebuilds ``history.json``,
    ``manifest.json`` and the history-level figures from scratch each time.

By default a date whose artifact already lives under ``docs/data/days/`` is
skipped, so re-running a range only fills the holes; ``--force`` re-settles
every day in the range. No new caching is introduced — the underlying
``src/data`` fetchers' own caches are relied on for repeated reads.

Run as ``python -m live.backfill --start YYYY-MM-DD --end YYYY-MM-DD``. Omitting
``--start`` backfills the last :data:`_DEFAULT_HORIZON_DAYS` days ending at
``--end`` (which itself defaults to yesterday in UTC).
"""

import argparse
import datetime as dt
import logging
import sys
from typing import Iterator

from live import aggregate, io_store, run_day

logger = logging.getLogger(__name__)

# Days backfilled when only ``--end`` (or nothing) is given: the trailing window
# ending at ``--end``, inclusive of both endpoints.
_DEFAULT_HORIZON_DAYS: int = 90


def _yesterday() -> dt.date:
    """Yesterday in UTC — the latest day whose prices are reliably settled."""
    return dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)


def _resolve_range(start: str | None, end: str | None) -> tuple[dt.date, dt.date]:
    """Resolve ``--start``/``--end`` to a concrete inclusive ``(start, end)`` range.

    ``--end`` defaults to yesterday (UTC). ``--start`` defaults to the
    :data:`_DEFAULT_HORIZON_DAYS`-day window ending at ``end``. Both, when given,
    are parsed as ISO ``YYYY-MM-DD`` dates.
    """
    end_date = dt.date.fromisoformat(end) if end is not None else _yesterday()
    if start is not None:
        start_date = dt.date.fromisoformat(start)
    else:
        start_date = end_date - dt.timedelta(days=_DEFAULT_HORIZON_DAYS - 1)
    if start_date > end_date:
        raise ValueError(f"start {start_date} is after end {end_date}")
    return start_date, end_date


def _date_range(start: dt.date, end: dt.date) -> Iterator[dt.date]:
    """Yield every date from ``start`` to ``end`` inclusive, oldest first."""
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def _day_exists(date: dt.date) -> bool:
    """Whether a settled artifact for ``date`` already lives under ``days/``.

    The path is derived from :data:`live.io_store.DATA_DIR` at call time, so
    redirecting that attribute (e.g. to a ``tmp_path`` in tests) is respected.
    """
    return (io_store.DATA_DIR / "days" / f"{date.isoformat()}.json").exists()


def backfill(start: dt.date, end: dt.date, *, force: bool = False) -> dict[str, list[str]]:
    """Replay ``[start, end]`` day by day, then rebuild the roll-up artifacts.

    Returns a summary mapping each outcome — ``"written"`` (a fresh artifact was
    produced), ``"skipped"`` (artifact already present and ``force`` is off) and
    ``"incomplete"`` (the day's prices were not available, so it was a clean
    no-op) — to the ISO dates it covers. :func:`live.aggregate.aggregate` runs
    once after the loop regardless of how many days were written.
    """
    summary: dict[str, list[str]] = {"written": [], "skipped": [], "incomplete": []}
    dates = list(_date_range(start, end))
    logger.info("backfill: start=%s end=%s days=%d force=%s", start, end, len(dates), force)

    for date in dates:
        iso = date.isoformat()
        if not force and _day_exists(date):
            logger.info("day: date=%s status=skipped (artifact exists)", iso)
            summary["skipped"].append(iso)
            continue
        if run_day.run_day(date):
            summary["written"].append(iso)
        else:
            logger.info("day: date=%s status=incomplete (no artifact)", iso)
            summary["incomplete"].append(iso)

    aggregate.aggregate()
    logger.info(
        "backfill done: written=%d skipped=%d incomplete=%d",
        len(summary["written"]),
        len(summary["skipped"]),
        len(summary["incomplete"]),
    )
    return summary


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m live.backfill",
        description="Backfill a date range of delivery days into the live GB BESS store.",
    )
    parser.add_argument(
        "--start",
        default=None,
        help=(
            "First delivery day as YYYY-MM-DD "
            f"(default: {_DEFAULT_HORIZON_DAYS} days before --end)."
        ),
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Last delivery day as YYYY-MM-DD (default: yesterday, UTC).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-settle days whose artifact already exists (default: skip them).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exits ``0`` on success, non-zero on any unhandled error."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    try:
        start, end = _resolve_range(args.start, args.end)
        backfill(start, end, force=args.force)
    except Exception:
        logger.exception("backfill failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
