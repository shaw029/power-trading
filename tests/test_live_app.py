"""Headless smoke test for the live Streamlit dashboard.

Every AppTest here allows 120s. The pages now do markedly more work per run —
physical-delivery reconstruction, tier classification, several more charts —
and at 60s the harness tripped intermittently on whichever test happened to run
under load, while the suite as a whole still finished in under 20s.

``live.fetch_live`` and the ``fleet`` fetchers are mocked so no network call
happens, and Streamlit's ``AppTest`` runs the script in-process and surfaces
any exception. This proves the app boots, renders its tabs, and stays
exception-free when the duration selector changes.
"""

import datetime as dt
import pathlib
import threading

import pandas as pd
import pytest

from fleet import fetch_fleet
from live import fetch_live

#: Absolute, because streamlit resolves a relative AppTest path against the file
#: that calls it (from 1.63) rather than the working directory, so "dashboard/
#: live_app.py" started resolving to tests/dashboard/live_app.py.
APP = str(pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "live_app.py")


def _prices(date):
    """A 24-hour arbitrage day: cheap first half, expensive second half."""
    times = pd.date_range(f"{date}T00:00:00Z", periods=24, freq="60min")
    da = [20.0 if i < 12 else 80.0 for i in range(24)]
    return pd.DataFrame({"day_ahead_price": da, "mid_price": [p + 1.0 for p in da]}, index=times)


def _context(_date):
    return {"wind_gwh": 120.0, "solar_gwh": 0.0, "demand_gwh": 700.0, "wind_share": 0.42}


def _fleet_pn(date, population=None):
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
            "notice_id",
            "type_id",
            "type_name",
            "title",
            "posted_utc",
            "start_utc",
            "end_utc",
        ]
    )


@pytest.fixture
def app(monkeypatch):
    import dashboard.live_app as live_app

    monkeypatch.setattr(
        fetch_live,
        "get_day_prices",
        lambda d: _prices(d.isoformat() if isinstance(d, dt.date) else d),
    )
    monkeypatch.setattr(fetch_live, "get_day_context", _context)
    monkeypatch.setattr(fetch_fleet, "fetch_fleet_pn", _fleet_pn)
    monkeypatch.setattr(
        fetch_fleet, "fetch_fleet_bm_cashflows", lambda d, p=None: {"bid": [], "offer": []}
    )
    monkeypatch.setattr(fetch_fleet, "fetch_day_mid_prices", _fleet_mid)
    # Physical delivery needs acceptances; without this the suite silently
    # starts hitting Elexon, which is exactly what this fixture exists to stop.
    monkeypatch.setattr(fetch_fleet, "fetch_fleet_boalf", lambda d, p=None: [])
    monkeypatch.setattr(fetch_live, "get_day_system", _system)
    monkeypatch.setattr(fetch_live, "get_day_lolpdrm", _lolpdrm)
    monkeypatch.setattr(fetch_live, "get_cmn_notices", _no_cmn)
    # Keep the smoke test fast. Three days is enough for every assertion here,
    # and the alignment page solves a resilience LP per settled day — at five
    # days the four AppTest runs in one process contended enough that one of
    # them, varying between runs, tripped the harness timeout.
    monkeypatch.setattr(live_app, "_MAX_HISTORY_DAYS", 3)
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


def test_prefetch_fleet_days_covers_every_day_and_survives_failures(monkeypatch):
    """The parallel prefetch must touch each day exactly once and swallow the
    failures the sequential path already tolerated."""
    import dashboard.live_app as live_app

    seen: list[str] = []
    lock = threading.Lock()

    def record(date, population=None):
        with lock:
            seen.append(date.isoformat())
        return []

    def boom(date, population=None):
        raise RuntimeError("Elexon unavailable")

    monkeypatch.setattr(fetch_fleet, "fetch_fleet_pn", record)
    monkeypatch.setattr(fetch_fleet, "fetch_day_mid_prices", record)
    monkeypatch.setattr(fetch_fleet, "fetch_fleet_boalf", boom)
    monkeypatch.setattr(fetch_fleet, "fetch_fleet_bm_cashflows", record)

    days = [f"2024-01-{d:02d}" for d in range(1, 13)]
    live_app._prefetch_fleet_days(days, bar=None)  # must not raise

    # Three surviving fetchers per day, and no day dropped by the pool.
    assert sorted(set(seen)) == sorted(days)
    assert len(seen) == 3 * len(days)


def test_prefetch_fleet_days_is_a_noop_on_an_empty_window(monkeypatch):
    import dashboard.live_app as live_app

    def fail(date, population=None):
        raise AssertionError("must not fetch for an empty window")

    monkeypatch.setattr(fetch_fleet, "fetch_fleet_pn", fail)
    live_app._prefetch_fleet_days([], bar=None)


def test_app_boots_on_latest_day_page(app):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=120)
    at.run()

    assert not at.exception
    # The default page is the benchmark's Latest day view: the sidebar carries
    # the parameter form and the page shows the four-KPI row.
    assert "Cycle target (cycles/day)" in [s.label for s in at.slider]
    labels = [m.label for m in at.metric]
    # Twelve numbers in three groups: what the model did, what the grid did,
    # what the real fleet did.
    assert len(labels) == 12
    assert labels[0].startswith("Net PnL")
    assert labels[1].startswith("Intraday improvement")
    assert labels[4].startswith("DA P90−P10 spread")
    assert labels[8].startswith("Fleet median PnL")
    # Capture (share of the DA optimum) and DA benchmark came off the page.
    assert not any(la == "Capture" or la.startswith("DA benchmark") for la in labels)


def test_alignment_page_renders_system_tightness(app):
    from streamlit.testing.v1 import AppTest
    from streamlit.testing.v1.app_test import calc_hash

    at = AppTest.from_file(APP, default_timeout=120)
    # Function pages hash on their url_path (st.Page(..., url_path="alignment")),
    # and AppTest.switch_page only accepts file paths — target the hash directly.
    at._page_hash = calc_hash("alignment")
    at.run()

    assert not at.exception
    # Labels carry their unit on a second line (_unit_label), so match the name
    # rather than the whole string — otherwise adding a unit breaks the test
    # without anything being wrong.
    labels = [m.label.split("  \n")[0] for m in at.metric]
    # The System tightness KPI row rendered, including the no-CMN degradation
    # path ("None in window" with an empty register).
    assert "Min de-rated margin" in labels
    assert "Capacity Market Notices" in labels
    assert "Coverage when confirmed tight" in labels
    # The utilisation lane must not borrow scarcity words: top-decile load is
    # when the system works hardest, which is not the same as being short.
    assert "Top-decile coverage" in labels
    assert not any("stress" in la.lower() for la in labels)


def test_regimes_page_renders_the_two_family_charts(app):
    from streamlit.testing.v1 import AppTest
    from streamlit.testing.v1.app_test import calc_hash

    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("regimes")
    at.run()

    assert not at.exception
    titles = [c.proto.spec for c in at.get("plotly_chart")]
    # Seven: capture, yield/wear, crossing matrix, frequency, SOC profiles,
    # market reliance, and the intraday-deviation profile.
    assert len(at.get("plotly_chart")) == 7, titles


def test_system_page_renders_price_and_stress_kpis(app):
    from streamlit.testing.v1 import AppTest
    from streamlit.testing.v1.app_test import calc_hash

    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("system")
    at.run()

    assert not at.exception
    labels = [m.label for m in at.metric]
    # Two rows of four: prices, then demand and stress.
    # The unit sits on a second label line so the value stays a bare,
    # comparable number.
    assert labels == [
        "Renewable share",
        "Avg wholesale price  \n£/MWh",
        "Highest wholesale price  \n£/MWh",
        "Lowest wholesale price  \n£/MWh",
        "Negative price count  \nhours",
        "Max daily P90–P10 spread  \n£/MWh",
        "Max daily peak demand  \nGW",
        "Peak residual load  \nGW",
    ]
    values = [m.value for m in at.metric]
    assert all("£" not in v and "GW" not in v for v in values)
    # Percent is the exception: it stays welded to the value, and its label
    # carries no unit line.
    assert values[0].endswith("%")
    assert "\n" not in labels[0]
    # Days shown moved into the header badge, so it is no longer a KPI tile,
    # and the two retired numbers are gone.
    assert "Days shown" not in labels
    assert "Avg peak demand" not in labels
    assert "Net interconnectors" not in labels


def test_fleet_page_kpis_follow_the_metric_switch(app):
    from streamlit.testing.v1 import AppTest
    from streamlit.testing.v1.app_test import calc_hash

    at = AppTest.from_file(APP, default_timeout=120)
    at._page_hash = calc_hash("fleet")
    at.run()

    assert not at.exception
    labels = [m.label for m in at.metric]
    assert labels == [
        "Active capacity  \nMW",
        "Operator dispersion  \n£/MW/day",
        "Fleet baseline  \n£/MW/day",
        "Top performer",
    ]
    # One mocked site, so an interquartile spread has nothing to measure and
    # says so rather than inventing a number.
    assert at.metric[1].value == "—"
    assert at.metric[3].value == "Pillswood"

    # Switching the metric re-labels and re-computes the numbers, not just the
    # charts — the whole point of this page's rebuild.
    at.segmented_control[0].set_value("Capture spread").run()
    assert not at.exception
    relabelled = [m.label for m in at.metric]
    assert relabelled[1] == "Operator dispersion  \n£/MWh"
    assert relabelled[2] == "Fleet baseline  \n£/MWh"


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

    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    # The levers sit in a sidebar form: pick a new duration, then Apply.
    at.radio[0].set_value("4h")
    apply_btn = next(b for b in at.button if b.label == "Apply")
    apply_btn.set_value(True).run()
    assert not at.exception
    assert "4h" in at.radio[0].value
