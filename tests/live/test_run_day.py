"""Tests for the single-day orchestration CLI.

The live data adapter (:mod:`live.fetch_live`) is mocked with in-memory price
frames and context dicts so no network IO happens, while the real settlement
engine and the real persistence layer run end to end against an isolated
``docs/data`` tree redirected to ``tmp_path``.
"""

import datetime as dt

import pandas as pd
import pytest

from live import fetch_live, io_store, run_day
from live.assets import REFERENCE_DURATIONS

_DAY = dt.date(2026, 6, 24)


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path, monkeypatch):
    """Point all io_store writes at an isolated temp directory."""
    monkeypatch.setattr(io_store, "DATA_DIR", tmp_path / "data")


def _prices(n_periods: int = 24, *, low: float = 20.0, high: float = 80.0) -> pd.DataFrame:
    """Cheap-first-half / expensive-second-half day giving clear arbitrage."""
    times = pd.date_range("2026-06-24T00:00:00Z", periods=n_periods, freq="60min")
    da = [low if i < n_periods // 2 else high for i in range(n_periods)]
    mid = [p + 1.0 for p in da]
    return pd.DataFrame({"day_ahead_price": da, "mid_price": mid}, index=times)


def _context() -> dict[str, float | None]:
    return {"wind_gwh": 120.0, "solar_gwh": 30.0, "demand_gwh": 700.0, "wind_share": 0.42}


def _mock_fetch(monkeypatch, prices: pd.DataFrame) -> None:
    monkeypatch.setattr(fetch_live, "get_day_prices", lambda date: prices)
    monkeypatch.setattr(fetch_live, "get_day_context", lambda date: _context())


def test_normal_run_writes_day_and_advances_latest(monkeypatch):
    _mock_fetch(monkeypatch, _prices())

    wrote = run_day.run_day(_DAY)

    assert wrote is True
    day = io_store.read_day(_DAY)
    assert day["date"] == _DAY.isoformat()
    assert set(day["assets"]) == set(REFERENCE_DURATIONS)

    latest = io_store.read_latest()
    assert latest is not None
    assert latest["date"] == _DAY.isoformat()
    assert set(latest["end_soc"]) == set(REFERENCE_DURATIONS)
    # The arbitrage day moves the battery off its 0.5 starting charge.
    assert any(soc != 0.5 for soc in latest["end_soc"].values())
    assert set(latest["cumulative_net_pnl"]) == set(REFERENCE_DURATIONS)


def test_run_writes_day_detail_figures(monkeypatch):
    # The dashboard fetches figs/<date>/dispatch.json + waterfall.json per day,
    # so run_day must export them alongside the artifact.
    _mock_fetch(monkeypatch, _prices())

    assert run_day.run_day(_DAY) is True

    figs_dir = io_store.DATA_DIR / "figs" / _DAY.isoformat()
    assert (figs_dir / "dispatch.json").exists()
    assert (figs_dir / "waterfall.json").exists()


def test_rerun_same_date_overwrites_without_duplicate(monkeypatch):
    _mock_fetch(monkeypatch, _prices())

    assert run_day.run_day(_DAY) is True
    first = io_store.read_latest()
    assert first is not None

    assert run_day.run_day(_DAY) is True
    second = io_store.read_latest()
    assert second is not None

    days_dir = io_store.DATA_DIR / "days"
    files = sorted(p.name for p in days_dir.glob("*.json"))
    assert files == [f"{_DAY.isoformat()}.json"]

    # Re-running the same day is idempotent: the cumulative PnL and end SOC must
    # be unchanged, not doubled by re-adding the day's own contribution.
    assert second["date"] == first["date"]
    assert second["cumulative_net_pnl"] == first["cumulative_net_pnl"]
    assert second["end_soc"] == first["end_soc"]

    # With no earlier day stored, the rerun starts from the default half charge,
    # never from the day's own end SOC.
    day = io_store.read_day(_DAY)
    for duration in REFERENCE_DURATIONS:
        assert day["assets"][duration]["soc"]["start"] == pytest.approx(0.5, abs=1e-9)
        assert second["cumulative_net_pnl"][duration] == pytest.approx(
            day["assets"][duration]["pnl"]["net_pnl"], abs=1e-2
        )


def test_carries_cumulative_pnl_forward(monkeypatch):
    """A second run's cumulative PnL builds on the first day's stored total."""
    _mock_fetch(monkeypatch, _prices())
    run_day.run_day(_DAY)
    after_first = io_store.read_latest()
    assert after_first is not None

    next_day = _DAY + dt.timedelta(days=1)
    run_day.run_day(next_day)
    after_second = io_store.read_latest()
    assert after_second is not None

    day_two = io_store.read_day(next_day)
    for duration in REFERENCE_DURATIONS:
        first = after_first["cumulative_net_pnl"][duration]
        second = after_second["cumulative_net_pnl"][duration]
        day_two_pnl = day_two["assets"][duration]["pnl"]["net_pnl"]
        # The running total advances by exactly the second day's net PnL.
        assert second == pytest.approx(first + day_two_pnl, abs=1e-2)
        # The second day starts from the carried-over SOC, so it is a real run.
        assert day_two["assets"][duration]["soc"]["start"] == pytest.approx(
            after_first["end_soc"][duration], abs=1e-3
        )


def test_incomplete_data_skips_and_writes_nothing(monkeypatch):
    # A partial day (period count outside the DST-valid set) makes settle_day
    # decline the day, which must be a clean skip with no artifacts written.
    _mock_fetch(monkeypatch, _prices(n_periods=10))

    wrote = run_day.run_day(_DAY)

    assert wrote is False
    assert not (io_store.DATA_DIR / "days").exists()
    assert io_store.read_latest() is None


def test_main_returns_zero_on_skip(monkeypatch):
    _mock_fetch(monkeypatch, _prices(n_periods=10))
    assert run_day.main(["--date", _DAY.isoformat()]) == 0


def test_main_returns_nonzero_on_fetch_failure(monkeypatch):
    def _boom(date):
        raise RuntimeError("fetch exploded")

    monkeypatch.setattr(fetch_live, "get_day_prices", _boom)
    monkeypatch.setattr(fetch_live, "get_day_context", lambda date: _context())

    assert run_day.main(["--date", _DAY.isoformat()]) == 1


def test_resolve_date_yesterday_default():
    today = dt.datetime.now(dt.timezone.utc).date()
    assert run_day._resolve_date(None) == today - dt.timedelta(days=1)
    assert run_day._resolve_date("yesterday") == today - dt.timedelta(days=1)
    assert run_day._resolve_date("2026-06-24") == _DAY
