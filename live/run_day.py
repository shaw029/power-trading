"""Single-day orchestration CLI for the live GB BESS benchmark.

This module ties the per-day pieces of the live benchmark together for one
delivery day:

  1. Resolve the carry-over SOC (and running PnL) from the previous day via
     :func:`live.io_store.read_latest` — defaulting to a half-charged battery
     when no history exists yet.
  2. Fetch the day's prices and tier-2 context (:mod:`live.fetch_live`).
  3. Settle all reference durations (:func:`live.settle.settle_day`).
  4. Classify the day's character (:func:`live.classify.classify`).
  5. Persist the per-day artifact and advance ``latest.json``
     (:func:`live.io_store.write_day` / :func:`live.io_store.write_latest`).

It is built to run headless inside CI: no interactive prompts, structured
one-line logging per step, idempotent per date (re-running a date overwrites its
artifact cleanly), and a clean exit ``0`` with nothing written when the day's
price data is incomplete or not yet available.

Run as ``python -m live.run_day --date YYYY-MM-DD`` (``--date yesterday`` is also
accepted; omitting ``--date`` defaults to yesterday in UTC).
"""

import argparse
import datetime as dt
import logging
import sys

from live import classify as classify_mod
from live import fetch_live, io_store
from live.assets import REFERENCE_DURATIONS, bess_config, build_assets
from live.settle import settle_day

logger = logging.getLogger(__name__)

# Carry-over SOC used for every duration on the very first run, before any
# ``latest.json`` exists. A half-charged battery is the neutral starting point.
_DEFAULT_START_SOC: float = 0.5


def _resolve_date(raw: str | None) -> dt.date:
    """Resolve the ``--date`` argument to a concrete UTC delivery date.

    ``None`` (omitted) and the literal ``"yesterday"`` both resolve to yesterday
    in UTC; anything else is parsed as an ISO ``YYYY-MM-DD`` date.
    """
    if raw is None or raw == "yesterday":
        return dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    return dt.date.fromisoformat(raw)


def _start_state() -> tuple[dict[str, float], dict[str, float]]:
    """Carry-over start SOC and running cumulative PnL per duration.

    Read from ``latest.json`` when present; any duration missing from the stored
    artifact (or the whole file being absent) falls back to a half-charged
    battery and zero cumulative PnL.
    """
    latest = io_store.read_latest()
    end_soc = latest["end_soc"] if latest else {}
    cumulative = latest["cumulative_net_pnl"] if latest else {}
    start_soc = {d: float(end_soc.get(d, _DEFAULT_START_SOC)) for d in REFERENCE_DURATIONS}
    prev_cumulative = {d: float(cumulative.get(d, 0.0)) for d in REFERENCE_DURATIONS}
    return start_soc, prev_cumulative


def run_day(date: dt.date) -> bool:
    """Fetch, settle, classify and persist a single delivery day.

    Returns ``True`` when a day artifact was written and ``latest.json``
    advanced, or ``False`` for a clean skip (the day's prices are incomplete or
    not yet available, so :func:`settle_day` declines the day). Re-running the
    same date overwrites that day's artifact in place rather than duplicating it.
    """
    start_soc, prev_cumulative = _start_state()

    prices = fetch_live.get_day_prices(date)
    context = fetch_live.get_day_context(date)
    logger.info("fetch: date=%s periods=%d context=%s", date, len(prices), context)

    day_result = settle_day(date, prices, bess_config(), build_assets(), start_soc)
    if day_result is None:
        logger.info(
            "skip: date=%s incomplete or unavailable price data (%d periods); nothing written",
            date,
            len(prices),
        )
        return False
    logger.info("settle: date=%s durations=%s", date, sorted(day_result.durations))

    labels = classify_mod.classify(prices, context)
    logger.info("classify: date=%s labels=%s", date, labels)

    end_soc = {d: result.end_soc for d, result in day_result.durations.items()}
    cumulative = {
        d: prev_cumulative.get(d, 0.0) + result.net_pnl
        for d, result in day_result.durations.items()
    }
    io_store.write_day(date, day_result, context, labels)
    io_store.write_latest(date, end_soc, cumulative)
    logger.info("persist: date=%s end_soc=%s cumulative_net_pnl=%s", date, end_soc, cumulative)
    return True


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m live.run_day",
        description="Run the live GB BESS benchmark for a single delivery day.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Delivery day as YYYY-MM-DD or 'yesterday' (default: yesterday, UTC).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exits ``0`` on success or a clean skip, non-zero on error."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    date = _resolve_date(args.date)
    try:
        run_day(date)
    except Exception:
        logger.exception("run_day failed for %s", date)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
