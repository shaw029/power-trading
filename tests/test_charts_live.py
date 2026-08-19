"""Smoke tests for the live GB BESS benchmark chart builders.

Each builder is fed a small synthetic DataFrame and must return a populated
Plotly figure. These exercise the additive builders without touching the
existing dashboard charts.
"""

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts import (
    chart_alignment_day,
    chart_capture_spread_daily,
    chart_alignment_scatter,
    chart_cycles_vs_revenue,
    chart_daytype_capture,
    chart_daytype_frequency,
    chart_daytype_matrix,
    chart_daytype_profiles,
    chart_daytype_ratio,
    chart_day_composite,
    chart_operation_explorer,
    chart_day_in_window,
    chart_duration_comparison,
    chart_equity_curve,
    chart_fleet_leaderboard,
    chart_fleet_spread,
    chart_gap_by_daytype,
    chart_generation_daily,
    chart_generation_mix,
    chart_renewable_daily,
    chart_price_capture,
    chart_price_volatility,
    chart_shape_overlay,
    chart_stress_frequency,
    chart_stress_vs_demand,
    chart_sim_vs_fleet_daily,
    chart_sim_vs_fleet_sites,
    chart_system_prices,
    chart_system_tightness,
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


def test_chart_renewable_daily_plots_percentage_and_energy_hover():
    daily = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "Wind": [100.0, 120.0],
            "Solar": [10.0, 20.0],
            "Gas": [90.0, 60.0],
        }
    )
    fig = chart_renewable_daily(daily, ["Wind", "Solar"])
    assert isinstance(fig, go.Figure)
    assert list(fig.data[0].y) == [0.55, 0.7]
    assert list(fig.data[0].customdata) == [110.0, 140.0]
    assert fig.layout.yaxis.tickformat == ".0%"
    assert tuple(fig.layout.yaxis.range) == (0, 1)


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


def test_chart_system_tightness_panels_threshold_and_shading():
    idx = pd.date_range("2026-06-01T00:00:00Z", periods=8, freq="30min")
    tiers = pd.DataFrame(
        {
            "drm_mw": [9000.0, 8000, 1500, 1400, 6000, 7000, 8000, 9000],
            "lolp": [0.0, 0.0, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0],
            "tier1": [False] * 8,
            "tier2": [False, False, True, True, False, False, False, False],
            "tier2_known": [True] * 8,
            "tier3": [False] * 4 + [True, True, False, False],
        },
        index=idx,
    )
    dispatch = pd.Series(
        [0.0, -50.0, 50.0, 0.0],
        index=pd.date_range("2026-06-01T00:00:00Z", periods=4, freq="1h"),
    )
    fig = chart_system_tightness(tiers, dispatch, drm_tight_mw=2000.0)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 3  # DRM line + LoLP markers + dispatch bars
    # One tier-2 span and one tier-3 span, each drawn on both subplot rows,
    # plus the dotted threshold line.
    assert len(fig.layout.shapes) == 5
    # The CMN band is annotated so the rare event is named on the chart.
    assert any(a.text == "CMN" for a in fig.layout.annotations)


def test_chart_system_tightness_survives_empty_frame():
    empty = pd.DataFrame(columns=["drm_mw", "lolp", "tier1", "tier2", "tier2_known", "tier3"])
    fig = chart_system_tightness(empty, dispatch_mw=None)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0

    idx = pd.date_range("2026-06-01T00:00:00Z", periods=4, freq="30min")
    all_nan = pd.DataFrame(
        {
            "drm_mw": [float("nan")] * 4,
            "lolp": [float("nan")] * 4,
            "tier1": [False] * 4,
            "tier2": [False] * 4,
            "tier2_known": [False] * 4,
            "tier3": [False] * 4,
        },
        index=idx,
    )
    fig = chart_system_tightness(all_nan, dispatch_mw=pd.Series(dtype=float))
    assert isinstance(fig, go.Figure)


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


def test_chart_day_composite_four_panels_with_shading():
    hidx = pd.date_range("2026-06-01T00:00:00Z", periods=24, freq="1h")
    prices = pd.DataFrame(
        {"day_ahead_price": range(40, 64), "mid_price": range(38, 62)}, index=hidx
    )
    dispatch = pd.Series([0.0] * 8 + [-50.0] * 4 + [0.0] * 6 + [50.0] * 4 + [0.0] * 2,
                         index=hidx)
    da = dispatch * 0.5
    soc = pd.Series([0.5] * 24, index=hidx)
    fidx = pd.date_range("2026-06-01T00:00:00Z", periods=48, freq="30min")
    flags = pd.DataFrame(
        {
            "residual_mw": [20000.0] * 36 + [27000.0] * 8 + [20000.0] * 4,
            "stress": [False] * 36 + [True] * 8 + [False] * 4,
            "surplus": [False] * 16 + [True] * 8 + [False] * 24,
        },
        index=fidx,
    )
    fig = chart_day_composite(prices, dispatch, da, soc, flags, 0.1, 0.9)
    assert isinstance(fig, go.Figure)
    # DA line, MID line, commitment step, dispatch bars, SOC, residual.
    assert len(fig.data) == 6


def test_chart_day_composite_survives_empty_flags():
    hidx = pd.date_range("2026-06-01T00:00:00Z", periods=4, freq="1h")
    prices = pd.DataFrame({"day_ahead_price": [40.0] * 4, "mid_price": [41.0] * 4},
                          index=hidx)
    zeros = pd.Series([0.0] * 4, index=hidx)
    fig = chart_day_composite(prices, zeros, zeros, zeros + 0.5, pd.DataFrame(), 0.1, 0.9)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 5  # no residual trace


def test_chart_day_in_window_marks_current():
    daily = pd.Series([50.0, 80.0, 90.0, 120.0, 60.0])
    fig = chart_day_in_window(daily, 90.0)
    assert isinstance(fig, go.Figure)
    assert fig.layout.shapes[0].x0 == 90.0


def _system_window() -> pd.DataFrame:
    """Five days of the System page's daily summary frame."""
    return pd.DataFrame(
        {
            "date": ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"],
            "da_min": [-15.0, 10.0, 5.0, -40.0, 22.0],
            "da_p10": [0.0, 20.0, 15.0, -5.0, 30.0],
            "avg_da": [55.0, 62.0, 48.0, 40.0, 70.0],
            "da_p90": [110.0, 95.0, 88.0, 105.0, 120.0],
            "da_max": [180.0, 130.0, 99.0, 312.0, 150.0],
            "peak_demand_gw": [31.2, 32.8, 30.4, 34.1, 33.0],
            "peak_residual_gw": [24.0, 27.8, 21.5, 26.9, 25.1],
        }
    )


def test_chart_price_volatility_bands_and_mean():
    fig = chart_price_volatility(_system_window())
    assert isinstance(fig, go.Figure)
    # Two nested bands (two traces each: invisible upper edge + filled lower)
    # plus the mean line.
    assert len(fig.data) == 5
    assert fig.data[-1].name == "Daily mean"
    assert [t.name for t in fig.data if t.name] == ["Min–max", "P10–P90", "Daily mean"]


def test_chart_price_volatility_survives_missing_band_columns():
    df = _system_window().drop(columns=["da_min", "da_max"])
    fig = chart_price_volatility(df)
    assert isinstance(fig, go.Figure)
    assert [t.name for t in fig.data if t.name] == ["P10–P90", "Daily mean"]


def test_chart_stress_vs_demand_two_lines():
    fig = chart_stress_vs_demand(_system_window())
    assert isinstance(fig, go.Figure)
    assert [t.name for t in fig.data] == ["Peak demand", "Peak residual load"]
    # The gap between the lines is the point, so the residual line is filled.
    assert fig.data[1].fill == "tonexty"


def test_chart_stress_vs_demand_without_residual():
    df = _system_window().drop(columns=["peak_residual_gw"])
    fig = chart_stress_vs_demand(df)
    assert len(fig.data) == 1


def test_chart_stress_frequency_two_grouped_series():
    df = pd.DataFrame(
        {
            "date": ["2026-08-01", "2026-08-02", "2026-08-03"],
            "stress": [4, 0, 6],
            "negative": [0, 3, 0],
        }
    )
    fig = chart_stress_frequency(df)
    assert isinstance(fig, go.Figure)
    assert [t.name for t in fig.data] == ["Top-decile stress", "Negative price"]
    # Grouped, not stacked: the two states can coincide, so a stack would imply
    # a total that does not exist.
    assert fig.layout.barmode == "group"


def test_chart_stress_frequency_survives_empty():
    fig = chart_stress_frequency(pd.DataFrame(columns=["date"]))
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0


def test_chart_fleet_spread_band_and_median():
    dist = pd.DataFrame(
        {
            "date": ["2026-08-01", "2026-08-02", "2026-08-03"],
            "median": [30.0, 42.0, 28.0],
            "p25": [20.0, 31.0, 19.0],
            "p75": [40.0, 55.0, 36.0],
            "min": [5.0, 12.0, 8.0],
            "max": [90.0, 120.0, 70.0],
        }
    )
    fig = chart_fleet_spread(dist, "revenue")
    assert isinstance(fig, go.Figure)
    # Two nested bands (upper edge + filled lower edge each) plus the median.
    assert len(fig.data) == 5
    assert [t.name for t in fig.data if t.name] == ["Min–max", "P25–P75", "Median site"]
    # Each band is named for a range, so its tooltip carries both ends.
    band = fig.data[3]
    assert list(band.customdata) == [40.0, 55.0, 36.0]
    assert "customdata" in band.hovertemplate


def test_chart_fleet_spread_unknown_metric_still_renders():
    dist = pd.DataFrame(
        {"date": ["2026-08-01"], "median": [1.0], "p25": [0.5], "p75": [1.5],
         "min": [0.1], "max": [2.0]}
    )
    fig = chart_fleet_spread(dist, "not-a-metric")
    assert isinstance(fig, go.Figure)


def test_chart_fleet_spread_refuses_a_frame_missing_a_bound():
    import pytest

    # Skipping the band quietly is how a chart ends up titled "full range"
    # while drawing none — which is exactly what shipped.
    dist = pd.DataFrame(
        {"date": ["2026-08-01"], "median": [1.0], "p25": [0.5], "p75": [1.5]}
    )
    with pytest.raises(KeyError, match="min"):
        chart_fleet_spread(dist, "revenue")


def test_leaderboard_flips_negative_capture_spread_to_red():
    from dashboard.charts import COLORS

    df = pd.DataFrame(
        {
            "site": ["A", "B", "C"], "optimiser": ["X", "Y", "Z"],
            "capture_spread": [95.0, -156.0, 40.0],
            "gbp_per_mw_day": [200.0, -50.0, 80.0],
            "cycles_per_day": [1.2, 0.4, 0.9],
            "power_mw": [100.0, 50.0, 99.0],
            "discharge_mwh": [500.0, 100.0, 300.0],
            "charge_mwh": [500.0, 100.0, 300.0],
            "days": [5, 5, 5], "total_gbp": [1000.0, -500.0, 800.0],
        }
    )
    # Capture spread goes negative when a site pays more to charge than it
    # earns discharging — the same failure revenue signals, so the same red.
    colours = list(chart_fleet_leaderboard(df, "capture").data[0].marker.color)
    assert colours.count(COLORS["cost"]) == 1
    # Cycles cannot be negative, so nothing flips.
    assert COLORS["cost"] not in list(chart_fleet_leaderboard(df, "cycles").data[0].marker.color)


def test_chart_capture_spread_daily_lines_and_wear_threshold():
    df = pd.DataFrame(
        {
            "date": ["2026-08-01", "2026-08-02", "2026-08-03"],
            "capture_spread": [80.0, 12.0, 45.0],
        }
    )
    fig = chart_capture_spread_daily(df, degradation_cost=5.0)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    # Window mean and the wear line the lever is set to.
    assert len(fig.layout.shapes) == 2
    texts = [a.text for a in fig.layout.annotations]
    assert any("degradation" in t for t in texts)


def test_chart_capture_spread_daily_without_degradation_lever():
    df = pd.DataFrame({"date": ["2026-08-01"], "capture_spread": [80.0]})
    fig = chart_capture_spread_daily(df, degradation_cost=0.0)
    # Mean only — no wear line to draw when the lever is off.
    assert len(fig.layout.shapes) == 1


def test_price_capture_days_divides_into_a_daily_average():
    df = pd.DataFrame(
        {
            "hour": [18, 18, 3, 3],
            "final_mw": [50.0, 50.0, -50.0, -50.0],
            "da_price": [90.0, 90.0, 10.0, 10.0],
        }
    )
    totals = chart_price_capture(df, duration_h=1.0)
    per_day = chart_price_capture(df, duration_h=1.0, days=2)
    hour18 = list(totals.data[0].y)[18]
    hour18_daily = list(per_day.data[0].y)[18]
    assert hour18 == 100.0
    assert hour18_daily == 50.0
    assert "per day" in per_day.layout.yaxis.title.text
    assert "per day" not in totals.layout.yaxis.title.text


def _explorer_frames(days: int):
    idx = pd.date_range("2026-08-01T00:00:00Z", periods=24 * days, freq="1h")
    dispatch = pd.DataFrame(
        {"timestamp": idx, "final_mw": 0.0, "da_mw": 0.0, "intraday_mw": 0.0,
         "soc_after": 0.5, "da_price": 100.0, "mid_price": 100.0}
    )
    prices = pd.DataFrame({"day_ahead_price": 100.0, "mid_price": 100.0}, index=idx)
    sched = pd.DataFrame({"timestamp": idx, "da_mw": 0.0, "da_price_pred": 100.0})
    return prices, dispatch, sched


def test_explorer_opens_on_five_days_but_holds_the_whole_window():
    from dashboard.charts import EXPLORER_VIEW_DAYS

    fig = chart_operation_explorer(*_explorer_frames(30), 0.1, 0.9)
    lo, hi = (pd.Timestamp(v) for v in fig.layout.xaxis.range)
    assert (hi - lo).days == EXPLORER_VIEW_DAYS
    # The slider itself is left to autorange, so it spans everything selected
    # — five days is the viewport, not a limit on what can be scrolled to.
    assert fig.layout.xaxis.rangeslider.range is None
    assert fig.layout.xaxis.rangeslider.visible


def test_explorer_viewport_never_overshoots_a_short_window():
    fig = chart_operation_explorer(*_explorer_frames(2), 0.1, 0.9)
    lo, hi = (pd.Timestamp(v) for v in fig.layout.xaxis.range)
    assert (hi - lo) <= pd.Timedelta(days=2)
