"""Day-level coverage accounting for the raw feed caches.

Every fetcher in this package caches one file per settlement day under
``RAW_DATA_DIR/<FEED>/``, which makes "what do we actually have?" a question
about the filesystem rather than about the network. This module answers it.

The point is not tidiness. An analysis window is only as trustworthy as the
thinnest feed inside it: the fleet's Physical Notifications may span three
years while the MID price they are valued against spans three months, and a
capture-spread average computed over that pair is quietly computed over the
three months. Coverage is therefore reported *per feed per day*, so downstream
work can state its denominator instead of averaging over holes.

Two consumers:

* ``scripts/backfill_market_data.py`` — decides what to download, and reports
  what changed once it has.
* the research notebooks — print the same table beside their results, the way
  notebook 05 already prints the stress-store coverage.

Cache filenames are not uniform across feeds (``MID_20240601_page_1.json``,
``LOLPDRM_20240601.json``, ``FLEET_PN_2024-06-01.json``), so the date is
recovered by regex rather than by re-deriving each fetcher's naming scheme.
A feed whose directory does not exist reads as zero days present, never as an
error — a feed that was never fetched is a normal state, not a fault.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass

import pandas as pd

from src.utils.config import RAW_DATA_DIR

# Matches YYYYMMDD or YYYY-MM-DD anywhere in a cache filename.
_DATE_RE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


@dataclass(frozen=True)
class Feed:
    """One cached raw feed: where it lives and what it is for."""

    name: str
    directory: str
    description: str
    #: ``True`` when the feed is fetched per fleet BM Unit, so its coverage
    #: depends on the registry/census population as well as on the date range.
    per_bmu: bool = False


# Every day-cached feed the repository writes. Grouped by what they serve so a
# coverage report reads as a statement about the analysis, not about disk.
FEEDS: dict[str, Feed] = {
    # --- system state -------------------------------------------------
    "ITSDO": Feed("ITSDO", "ITSDO", "Transmission demand outturn"),
    "FUELHH": Feed("FUELHH", "FUELHH", "Generation mix by fuel type"),
    "PVLIVE_SOLAR": Feed("PVLIVE_SOLAR", "PVLIVE_SOLAR", "Embedded solar outturn"),
    "LOLPDRM": Feed("LOLPDRM", "LOLPDRM", "Loss-of-load probability / de-rated margin"),
    # --- prices -------------------------------------------------------
    "MID": Feed("MID", "MID", "Market index price (wholesale proxy)"),
    "B1770": Feed("B1770", "B1770", "Imbalance prices (SBP/SSP)"),
    "NORDPOOL_DA": Feed("NORDPOOL_DA", "NORDPOOL_DA", "N2EX day-ahead price (~65-day window)"),
    # --- forecasts ----------------------------------------------------
    "WINDFOR": Feed("WINDFOR", "WINDFOR", "Wind generation forecast"),
    "NESO_NDFD": Feed("NESO_NDFD", "NESO_NDFD", "National demand forecast (day-ahead)"),
    # --- per-BMU fleet feeds -----------------------------------------
    "FLEET_PN": Feed("FLEET_PN", "FLEET_PN", "Physical Notifications", per_bmu=True),
    "FLEET_BOALF": Feed("FLEET_BOALF", "FLEET_BOALF", "Accepted bid-offer levels", per_bmu=True),
    "FLEET_EBOCF": Feed("FLEET_EBOCF", "FLEET_EBOCF", "Indicative BM cashflows", per_bmu=True),
    "FLEET_MELS": Feed("FLEET_MELS", "FLEET_MELS", "Maximum export limits", per_bmu=True),
    "FLEET_MILS": Feed("FLEET_MILS", "FLEET_MILS", "Maximum import limits", per_bmu=True),
}

# The same per-BMU feeds fetched for the census population. A day-file holds
# exactly the BM Units it was fetched for, so the two populations cache into
# separate directories and their coverage is accounted separately — a census
# day is not "present" merely because the curated 47 were fetched for it.
for _base in ("FLEET_PN", "FLEET_BOALF", "FLEET_EBOCF", "FLEET_MELS", "FLEET_MILS"):
    _spec = FEEDS[_base]
    FEEDS[f"{_base}_CENSUS"] = Feed(
        name=f"{_base}_CENSUS",
        directory=f"{_base}_CENSUS",
        description=f"{_spec.description} (census population)",
        per_bmu=True,
    )


def window_days(start: dt.date, end: dt.date) -> list[dt.date]:
    """Inclusive list of settlement days in ``[start, end]``."""
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def cached_days(feed: str, raw_dir: str | None = None) -> set[dt.date]:
    """Every settlement day ``feed`` has at least one cache file for.

    A feed with no directory yet returns an empty set rather than raising:
    "never fetched" is a normal state for a feed the current config does not
    use. Files whose name carries no recoverable date are ignored.
    """
    spec = FEEDS.get(feed)
    directory = spec.directory if spec else feed
    path = os.path.join(raw_dir or RAW_DATA_DIR, directory)
    if not os.path.isdir(path):
        return set()

    days: set[dt.date] = set()
    for filename in os.listdir(path):
        match = _DATE_RE.search(filename)
        if not match:
            continue
        try:
            days.add(dt.date(*(int(part) for part in match.groups())))
        except ValueError:
            continue  # e.g. a stray filename that parses to 2024-13-45
    return days


def missing_days(
    feed: str, start: dt.date, end: dt.date, raw_dir: str | None = None
) -> list[dt.date]:
    """Days in ``[start, end]`` that ``feed`` has no cache file for."""
    have = cached_days(feed, raw_dir)
    return [day for day in window_days(start, end) if day not in have]


def coverage_frame(
    start: dt.date,
    end: dt.date,
    feeds: list[str] | None = None,
    raw_dir: str | None = None,
) -> pd.DataFrame:
    """One row per day, one boolean column per feed.

    The long form, for joining against an analysis frame so a result can drop
    the days its inputs never covered.
    """
    names = feeds if feeds is not None else list(FEEDS)
    days = window_days(start, end)
    return pd.DataFrame(
        {name: [day in cached_days(name, raw_dir) for day in days] for name in names},
        index=pd.Index(days, name="date"),
    )


def coverage_summary(
    start: dt.date,
    end: dt.date,
    feeds: list[str] | None = None,
    raw_dir: str | None = None,
) -> pd.DataFrame:
    """One row per feed: days present, days missing, percentage and extent.

    The short form — what a notebook prints beside its results, and what the
    backfill script prints before and after a run.
    """
    names = feeds if feeds is not None else list(FEEDS)
    days = window_days(start, end)
    total = len(days)

    rows = []
    for name in names:
        have = cached_days(name, raw_dir) & set(days)
        rows.append(
            {
                "feed": name,
                "description": FEEDS[name].description if name in FEEDS else "",
                "days_present": len(have),
                "days_missing": total - len(have),
                "pct_present": round(100.0 * len(have) / total, 1) if total else 0.0,
                "first_day": min(have) if have else None,
                "last_day": max(have) if have else None,
            }
        )
    return pd.DataFrame(rows).set_index("feed").sort_values("pct_present")
