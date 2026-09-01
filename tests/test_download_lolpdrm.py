"""Tests for the Elexon LoLP/De-rated Margin and NESO CMN register fetchers.

``requests.get`` is mocked so no network call happens, and the raw cache is
redirected to ``tmp_path`` so no committed data is touched.
"""

import json
import os

import pandas as pd
import pytest

from src.data import download as dl


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"x" if payload is not None else b""

    def json(self):
        return self._payload


def _lolpdrm_payload(date="2026-08-10", periods=2, horizons=(12, 8, 4, 2, 1)):
    """Every horizon print for the first ``periods`` half-hours of the day."""
    base = pd.Timestamp(f"{date}T00:00:00Z")
    records = []
    for p in range(periods):
        start = base + pd.Timedelta(minutes=30 * p)
        for h in horizons:
            records.append(
                {
                    "publishTime": (start - pd.Timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "settlementDate": date,
                    "settlementPeriod": p + 1,
                    "forecastHorizon": h,
                    "lossOfLoadProbability": 0.0,
                    "deratedMargin": 10000.0 + h,
                }
            )
    return {"data": records}


def _cmn_payload():
    return {
        "success": True,
        "data": {
            "results": [
                {
                    "id": 37,
                    "type": {"id": 1, "name": "CMN"},
                    "title": "Electricity Capacity Market Notice Currently Active",
                    "posted": {"timestamp": 1736337674},
                    "extended": {
                        "startDate": {"timestamp": 1736353800},
                        "endDate": {"timestamp": 1736368200},
                    },
                    "operator": "NESO",
                }
            ],
            "next": None,
        },
    }


@pytest.fixture(autouse=True)
def _redirect_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "RAW_DATA_DIR", str(tmp_path))


def test_fetch_one_day_keeps_all_horizons(monkeypatch):
    monkeypatch.setattr(dl.requests, "get", lambda *a, **k: _FakeResponse(_lolpdrm_payload()))
    records = dl._fetch_lolpdrm_day(pd.Timestamp("2026-08-10"))

    # The raw cache keeps every print — horizon selection is preprocess's job.
    assert len(records) == 10
    assert sorted({r["forecastHorizon"] for r in records}) == [1, 2, 4, 8, 12]

    df = dl.fetch_lolpdrm("2026-08-10", "2026-08-10")
    assert list(df.columns) == dl._LOLPDRM_COLUMNS
    assert len(df) == 10


def test_lolpdrm_second_call_reads_cache(monkeypatch):
    hits = {"n": 0}

    def fake_get(*a, **k):
        hits["n"] += 1
        return _FakeResponse(_lolpdrm_payload())

    monkeypatch.setattr(dl.requests, "get", fake_get)
    dl._fetch_lolpdrm_day(pd.Timestamp("2026-08-10"))
    dl._fetch_lolpdrm_day(pd.Timestamp("2026-08-10"))
    assert hits["n"] == 1


def test_lolpdrm_empty_payload_not_cached(monkeypatch):
    hits = {"n": 0}

    def fake_get(*a, **k):
        hits["n"] += 1
        return _FakeResponse({"data": []})

    monkeypatch.setattr(dl.requests, "get", fake_get)
    assert dl._fetch_lolpdrm_day(pd.Timestamp("2026-08-10")) == []
    # A day that published nothing is retried on the next call, not cached.
    assert dl._fetch_lolpdrm_day(pd.Timestamp("2026-08-10")) == []
    assert hits["n"] == 2
    assert dl.fetch_lolpdrm("2026-08-10", "2026-08-10").empty


def test_lolpdrm_windows_records_to_requested_day(monkeypatch):
    payload = _lolpdrm_payload()
    payload["data"].append(
        {
            "publishTime": "2026-08-10T23:00:00Z",
            "startTime": "2026-08-11T00:00:00Z",  # next UTC day — must be dropped
            "settlementDate": "2026-08-11",
            "settlementPeriod": 1,
            "forecastHorizon": 1,
            "lossOfLoadProbability": 0.0,
            "deratedMargin": 9000.0,
        }
    )
    monkeypatch.setattr(dl.requests, "get", lambda *a, **k: _FakeResponse(payload))
    records = dl._fetch_lolpdrm_day(pd.Timestamp("2026-08-10"))
    assert all(r["settlementDate"] == "2026-08-10" for r in records)


def test_cmn_fetch_sends_mandatory_types_and_caches_by_fetch_date(monkeypatch, tmp_path):
    seen = {}

    def fake_get(url, params=None, **k):
        seen["url"] = url
        seen["params"] = params
        return _FakeResponse(_cmn_payload())

    monkeypatch.setattr(dl.requests, "get", fake_get)
    first = dl.fetch_cmn_notices()

    assert len(first) == 1
    # The register returns nothing without the types[] filter, so both type
    # ids must ride along as repeated keys.
    assert ("types[]", "1") in seen["params"]
    assert ("types[]", "4") in seen["params"]

    # Snapshot cached under the fetch date: second call makes no network hit.
    monkeypatch.setattr(dl.requests, "get", lambda *a, **k: pytest.fail("network hit"))
    assert dl.fetch_cmn_notices() == first
    cached = [f for f in os.listdir(tmp_path / "CMN") if f.startswith("CMN_")]
    assert len(cached) == 1
    with open(tmp_path / "CMN" / cached[0], encoding="utf-8") as fp:
        assert json.load(fp)["data"] == first


def test_cmn_softfails_on_error(monkeypatch):
    monkeypatch.setattr(dl.requests, "get", lambda *a, **k: _FakeResponse(None, status_code=500))
    assert dl.fetch_cmn_notices() == []

    monkeypatch.setattr(
        dl.requests, "get", lambda *a, **k: _FakeResponse({"success": False, "data": None})
    )
    assert dl.fetch_cmn_notices() == []
