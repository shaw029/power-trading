"""Smoke tests for the live GB BESS benchmark chart builders.

Each builder is fed a small synthetic DataFrame and must return a populated
Plotly figure. These exercise the additive builders without touching the
existing dashboard charts.
"""

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts import (
    chart_daytype_profiles,
    chart_daytype_scatter,
    chart_duration_comparison,
    chart_equity_curve,
    chart_price_capture,
)
from live.figures import _da_sched_df, _dispatch_df


def test_chart_price_capture_returns_figure_and_spread():
    # Charge at hour 2 (£10), discharge at hour 18 (£90): clear positive spread.
    df = pd.DataFrame(
        {
            "hour": [2, 18],
            "final_mw": [-50.0, 50.0],
            "da_price": [10.0, 90.0],
        }
    )
    fig = chart_price_capture(df, duration_h=1.0)
    assert isinstance(fig, go.Figure)
    # discharge bars, charge bars, DA-price line.
    assert len(fig.data) == 3
    # Achieved spread (90 - 10 = 80) is surfaced in the title.
    assert "80.00" in fig.layout.title.text


def test_chart_price_capture_handles_no_charge_or_discharge():
    df = pd.DataFrame({"hour": [5], "final_mw": [0.0], "da_price": [40.0]})
    fig = chart_price_capture(df)
    assert isinstance(fig, go.Figure)


def test_chart_duration_comparison_returns_figure():
    df = pd.DataFrame(
        {
            "duration": ["1h", "2h", "4h"],
            "net_pnl": [10_000.0, 18_000.0, 25_000.0],
        }
    )
    fig = chart_duration_comparison(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


def test_chart_daytype_scatter_returns_figure():
    df = pd.DataFrame(
        {
            "da_spread": [20.0, 35.0, 15.0, 40.0],
            "net_pnl": [500.0, 900.0, 300.0, 1100.0],
            "day_type": ["windy", "sunny", "calm", "windy"],
        }
    )
    fig = chart_daytype_scatter(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


def test_chart_equity_curve_returns_figure():
    dates = pd.date_range("2025-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "date": list(dates) * 2,
            "duration": ["1h"] * 3 + ["4h"] * 3,
            "net_pnl": [100.0, 120.0, 90.0, 200.0, 210.0, 180.0],
        }
    )
    fig = chart_equity_curve(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


def test_chart_daytype_profiles_returns_figure():
    hours = list(range(4))
    df = pd.DataFrame(
        {
            "hour": hours * 2,
            "soc": [0.5, 0.4, 0.3, 0.6, 0.55, 0.45, 0.35, 0.65],
            "day_type": ["windy"] * 4 + ["calm"] * 4,
        }
    )
    fig = chart_daytype_profiles(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


def test_dispatch_df_empty_keeps_columns():
    df = _dispatch_df({"dispatch": []}, timestamps=[])
    assert df.empty
    assert list(df.columns) == ["timestamp", "da_mw", "intraday_mw", "soc_after"]


def test_da_sched_df_empty_keeps_columns():
    prices = {"timestamps": [], "da": []}
    df = _da_sched_df({"schedule_mw": []}, prices)
    assert df.empty
    assert list(df.columns) == ["timestamp", "da_mw", "da_price_pred"]
