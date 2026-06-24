"""Headless smoke test for the live Streamlit dashboard.

``live.fetch_live`` is mocked so no network call happens, and Streamlit's
``AppTest`` runs the script in-process and surfaces any exception. This proves
the app boots, renders its three tabs, and stays exception-free when the
duration selector changes.
"""

import datetime as dt

import pandas as pd
import pytest

from live import fetch_live


def _prices(date):
    """A 24-hour arbitrage day: cheap first half, expensive second half."""
    times = pd.date_range(f"{date}T00:00:00Z", periods=24, freq="60min")
    da = [20.0 if i < 12 else 80.0 for i in range(24)]
    return pd.DataFrame({"day_ahead_price": da, "mid_price": [p + 1.0 for p in da]}, index=times)


def _context(_date):
    return {"wind_gwh": 120.0, "solar_gwh": 0.0, "demand_gwh": 700.0, "wind_share": 0.42}


@pytest.fixture
def app(monkeypatch):
    import dashboard.live_app as live_app

    monkeypatch.setattr(
        fetch_live, "get_day_prices", lambda d: _prices(d.isoformat() if isinstance(d, dt.date) else d)
    )
    monkeypatch.setattr(fetch_live, "get_day_context", _context)
    # Keep the smoke test fast — settle a handful of days, not the full window.
    monkeypatch.setattr(live_app, "_MAX_HISTORY_DAYS", 5)
    # Drop any cached real data from other runs so the mocks take effect.
    live_app._fetch_day.clear()
    live_app._settle_range.clear()
    return live_app


def test_app_boots_with_three_tabs(app):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("dashboard/live_app.py", default_timeout=60)
    at.run()

    assert not at.exception
    assert [t.label for t in at.tabs] == ["Latest", "History", "Day-types", "Methodology"]
    assert "Cycle target (cycles/day)" in [s.label for s in at.slider]
    assert len(at.metric) >= 4  # Latest KPIs + History KPIs


def test_duration_change_does_not_error(app):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("dashboard/live_app.py", default_timeout=60)
    at.run()
    at.radio[0].set_value("4h").run()
    assert not at.exception
