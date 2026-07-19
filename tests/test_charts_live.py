"""Smoke tests for the live GB BESS benchmark chart builders.

Each builder is fed a small synthetic DataFrame and must return a populated
Plotly figure. These exercise the additive builders without touching the
existing dashboard charts.
"""

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts import (
    chart_alignment_day,
    chart_alignment_scatter,
    chart_cycles_vs_revenue,
    chart_daytype_capture,
    chart_daytype_frequency,
    chart_daytype_matrix,
    chart_daytype_profiles,
    chart_daytype_ratio,
    chart_duration_comparison,
    chart_equity_curve,
    chart_gap_by_daytype,
    chart_generation_daily,
    chart_generation_mix,
    chart_price_capture,
    chart_shape_overlay,
    chart_sim_vs_fleet_daily,
    chart_sim_vs_fleet_sites,
    chart_system_prices,
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


def test_chart_sim_vs_fleet_sites_stacks_legs_and_marks_ceiling():
    df = pd.DataFrame(
        {
            "site": ["A", "B"],
            "optimiser": ["OptX", "OptY"],
            "wholesale": [80.0, 40.0],
            "bm": [20.0, 35.0],
            "ratio": [0.8, 0.4],
        }
    )
    fig = chart_sim_vs_fleet_sites(df, sim_gbp=100.0, sim_label="sim 2h ceiling")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2  # wholesale + BM traces; the ceiling is a vline
    assert fig.layout.shapes[0].x0 == 100.0


def test_chart_sim_vs_fleet_daily_returns_figure():
    df = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-02"],
            "sim": [120.0, 90.0],
            "fleet": [70.0, 65.0],
        }
    )
    fig = chart_sim_vs_fleet_daily(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2


def test_chart_shape_overlay_returns_figure():
    df = pd.DataFrame(
        {
            "hour": list(range(24)),
            "fleet": [0.1] * 12 + [-0.1] * 12,
            "sim": [0.5] * 12 + [-0.5] * 12,
        }
    )
    fig = chart_shape_overlay(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2


def test_chart_cycles_vs_revenue_ghosts_excluded_sites():
    df = pd.DataFrame(
        {
            "site": ["A", "B", "C"],
            "optimiser": ["X", "Y", "Z"],
            "cycles_per_day": [1.1, 0.9, 0.1],
            "gbp_per_mw_day": [90.0, 70.0, 5.0],
            "excluded": [False, False, True],
        }
    )
    fig = chart_cycles_vs_revenue(df, sim_cycles=1.4, sim_gbp=120.0)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 3  # sites, ghosts, sim star


def test_chart_generation_mix_stacks_groups_and_demand():
    idx = pd.date_range("2024-01-01T00:00:00Z", periods=4, freq="30min")
    groups = pd.DataFrame(
        {
            "Wind": [1000.0, 1100.0, 1200.0, 1050.0],
            "Gas": [2000.0, 1900.0, 1800.0, 1850.0],
            "Interconnectors": [500.0, -200.0, 300.0, 400.0],
        },
        index=idx,
    )
    demand = pd.Series([3400.0, 2900.0, 3200.0, 3250.0], index=idx)
    fig = chart_generation_mix(groups, demand)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 4  # three stacked groups + demand line
    assert fig.data[-1].name == "Demand (outturn)"


def test_chart_generation_mix_without_demand():
    idx = pd.date_range("2024-01-01T00:00:00Z", periods=2, freq="30min")
    groups = pd.DataFrame({"Wind": [1000.0, 1100.0]}, index=idx)
    fig = chart_generation_mix(groups)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1


def test_chart_generation_daily_stacks_one_bar_per_day():
    daily = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "Wind": [200.0, 240.0, 180.0],
            "Gas": [120.0, 100.0, 150.0],
            "Interconnectors": [40.0, -20.0, 30.0],
        }
    )
    fig = chart_generation_daily(daily, ["Wind", "Gas", "Interconnectors"])
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 3  # one stacked bar series per group
    assert fig.layout.barmode == "relative"


def test_chart_system_prices_returns_figure():
    idx = pd.date_range("2024-01-01T00:00:00Z", periods=24, freq="60min")
    prices = pd.DataFrame(
        {"day_ahead_price": range(50, 74), "mid_price": range(48, 72)}, index=idx
    )
    fig = chart_system_prices(prices)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2


def test_chart_daytype_ratio_returns_figure():
    df = pd.DataFrame(
        {
            "tag": ["windy", "volatile"],
            "family": ["driver", "price"],
            "ratio": [0.6, 0.45],
            "days": [10, 4],
        }
    )
    fig = chart_daytype_ratio(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1


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


def test_chart_alignment_day_two_panels_with_shading():
    idx = pd.date_range("2026-06-01T00:00:00Z", periods=8, freq="30min")
    flags = pd.DataFrame(
        {
            "residual_mw": [20000.0, 21000, 22000, 25000, 26000, 24000, 15000, 12000],
            "stress": [False, False, False, True, True, False, False, False],
            "surplus": [False] * 6 + [True, True],
        },
        index=idx,
    )
    dispatch = pd.Series(
        [0.0, -50.0, 0.0, 50.0],
        index=pd.date_range("2026-06-01T00:00:00Z", periods=4, freq="1h"),
    )
    fig = chart_alignment_day(flags, dispatch)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2                      # residual line + dispatch bars
    # One stress + one surplus band, each drawn on both subplot rows.
    assert len(fig.layout.shapes) == 4


def test_chart_alignment_scatter_ghosts_excluded_and_stars_benchmark():
    df = pd.DataFrame(
        {
            "site": ["A", "B", "C"],
            "optimiser": ["x", "y", "z"],
            "stress_coverage": [0.5, 0.2, 0.7],
            "gbp_per_mw_day": [80.0, 30.0, 70.0],
            "excluded": [False, True, False],
        }
    )
    fig = chart_alignment_scatter(df, sim_coverage=0.6, sim_gbp=90.0)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 3                      # sites, ghosts, benchmark star


def test_chart_gap_by_daytype_returns_figure():
    df = pd.DataFrame(
        {
            "tag": ["windy", "volatile"],
            "family": ["driver", "price"],
            "gap": [40.0, 90.0],
            "days": [7, 3],
        }
    )
    fig = chart_gap_by_daytype(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
