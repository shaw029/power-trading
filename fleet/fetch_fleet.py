"""Per-BMU Elexon downloads for the live GB fleet tab.

The fleet tab needs two things the rest of the project never touches — per-BMU
Physical Notifications (dataset ``PN``) and per-BMU indicative Balancing
Mechanism cashflows (dataset ``EBOCF``) — so their HTTP code lives here rather
than in :mod:`src.data.download`. Everything else (the MID price used as the
wholesale proxy) is reused from the existing fetch/preprocess functions.

Both endpoints are public and keyless. Responses are cached one JSON file per
settlement day under ``RAW_DATA_DIR`` (``FLEET_PN/``, ``FLEET_EBOCF/``),
mirroring the day-file caching convention of ``src.data.download``; empty
payloads are not cached so a day that publishes late is retried on the next
run.
"""

import datetime as dt
import json
import logging
import os
from typing import Any, cast

import pandas as pd
import requests

from fleet.registry import all_bmu_ids
from src.data.download import fetch_market_index_price
from src.data.preprocess import process_market_index_price
from src.utils.config import ELEXON_BASE_URL, RAW_DATA_DIR

logger = logging.getLogger(__name__)

_PN_DIR = "FLEET_PN"
_MELS_DIR = "FLEET_MELS"
_MILS_DIR = "FLEET_MILS"
_CASHFLOW_DIR = "FLEET_EBOCF"
_TIMEOUT_S = 30

# A GB settlement day is local (Europe/London), so in summer it starts at
# 23:00 UTC the previous day. The PN stream is queried on a padded UTC window
# and filtered back to the settlement date afterwards.
_PN_WINDOW_PAD = pd.Timedelta(hours=2)


def _cache_path(subdir: str, date: dt.date) -> str:
    return os.path.join(RAW_DATA_DIR, subdir, f"{subdir}_{date.isoformat()}.json")


def _read_cache(subdir: str, date: dt.date) -> Any:
    path = _cache_path(subdir, date)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    return None


def _write_cache(subdir: str, date: dt.date, payload) -> None:
    path = _cache_path(subdir, date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp)
    logger.info("Cached %s", path)


def _get_json(url: str, params: list[tuple[str, str]] | None = None):
    response = requests.get(
        url, params=params, headers={"Accept": "application/json"}, timeout=_TIMEOUT_S
    )
    response.raise_for_status()
    return response.json()


def _fetch_day_stream(dataset: str, subdir: str, date: dt.date) -> list[dict]:
    """One settlement day of a per-BMU Elexon ``/datasets/<X>/stream`` feed.

    Queries a ±2h-padded UTC window for every fleet BMU, filters back to
    ``settlementDate == date``, and day-file caches non-empty results under
    ``subdir``.
    """
    cached = _read_cache(subdir, date)
    if cached is not None:
        return cast(list[dict], cached)

    start = pd.Timestamp(date, tz="UTC") - _PN_WINDOW_PAD
    end = pd.Timestamp(date + dt.timedelta(days=1), tz="UTC") + _PN_WINDOW_PAD
    params: list[tuple[str, str]] = [
        ("from", start.strftime("%Y-%m-%dT%H:%MZ")),
        ("to", end.strftime("%Y-%m-%dT%H:%MZ")),
    ]
    params += [("bmUnit", bmu) for bmu in all_bmu_ids()]

    url = f"{ELEXON_BASE_URL.rstrip('/')}/datasets/{dataset}/stream"
    records = _get_json(url, params)
    records = [r for r in records if r.get("settlementDate") == date.isoformat()]
    if records:
        _write_cache(subdir, date, records)
    return records


def fetch_fleet_pn(date: dt.date) -> list[dict]:
    """Physical Notification records for every fleet BMU on one settlement day.

    Returns the raw Elexon ``PN`` stream records (one per BMU per settlement
    period, with ``levelFrom``/``levelTo`` MW and a UTC ``timeFrom``/``timeTo``
    span), filtered to ``settlementDate == date``.
    """
    return _fetch_day_stream("PN", _PN_DIR, date)


def fetch_fleet_mels(date: dt.date) -> list[dict]:
    """Maximum Export Limit records for every fleet BMU on one settlement day.

    Raw Elexon ``MELS`` stream records: declared export capability in MW
    (``levelFrom``/``levelTo`` ≥ 0). Unlike PNs, spans are *irregular* —
    redeclarations cut periods into sub-spans (e.g. 18:00→18:24) and carry
    ``notificationTime``/``notificationSequence``. Resolving overlaps onto the
    half-hourly grid is :func:`fleet.performance.site_limit_profile`'s job,
    not this fetcher's.
    """
    return _fetch_day_stream("MELS", _MELS_DIR, date)


def fetch_fleet_mils(date: dt.date) -> list[dict]:
    """Maximum Import Limit records for every fleet BMU on one settlement day.

    Raw Elexon ``MILS`` stream records: declared import capability in MW
    (``levelFrom``/``levelTo`` ≤ 0, i.e. charge headroom). Same irregular-span
    shape as MELS; see :func:`fetch_fleet_mels`.
    """
    return _fetch_day_stream("MILS", _MILS_DIR, date)


def fetch_fleet_bm_cashflows(date: dt.date) -> dict[str, list[dict]]:
    """Indicative BM cashflow records (£) for every fleet BMU on one day.

    Elexon's ``EBOCF`` dataset already prices each unit's accepted bids and
    offers, so no settlement arithmetic is re-implemented here. Returns
    ``{"bid": [...], "offer": [...]}`` with one record per BMU per settlement
    period, each carrying a ``bidOfferPairCashflows`` mapping.
    """
    cached = _read_cache(_CASHFLOW_DIR, date)
    if cached is not None:
        return cast(dict[str, list[dict]], cached)

    base = f"{ELEXON_BASE_URL.rstrip('/')}/balancing/settlement/indicative/cashflows/all"
    params = [("bmUnit", bmu) for bmu in all_bmu_ids()]

    payload: dict[str, list[dict]] = {}
    for direction in ("bid", "offer"):
        body = _get_json(f"{base}/{direction}/{date.isoformat()}", params)
        payload[direction] = body.get("data", []) if isinstance(body, dict) else []

    if payload["bid"] or payload["offer"]:
        _write_cache(_CASHFLOW_DIR, date, payload)
    return payload


def fetch_day_mid_prices(date: dt.date) -> pd.DataFrame:
    """Half-hourly MID prices covering the full settlement day.

    Reuses the repo's Elexon MID fetch (day-file cached) and preprocess. The
    fetch window is padded one day back so the BST-shifted start of the GB
    settlement day is covered; the returned frame is a UTC-indexed
    ``mid_price`` column spanning at least ``[date - 1, date + 1)``.
    """
    start = (date - dt.timedelta(days=1)).isoformat()
    return process_market_index_price(
        fetch_market_index_price(start_date=start, end_date=date.isoformat())
    )
