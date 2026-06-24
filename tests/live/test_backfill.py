"""Tests for the bulk backfill CLI.

The live data adapter (:mod:`live.fetch_live`) is mocked with in-memory price
frames and context dicts so no network IO happens, while the real settlement,
persistence and aggregation layers run end to end against an isolated
``docs/data`` tree redirected to ``tmp_path``.
"""

import datetime as dt

import pandas as pd
import pytest

from live import backfill, fetch_live, io_store
from live.assets import REFERENCE_DURATIONS

_START = dt.date(2026, 6, 22)
_END = dt.date(2026, 6, 24)


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path, monkeypatch):
    """Point all io_store writes at an isolated temp directory."""
    monkeypatch.setattr(io_store, "DATA_DIR", tmp_path / "data")


def _prices(n_periods: int = 24, *, low: float = 20.0, high: float = 80.0) -> pd.DataFrame:
    """Cheap-first-half / expensive-second-half day giving clear arbitrage."""
    times = pd.date_range("2026-06-22T00:00:00Z", periods=n_periods, freq="60min")
    da = [low if i < n_periods // 2 else high for i in range(n_periods)]
    mid = [p + 1.0 for p in da]
    return pd.DataFrame({"day_ahead_price": da, "mid_price": mid}, index=times)


def _context() -> dict[str, float | None]:
    return {"wind_gwh": 120.0, "solar_gwh": 30.0, "demand_gwh": 700.0, "wind_share": 0.42}


def _mock_fetch(monkeypatch, prices: pd.DataFrame) -> None:
    monkeypatch.setattr(fetch_live, "get_day_prices", lambda date: prices)
    monkeypatch.setattr(fetch_live, "get_day_context", lambda date: _context())


def test_backfill_writes_each_day_with_continuous_soc(monkeypatch):
    _mock_fetch(monkeypatch, _prices())

    summary = backfill.backfill(_START, _END)

    dates = [d.isoformat() for d in (_START, _START + dt.timedelta(days=1), _END)]
    assert summary["written"] == dates
    assert summary["skipped"] == []
    assert summary["incomplete"] == []

    # Three day files, exactly one per date in the range.
    days_dir = io_store.DATA_DIR / "days"
    assert sorted(p.name for p in days_dir.glob("*.json")) == [f"{d}.json" for d in dates]

    # SOC carries over: each day starts from the prior day's end SOC.
    settled = [io_store.read_day(d) for d in dates]
    for prev, nxt in zip(settled, settled[1:]):
        for duration in REFERENCE_DURATIONS:
            assert nxt["assets"][duration]["soc"]["start"] == pytest.approx(
                prev["assets"][duration]["soc"]["end"], abs=1e-3
            )

    # A single roll-up pass rebuilt history.json over all three days.
    history = io_store.read_history()
    assert history is not None
    assert [row["date"] for row in history["rows"]] == dates


def test_backfill_skips_existing_unless_forced(monkeypatch):
    _mock_fetch(monkeypatch, _prices())

    backfill.backfill(_START, _START)
    first = io_store.read_day(_START)

    # Re-running the same date is a skip and leaves the artifact untouched.
    summary = backfill.backfill(_START, _START)
    assert summary["skipped"] == [_START.isoformat()]
    assert summary["written"] == []
    assert io_store.read_day(_START) == first

    # --force re-settles the day instead of skipping it.
    forced = backfill.backfill(_START, _START, force=True)
    assert forced["written"] == [_START.isoformat()]
    assert forced["skipped"] == []


def test_backfill_records_incomplete_days(monkeypatch):
    # A partial day makes settle_day decline, which must be a clean no-op.
    _mock_fetch(monkeypatch, _prices(n_periods=10))

    summary = backfill.backfill(_START, _START)

    assert summary["incomplete"] == [_START.isoformat()]
    assert summary["written"] == []
    assert not (io_store.DATA_DIR / "days").exists()


def test_resolve_range_defaults_to_trailing_window():
    today = dt.datetime.now(dt.timezone.utc).date()
    yesterday = today - dt.timedelta(days=1)

    start, end = backfill._resolve_range(None, None)
    assert end == yesterday
    assert start == yesterday - dt.timedelta(days=backfill._DEFAULT_HORIZON_DAYS - 1)

    start, end = backfill._resolve_range("2026-06-22", "2026-06-24")
    assert (start, end) == (_START, _END)


def test_resolve_range_rejects_inverted_range():
    with pytest.raises(ValueError):
        backfill._resolve_range("2026-06-24", "2026-06-22")


def test_main_returns_zero(monkeypatch):
    _mock_fetch(monkeypatch, _prices())
    assert backfill.main(["--start", _START.isoformat(), "--end", _END.isoformat()]) == 0
