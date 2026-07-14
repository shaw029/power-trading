"""Smoke tests for the live GB BESS benchmark chart builders.

Each builder is fed a small synthetic DataFrame and must return a populated
Plotly figure. These exercise the additive builders without touching the
existing dashboard charts.
"""

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts import (
    chart_daytype_capture,
    chart_daytype_frequency,
    chart_daytype_matrix,
    chart_daytype_profiles,
    chart_duration_comparison,
    chart_equity_curve,
    chart_price_capture,
)


def _membership() -> pd.DataFrame:
    """Per-(day, tag) membership rows as assembled by the Day types page."""
    return pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-01", "2025-01-02", "2025-01-03"],
            "tag": ["windy", "volatile", "calm", "windy"],
            "family": ["driver", "price", "price", "driver"],
            "capture": [0.7, 0.7, 0.2, 0.55],
        }
    )


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


def test_chart_daytype_capture_orders_and_groups_by_family():
    fig = chart_daytype_capture(_membership())
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 3  # one box per tag
    # Exactly one legend entry per family, not one per tag.
    assert sum(1 for t in fig.data if t.showlegend) == 2


def test_chart_daytype_frequency_counts_days():
    fig = chart_daytype_frequency(_membership())
    assert isinstance(fig, go.Figure)
    counts = dict(zip(fig.data[0].y, fig.data[0].x))
    assert counts["windy"] == 2
    assert counts["calm"] == 1


def test_chart_daytype_matrix_returns_figure():
    matrix = pd.DataFrame(
        [[2, 0], [1, 3]],
        index=["windy", "(none)"],
        columns=["volatile", "(none)"],
    )
    fig = chart_daytype_matrix(matrix)
    assert isinstance(fig, go.Figure)
    assert fig.data[0].z.tolist() == [[2, 0], [1, 3]]


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
