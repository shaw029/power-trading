"""Headless smoke test for the live Streamlit dashboard.

``live.fetch_live`` and the ``fleet`` fetchers are mocked so no network call
happens, and Streamlit's ``AppTest`` runs the script in-process and surfaces
any exception. This proves the app boots, renders its tabs, and stays
exception-free when the duration selector changes.
"""

import datetime as dt

import pandas as pd
import pytest

from fleet import fetch_fleet
from live import fetch_live


def _prices(date):
    """A 24-hour arbitrage day: cheap first half, expensive second half."""
    times = pd.date_range(f"{date}T00:00:00Z", periods=24, freq="60min")
    da = [20.0 if i < 12 else 80.0 for i in range(24)]
    return pd.DataFrame({"day_ahead_price": da, "mid_price": [p + 1.0 for p in da]}, index=times)


def _context(_date):
    return {"wind_gwh": 120.0, "solar_gwh": 0.0, "demand_gwh": 700.0, "wind_share": 0.42}


def _fleet_pn(date):
    """One half-hour 50 MW discharge on a real fleet BMU."""
    start = pd.Timestamp(f"{date.isoformat()}T18:00:00Z")
    return [
        {
            "bmUnit": "E_PILLB-1",
            "settlementDate": date.isoformat(),
            "timeFrom": start.isoformat(),
            "timeTo": (start + pd.Timedelta(minutes=30)).isoformat(),
            "levelFrom": 50.0,
            "levelTo": 50.0,
        }
    ]


def _fleet_mid(date):
    times = pd.date_range(f"{date.isoformat()}T00:00:00Z", periods=48, freq="30min")
    return pd.DataFrame({"mid_price": 80.0}, index=times)


def _system(date):
    """Half-hourly system snapshot: enough structure for residual load,
    stress/surplus classification and the generation-mix stack."""
    iso = date.isoformat() if isinstance(date, dt.date) else str(date)
    times = pd.date_range(f"{iso}T00:00:00Z", periods=48, freq="30min")
    demand = [25000.0 if i < 36 else 30000.0 for i in range(48)]  # evening peak
    return pd.DataFrame(
        {
            "gen_WIND": 8000.0,
            "gen_CCGT": 9000.0,
            "solar_mw": [4000.0 if 18 <= i <= 30 else 0.0 for i in range(48)],
            "demand_actual": demand,
        },
        index=times,
    )


def _lolpdrm(date):
    """Half-hourly LoLP/DRM with one tight period (DRM < 2,000) and one LoLP>0."""
    iso = date.isoformat() if isinstance(date, dt.date) else str(date)
    times = pd.date_range(f"{iso}T00:00:00Z", periods=48, freq="30min")
    drm = [9000.0] * 48
    lolp = [0.0] * 48
    drm[36] = 1500.0  # evening-peak tight half-hour
    lolp[37] = 0.05
    return pd.DataFrame({"lolp": lolp, "drm_mw": drm}, index=times)


def _no_cmn():
    """Empty register — the normal case; the page must degrade gracefully."""
    return pd.DataFrame(
        columns=[
            "notice_id", "type_id", "type_name", "title",
            "posted_utc", "start_utc", "end_utc",
        ]
    )


@pytest.fixture
def app(monkeypatch):
    import dashboard.live_app as live_app

    monkeypatch.setattr(
        fetch_live, "get_day_prices", lambda d: _prices(d.isoformat() if isinstance(d, dt.date) else d)
    )
    monkeypatch.setattr(fetch_live, "get_day_context", _context)
    monkeypatch.setattr(fetch_fleet, "fetch_fleet_pn", _fleet_pn)
    monkeypatch.setattr(
        fetch_fleet, "fetch_fleet_bm_cashflows", lambda d: {"bid": [], "offer": []}
    )
    monkeypatch.setattr(fetch_fleet, "fetch_day_mid_prices", _fleet_mid)
    monkeypatch.setattr(fetch_live, "get_day_system", _system)
    monkeypatch.setattr(fetch_live, "get_day_lolpdrm", _lolpdrm)
    monkeypatch.setattr(fetch_live, "get_cmn_notices", _no_cmn)
    # Keep the smoke test fast — settle a handful of days, not the full window.
    monkeypatch.setattr(live_app, "_MAX_HISTORY_DAYS", 5)
    # Drop any cached real data from other runs so the mocks take effect.
    live_app._fetch_day.clear()
    live_app._settle_range.clear()
    live_app._fleet_day.clear()
    live_app._day_labels.clear()
    live_app._system_day.clear()
    live_app._window_flags.clear()
    live_app._system_summary_day.clear()
    live_app._fleet_profile_day.clear()
    live_app._lolpdrm_window.clear()
    live_app._cmn_notices.clear()
    return live_app


def test_app_boots_on_latest_day_page(app):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("dashboard/live_app.py", default_timeout=60)
    at.run()

    assert not at.exception
    # The default page is the benchmark's Latest day view: the sidebar carries
    # the parameter form and the page shows the four-KPI row.
    assert "Cycle target (cycles/day)" in [s.label for s in at.slider]
    assert len(at.metric) >= 4  # Net PnL · DA benchmark · Cycles · Capture


def test_alignment_page_renders_system_tightness(app):
    from streamlit.testing.v1 import AppTest
    from streamlit.testing.v1.app_test import calc_hash

    at = AppTest.from_file("dashboard/live_app.py", default_timeout=120)
    # Function pages hash on their url_path (st.Page(..., url_path="alignment")),
    # and AppTest.switch_page only accepts file paths — target the hash directly.
    at._page_hash = calc_hash("alignment")
    at.run()

    assert not at.exception
    labels = [m.label for m in at.metric]
    # The System tightness KPI row rendered, including the no-CMN degradation
    # path ("None in window" with an empty register).
    assert "Min de-rated margin" in labels
    assert "Capacity Market Notices" in labels
    assert "Tier-2 stress coverage" in labels


def test_system_page_renders_price_and_stress_kpis(app):
    from streamlit.testing.v1 import AppTest
    from streamlit.testing.v1.app_test import calc_hash

    at = AppTest.from_file("dashboard/live_app.py", default_timeout=120)
    at._page_hash = calc_hash("system")
    at.run()

    assert not at.exception
    labels = [m.label for m in at.metric]
    # Two rows of four: prices, then demand and stress.
    assert labels == [
        "Low-carbon share",
        "Avg wholesale price",
        "Highest wholesale price",
        "Lowest wholesale price",
        "Negative price count",
        "Max daily P90–P10 spread",
        "Max daily peak demand",
        "Max system stress",
    ]
    # Days shown moved into the header badge, so it is no longer a KPI tile,
    # and the two retired numbers are gone.
    assert "Days shown" not in labels
    assert "Avg peak demand" not in labels
    assert "Net interconnectors" not in labels


def test_filter_days_by_period_and_day_type():
    import dashboard.live_app as live_app

    days = [
        {"date": "2024-01-01", "labels": ["windy"]},
        {"date": "2024-01-02", "labels": []},
    ]
    full = live_app._filter_days(days, "2024-01-01", "2024-01-02", [])
    assert [d["date"] for d in full] == ["2024-01-01", "2024-01-02"]
    assert [d["date"] for d in live_app._filter_days(days, "2024-01-02", "2024-01-02", [])] == [
        "2024-01-02"
    ]
    windy = live_app._filter_days(days, "2024-01-01", "2024-01-02", ["windy"])
    assert [d["date"] for d in windy] == ["2024-01-01"]
    untagged = live_app._filter_days(days, "2024-01-01", "2024-01-02", ["untagged"])
    assert [d["date"] for d in untagged] == ["2024-01-02"]


def test_duration_change_does_not_error(app):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("dashboard/live_app.py", default_timeout=60)
    at.run()
    # The levers sit in a sidebar form: pick a new duration, then Apply.
    at.radio[0].set_value("4h")
    apply_btn = next(b for b in at.button if b.label == "Apply")
    apply_btn.set_value(True).run()
    assert not at.exception
    assert "4h" in at.radio[0].value
