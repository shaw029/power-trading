"""Tests for the Nord Pool (N2EX, GB) day-ahead price fetcher.

``requests.get`` is mocked so no network call happens, and the raw cache is
redirected to ``tmp_path`` so no committed data is touched.
"""

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


def _payload(date="2026-06-23", n=24):
    """A day of hourly UK entries starting at CET midnight (22:00Z prev day)."""
    base = pd.Timestamp(f"{date}T00:00:00Z") - pd.Timedelta(hours=2)
    entries = [
        {
            "deliveryStart": (base + pd.Timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "deliveryEnd": (base + pd.Timedelta(hours=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entryPerArea": {"UK": 100.0 + i},
        }
        for i in range(n)
    ]
    return {"market": "N2EX_DayAhead", "deliveryAreas": ["UK"], "multiAreaEntries": entries}


@pytest.fixture(autouse=True)
def _redirect_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "RAW_DATA_DIR", str(tmp_path))


def test_fetch_one_day_parses_entries(monkeypatch):
    monkeypatch.setattr(dl.requests, "get", lambda *a, **k: _FakeResponse(_payload()))
    df = dl._fetch_nordpool_da_day(pd.Timestamp("2026-06-23"))

    assert list(df.columns) == ["time", "value"]
    assert len(df) == 24
    assert str(df["time"].dt.tz) == "UTC"
    assert df["value"].iloc[0] == 100.0


def test_non_200_returns_empty(monkeypatch):
    monkeypatch.setattr(dl.requests, "get", lambda *a, **k: _FakeResponse(None, status_code=401))
    df = dl._fetch_nordpool_da_day(pd.Timestamp("2026-06-23"))
    assert df.empty
    assert list(df.columns) == ["time", "value"]


def test_router_uses_nordpool_and_dedupes_inclusive_range(monkeypatch):
    calls = []

    def fake_get(url, params=None, **k):
        calls.append(params["date"])
        return _FakeResponse(_payload(date=params["date"]))

    monkeypatch.setattr(dl.requests, "get", fake_get)
    df = dl.fetch_day_ahead_price(source="NORDPOOL", start_date="2026-06-23", end_date="2026-06-24")

    # Range is fetched inclusive of end_date (CET-day stitch), so both days hit.
    assert calls == ["2026-06-23", "2026-06-24"]
    # Overlapping CET windows are de-duplicated on timestamp.
    assert df["time"].is_unique
    assert not df.empty


def test_second_call_reads_cache(monkeypatch):
    hits = {"n": 0}

    def fake_get(*a, **k):
        hits["n"] += 1
        return _FakeResponse(_payload())

    monkeypatch.setattr(dl.requests, "get", fake_get)
    dl._fetch_nordpool_da_day(pd.Timestamp("2026-06-23"))
    dl._fetch_nordpool_da_day(pd.Timestamp("2026-06-23"))
    # Second call served from the cached JSON, so only one network hit.
    assert hits["n"] == 1
