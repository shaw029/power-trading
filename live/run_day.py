"""Single-day orchestration CLI for the live GB BESS benchmark.

This module ties the per-day pieces of the live benchmark together for one
delivery day:

  1. Resolve the carry-over SOC from the most recent earlier stored day
     (:func:`_carry_over_soc`) — defaulting to a half-charged battery when no
     earlier history exists yet.
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
from live.assets import DEFAULT_START_SOC, REFERENCE_DURATIONS, bess_config, build_assets
from live.settle import settle_day

logger = logging.getLogger(__name__)


def _resolve_date(raw: str | None) -> dt.date:
    """Resolve the ``--date`` argument to a concrete UTC delivery date.

    ``None`` (omitted) and the literal ``"yesterday"`` both resolve to yesterday
    in UTC; anything else is parsed as an ISO ``YYYY-MM-DD`` date.
    """
    if raw is None or raw == "yesterday":
        return dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    return dt.date.fromisoformat(raw)


def _carry_over_soc(date: dt.date) -> dict[str, float]:
    """Start SOC carried into ``date`` from the most recent earlier stored day.

    Reconstructed from the per-day artifacts strictly *before* ``date`` rather
    than from the mutable ``latest.json``, so re-running ``date`` (whose own
    artifact may already exist) or backfilling it into a gap never reads its own
    or a later day's state. Durations with no earlier history fall back to a
    half-charged battery.
    """
    iso = date.isoformat()
    start_soc = {d: DEFAULT_START_SOC for d in REFERENCE_DURATIONS}
    for day_iso in io_store.list_day_dates():
        if day_iso >= iso:
            break
        for duration, asset in io_store.read_day(day_iso)["assets"].items():
            if duration in start_soc:
                start_soc[duration] = float(asset["soc"]["end"])
    return start_soc


def _advance_latest() -> dict[str, float]:
    """Rewrite ``latest.json`` to reflect the newest stored day, and return its cumulative PnL.

    End SOC is taken from the newest day's artifact and cumulative PnL is summed
    over every stored day, so the snapshot stays correct after a re-run or a gap
    backfill changes the set of days. A no-op (and empty result) when no day
    artifacts exist yet.
    """
    cumulative = {d: 0.0 for d in REFERENCE_DURATIONS}
    last_assets: dict[str, dict] = {}
    last_iso = ""
    for day_iso in io_store.list_day_dates():
        last_iso = day_iso
        last_assets = io_store.read_day(day_iso)["assets"]
        for duration, asset in last_assets.items():
            if duration in cumulative:
                cumulative[duration] += float(asset["pnl"]["net_pnl"])
    if not last_iso:
        return {}
    end_soc = {duration: float(asset["soc"]["end"]) for duration, asset in last_assets.items()}
    io_store.write_latest(last_iso, end_soc, cumulative)
    return cumulative


def run_day(date: dt.date) -> bool:
    """Fetch, settle, classify and persist a single delivery day.

    Returns ``True`` when a day artifact was written and ``latest.json``
    advanced, or ``False`` for a clean skip (the day's prices are incomplete or
    not yet available, so :func:`settle_day` declines the day). Re-running the
    same date overwrites that day's artifact in place rather than duplicating it.
    """
    start_soc = _carry_over_soc(date)

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

    io_store.write_day(date, day_result, context, labels)
    # Recompute latest.json from every stored day so cumulative PnL is summed
    # from scratch — re-running or gap-filling a day never double-counts it.
    cumulative = _advance_latest()
    logger.info("persist: date=%s cumulative_net_pnl=%s", date, cumulative)
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
