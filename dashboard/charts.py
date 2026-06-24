"""Plotly chart builders for the BESS dispatch dashboard (dashboard/app.py).

Each function takes already-sliced simulation frames and returns a Plotly
figure; they hold no Streamlit or data-loading logic so they can be reused and
tested in isolation.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Default figure height (px) shared by the standard single-panel builders; the
# taller multi-panel/explorer views set their own height explicitly.
DEFAULT_CHART_HEIGHT = 400

# Shared palette. "da"/"intraday" give the frozen benchmark and the consolidated
# intraday improvement their own identity in the waterfall; the remaining buckets
# fall back to the existing green (gain) / red (cost) scheme.
COLORS = {
    "da": "#1f77b4",
    "intraday": "#2ecc71",
    "gain": "#2ecc71",
    "cost": "#e74c3c",
    "net": "#2c3e50",
}


def chart_da_commitment_shape(
    da_sched_df: pd.DataFrame,
    prices_hourly: pd.DataFrame,
):
    """Mean day-ahead committed dispatch and DA price by hour-of-day.

    The planning layer: what the LP locked in against its forecast, before any
    intraday adjustment. Bars are the committed MW (+ discharge / − charge);
    the lines compare the realised DA price against the forecast the schedule
    was optimised on, so forecast bias by hour is visible at a glance.
    """
    sched = da_sched_df.copy()
    sched["hod"] = pd.to_datetime(sched["timestamp"]).dt.hour
    mean_mw = sched.groupby("hod")["da_mw"].mean()
    fc_by_hour = sched.groupby("hod")["da_price_pred"].mean()
    da_by_hour = prices_hourly.groupby(prices_hourly.index.hour)["day_ahead_price"].mean()

    colors = ["#e74c3c" if v > 0 else "#2ecc71" for v in mean_mw.values]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=mean_mw.index,
            y=mean_mw.values,
            name="Mean DA commitment MW",
            yaxis="y2",
            marker_color=colors,
            opacity=0.5,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=da_by_hour.index,
            y=da_by_hour.values,
            name="Mean DA price (actual)",
            yaxis="y",
            line=dict(color="#1f77b4", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=fc_by_hour.index,
            y=fc_by_hour.values,
            name="Mean DA forecast",
            yaxis="y",
            line=dict(color="#7fb3e0", width=1.5, dash="dash"),
        )
    )
    fig.update_layout(
        title="DA Commitment Shape — committed dispatch & DA price by hour",
        xaxis=dict(title="Hour of Day", dtick=1),
        yaxis=dict(title="DA Price (£/MWh)", side="left", title_font=dict(color="#1f77b4")),
        yaxis2=dict(
            title="Mean DA Commitment (MW, + discharge / − charge)",
            side="right",
            overlaying="y",
            title_font=dict(color="#555"),
        ),
        legend=dict(x=0, y=1.12, orientation="h"),
        template="plotly_white",
        height=DEFAULT_CHART_HEIGHT,
    )
    return fig


def chart_realized_shape(
    dispatch_df: pd.DataFrame,
    prices_hourly: pd.DataFrame,
    da_sched_df: pd.DataFrame,
):
    """Mean realised physical dispatch and execution prices by hour-of-day.

    The execution layer: what the battery physically did after the rolling
    re-optimisation reshaped the committed schedule. Faint ghost bars are the DA
    commitment, so the gap to the solid bars is the net intraday reshaping — the
    re-optimisation's deviation (``spread_mw``) moving energy across the day. The
    lines are the realised DA price (the proxy the engine *decides* on) and the
    realised MID (where the deviations *settle*).
    """
    d = dispatch_df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    # Physical movement = the realised net dispatch (final_mw): the DA leg as
    # reshaped by the re-optimisation. Falls back to action/mw + spread_mw for
    # older logs that predate the final_mw column.
    if "final_mw" in d:
        d["signed_mw"] = d["final_mw"].fillna(0.0)
    else:
        signed = d["mw"].where(d["action"] == "discharge", -d["mw"])
        signed = signed.where(d["action"] != "idle", 0.0)
        spread = d["spread_mw"].fillna(0.0) if "spread_mw" in d else 0.0
        d["signed_mw"] = signed + spread
    mean_mw = d.groupby(d["timestamp"].dt.hour)["signed_mw"].mean()

    sched = da_sched_df.copy()
    sched["hod"] = pd.to_datetime(sched["timestamp"]).dt.hour
    da_commit = sched.groupby("hod")["da_mw"].mean()

    da_by_hour = prices_hourly.groupby(prices_hourly.index.hour)["day_ahead_price"].mean()
    mid_by_hour = prices_hourly.groupby(prices_hourly.index.hour)["mid_price"].mean()

    colors = ["#e74c3c" if v > 0 else "#2ecc71" for v in mean_mw.values]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=da_commit.index,
            y=da_commit.values,
            name="DA commitment (ghost)",
            yaxis="y2",
            marker_color="#999999",
            opacity=0.25,
        )
    )
    fig.add_trace(
        go.Bar(
            x=mean_mw.index,
            y=mean_mw.values,
            name="Mean realised dispatch MW",
            yaxis="y2",
            marker_color=colors,
            opacity=0.65,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=da_by_hour.index,
            y=da_by_hour.values,
            name="Mean DA price (decision proxy)",
            yaxis="y",
            line=dict(color="#1f77b4", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=mid_by_hour.index,
            y=mid_by_hour.values,
            name="Mean MID price (settlement)",
            yaxis="y",
            line=dict(color="#9467bd", width=2),
        )
    )
    fig.update_layout(
        title="Realised Dispatch Shape — physical dispatch & execution prices by hour",
        xaxis=dict(title="Hour of Day", dtick=1),
        yaxis=dict(title="Price (£/MWh)", side="left"),
        yaxis2=dict(
            title="Mean Dispatch (MW, + discharge / − charge)",
            side="right",
            overlaying="y",
            title_font=dict(color="#555"),
        ),
        barmode="overlay",
        legend=dict(x=0, y=1.12, orientation="h"),
        template="plotly_white",
        height=DEFAULT_CHART_HEIGHT,
    )
    return fig


def chart_soc_tracker(
    dispatch_df: pd.DataFrame,
    min_soc_pct: float = 0.0,
    max_soc_pct: float = 1.0,
    initial_soc_pct: float = 0.50,
):
    dispatch_df = dispatch_df.copy()
    dispatch_df["timestamp"] = pd.to_datetime(dispatch_df["timestamp"])
    soc = dispatch_df.set_index("timestamp")["soc_after"].sort_index()

    min_pct = min_soc_pct * 100
    max_pct = max_soc_pct * 100

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=soc.index,
            y=soc.values * 100,
            mode="lines",
            name="SOC",
            line=dict(color="#1f77b4", width=1),
            fill="tozeroy",
            fillcolor="rgba(31,119,180,0.1)",
        )
    )
    fig.add_hline(
        y=initial_soc_pct * 100,
        line_dash="dash",
        line_color="grey",
        annotation_text=f"Initial SOC ({initial_soc_pct * 100:.0f}%)",
    )
    fig.add_hline(
        y=min_pct,
        line_dash="dot",
        line_color="#e74c3c",
        annotation_text=f"Min SOC ({min_pct:.0f}%)",
        annotation_position="bottom right",
    )
    fig.add_hline(
        y=max_pct,
        line_dash="dot",
        line_color="#e74c3c",
        annotation_text=f"Max SOC ({max_pct:.0f}%)",
        annotation_position="top right",
    )
    fig.update_layout(
        title="State of Charge — Selected Month",
        xaxis_title="Date",
        yaxis_title="SOC (%)",
        yaxis=dict(range=[max(0, min_pct - 10), min(105, max_pct + 10)]),
        template="plotly_white",
        height=350,
    )
    return fig


def chart_operation_explorer(
    prices_hourly: pd.DataFrame,
    dispatch_df: pd.DataFrame,
    da_sched_df: pd.DataFrame,
    min_soc_pct: float = 0.0,
    max_soc_pct: float = 1.0,
):
    """Month-wide operation view with a draggable 24-hour viewport (date rangeslider)."""
    dispatch = dispatch_df.copy()
    dispatch["timestamp"] = pd.to_datetime(dispatch["timestamp"])
    dispatch = dispatch.sort_values("timestamp")

    sched = da_sched_df.copy()
    sched["timestamp"] = pd.to_datetime(sched["timestamp"])
    sched = sched.sort_values("timestamp").set_index("timestamp")
    da_price_pred = sched["da_price_pred"]

    times = dispatch["timestamp"]
    da_price_map = prices_hourly["day_ahead_price"]
    mid_map = prices_hourly["mid_price"]

    # Build the trade tape. The DA leg is the day-ahead commitment, settled on the
    # DA price line; the intraday leg is the re-optimisation's deviation
    # (intraday_mw / spread_mw), which the engine *decides* on the DA proxy but
    # *settles* at the real MID — so its markers sit on the MID line. Buy = ▲,
    # Sell = ▼; DA blue, Intraday green.
    buy_da_x, buy_da_y, sell_da_x, sell_da_y = [], [], [], []
    buy_id_x, buy_id_y, sell_id_x, sell_id_y = [], [], [], []
    for _, row in dispatch.iterrows():
        ts = row["timestamp"]
        da_p = da_price_map.get(ts)
        mid_p = mid_map.get(ts)
        da_v = row["da_mw"]
        # pd.notna guards against a missing price (ts absent from prices_hourly)
        # and a NaN cell. A DA price of 0 is a valid level, not a reason to suppress.
        if pd.notna(da_p):
            if da_v > 1e-6:  # committed to discharge → sold on DA
                sell_da_x.append(ts)
                sell_da_y.append(da_p)
            elif da_v < -1e-6:  # committed to charge → bought on DA
                buy_da_x.append(ts)
                buy_da_y.append(da_p)
        # Re-optimisation deviation from the locked plan, settled at the real MID:
        # + extra discharge sold, − extra charge bought.
        if pd.notna(mid_p):
            dev = row.get("intraday_mw", row.get("spread_mw", 0.0))
            if dev > 1e-6:
                sell_id_x.append(ts)
                sell_id_y.append(mid_p)
            elif dev < -1e-6:
                buy_id_x.append(ts)
                buy_id_y.append(mid_p)

    # Row 1 is a thin strip that only hosts the rangeslider. Its sole trace is
    # day-number text, so the slider band renders dates as its background and,
    # being row 1, the slider sits at the top of the figure.
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.095,
        subplot_titles=(
            "",
            "Market Prices & Trades",
            "Traded Volume — DA vs Intraday",
            "State of Charge",
        ),
        row_heights=[0.02, 0.327, 0.327, 0.326],
    )

    day_marks = pd.date_range(
        times.iloc[0].normalize(), times.iloc[-1].normalize(), freq="D"
    ) + pd.Timedelta(hours=12)
    fig.add_trace(
        go.Scatter(
            x=day_marks,
            y=[0] * len(day_marks),
            mode="text",
            text=[str(t.day) for t in day_marks],
            textfont=dict(size=10, color="#7f8c8d"),
            showlegend=False,
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )
    # Strip y-range excludes the text (y=0) so it only appears inside the
    # rangeslider band, whose miniature autoranges to the data independently.
    fig.update_yaxes(visible=False, fixedrange=True, range=[5, 6], row=1, col=1)

    fig.add_trace(
        go.Scatter(
            x=prices_hourly.index,
            y=prices_hourly["day_ahead_price"].values,
            name="DA Price",
            line=dict(color="#1f77b4", width=2),
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=da_price_pred.index,
            y=da_price_pred.values,
            name="DA Forecast",
            line=dict(color="#7fb3e0", width=1.2, dash="dash"),
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=prices_hourly.index,
            y=prices_hourly["mid_price"].values,
            name="MID Price (settlement)",
            line=dict(color="#27ae60", width=1.6),
        ),
        row=2,
        col=1,
    )

    # DA-leg markers sit on the DA price line; intraday re-opt markers sit on the
    # MID line where they settle. DA blue, Intraday green; ▲ = buy (charge),
    # ▼ = sell (discharge).
    da_mk = dict(color="#1f3b6d", line=dict(width=0.5, color="white"))
    id_mk = dict(color="#1e8449", line=dict(width=0.5, color="white"))
    fig.add_trace(
        go.Scatter(
            x=buy_da_x,
            y=buy_da_y,
            mode="markers",
            name="Buy on DA",
            marker=dict(symbol="triangle-up", size=11, **da_mk),
            hovertemplate="%{x|%d %b %H:%M}<br>Buy (charge) on DA @ £%{y:.1f}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=sell_da_x,
            y=sell_da_y,
            mode="markers",
            name="Sell on DA",
            marker=dict(symbol="triangle-down", size=11, **da_mk),
            hovertemplate="%{x|%d %b %H:%M}<br>Sell (discharge) on DA @ £%{y:.1f}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=buy_id_x,
            y=buy_id_y,
            mode="markers",
            name="Buy on Intraday",
            marker=dict(symbol="triangle-up", size=11, **id_mk),
            hovertemplate="%{x|%d %b %H:%M}<br>Buy-back on Intraday @ £%{y:.1f}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=sell_id_x,
            y=sell_id_y,
            mode="markers",
            name="Sell on Intraday",
            marker=dict(symbol="triangle-down", size=11, **id_mk),
            hovertemplate="%{x|%d %b %H:%M}<br>Sell on Intraday @ £%{y:.1f}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    # How much, signed the same way as the markers (+ sell/discharge, − buy/charge):
    # the blue bar is the locked DA commitment, the green bar is the
    # re-optimisation's deviation from it. Kept as separate stacked traces so a
    # period that trims the DA leg shows both the original commitment and the
    # offsetting intraday adjustment.
    da_vol = dispatch["da_mw"].values
    dev_col = "intraday_mw" if "intraday_mw" in dispatch else "spread_mw"
    dev_vol = dispatch[dev_col].values if dev_col in dispatch else [0.0] * len(dispatch)
    da_y = [v if abs(v) > 1e-6 else None for v in da_vol]
    dev_y = [v if abs(v) > 1e-6 else None for v in dev_vol]

    fig.add_trace(
        go.Bar(
            x=times,
            y=da_y,
            name="DA commitment volume",
            marker_color="#1f77b4",
            hovertemplate="%{x|%d %b %H:%M}<br>DA %{y:+.1f} MW<extra></extra>",
        ),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=times,
            y=dev_y,
            name="Intraday re-opt deviation",
            marker_color="#27ae60",
            hovertemplate="%{x|%d %b %H:%M}<br>Intraday re-opt %{y:+.1f} MW<extra></extra>",
        ),
        row=3,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=times,
            y=dispatch["soc_after"].values * 100,
            name="SOC",
            mode="lines",
            line=dict(color="#34495e", width=2),
            hovertemplate="%{x|%d %b %H:%M}<br>SOC %{y:.1f}%<extra></extra>",
        ),
        row=4,
        col=1,
    )
    fig.add_hline(
        y=min_soc_pct * 100,
        line_dash="dot",
        line_color="#e74c3c",
        annotation_text=f"Min SOC ({min_soc_pct * 100:.0f}%)",
        annotation_position="bottom right",
        row=4,
        col=1,
    )
    fig.add_hline(
        y=max_soc_pct * 100,
        line_dash="dot",
        line_color="#e74c3c",
        annotation_text=f"Max SOC ({max_soc_pct * 100:.0f}%)",
        annotation_position="top right",
        row=4,
        col=1,
    )

    # Open on the first simulated day; drag the date strip at the top to scroll
    window_start = times.iloc[0].normalize()
    window_end = window_start + pd.Timedelta(hours=24)
    fig.update_xaxes(range=[window_start.isoformat(), window_end.isoformat()])
    # rangemode "auto" lets the slider miniature autorange onto the date text,
    # which the strip itself keeps out of view via its [5, 6] y-range
    fig.update_xaxes(
        rangeslider=dict(visible=True, thickness=0.05, yaxis=dict(rangemode="auto")),
        row=1,
        col=1,
    )
    for ann in fig.layout.annotations:
        if ann.text == "Market Prices":
            ann.update(y=ann.y - 0.022)

    fig.update_yaxes(title_text="£/MWh", row=2, col=1)
    fig.update_yaxes(title_text="MW (+ discharge / − charge)", row=3, col=1)
    fig.update_yaxes(title_text="SOC (%)", range=[0, 105], row=4, col=1)
    fig.update_layout(
        template="plotly_white",
        height=850,
        legend=dict(x=0, y=1.05, orientation="h"),
        # "closest" shows only the point under the cursor, so a trade reads once
        # (the marker) instead of unified hover restacking the price line, the
        # marker and the volume bar — which repeated each buy/sell.
        hovermode="closest",
        barmode="relative",
        bargap=0.2,
    )
    return fig


def chart_pnl_waterfall(results_df: pd.DataFrame):
    """Trader's ledger PnL waterfall.

    The frozen day-ahead schedule is the benchmark; the intraday rules are
    consolidated into a single improvement bar on top of it, execution friction
    is isolated into its own deduction, and degradation bridges to the net
    result. The bars sum exactly to Net PnL.
    """
    benchmark = results_df["benchmark_da_revenue"].sum()
    intraday = results_df["intraday_da_improvement"].sum()
    execution = results_df["execution_costs_paid"].sum()
    degradation = results_df["degradation_cost"].sum()

    # (label, signed value, bar colour). DA Benchmark and the intraday improvement
    # carry their own palette identity; the rest are coloured by add or cost.
    components = [
        ("DA Benchmark", benchmark, COLORS["da"]),
        ("Intraday DA Improvement", intraday, COLORS["intraday"]),
        ("Execution Costs", -execution, COLORS["cost"]),
        ("Degradation", -degradation, COLORS["cost"]),
    ]
    net = sum(v for _, v, _ in components)

    # Floating bars: each relative bar starts where the running total sits (for a
    # decrease it hangs down from the prior top), and the final total bar grows
    # from zero.
    bottoms, running = [], 0.0
    for _, v, _ in components:
        bottoms.append(running if v >= 0 else running + v)
        running += v
    bottoms.append(0.0)

    labels = [c[0] for c in components] + ["Net PnL"]
    values = [c[1] for c in components] + [net]
    bar_colors = [c[2] for c in components] + [COLORS["gain"] if net >= 0 else COLORS["cost"]]

    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            base=bottoms,
            marker_color=bar_colors,
            text=[f"£{v:,.0f}" for v in values],
            textposition="outside",
            hovertemplate="%{x}<br>£%{y:,.0f}<extra></extra>",
        )
    )

    # Connectors joining each bar's running top to the next bar.
    running = 0.0
    for i, (_, v, _) in enumerate(components):
        top = running + v if v >= 0 else running
        fig.add_shape(
            type="line",
            x0=i + 0.3,
            x1=i + 0.7,
            y0=top,
            y1=top,
            line=dict(color="#999999", width=0.8),
        )
        running += v

    fig.update_layout(
        title="PnL Waterfall — Trader's Ledger",
        yaxis_title="£",
        template="plotly_white",
        height=450,
        showlegend=False,
    )
    return fig


def chart_daily_attribution(results_df: pd.DataFrame):
    """Daily PnL attribution across the selected month.

    The waterfall shows *what* made the money over the whole month; this shows
    *when*. Each day stacks its positive returns above zero (DA benchmark, the
    intraday improvement, positive imbalance) and its costs below (execution
    friction, degradation, negative imbalance) via barmode='relative', so you can
    see at a glance whether the month earned steadily or on a handful of volatile
    days. The black line is each day's net PnL, which the stacked buckets sum to.
    """
    df = results_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    x = df["date"]

    components = [
        ("DA Benchmark", df["benchmark_da_revenue"], COLORS["da"]),
        ("Intraday DA Improvement", df["intraday_da_improvement"], COLORS["intraday"]),
        ("Execution Costs", -df["execution_costs_paid"], "#7f8c8d"),
        ("Degradation", -df["degradation_cost"], "#c0392b"),
    ]

    fig = go.Figure()
    for name, y, color in components:
        fig.add_trace(
            go.Bar(
                x=x,
                y=y,
                name=name,
                marker_color=color,
                hovertemplate="%{x|%d %b}<br>" + name + " £%{y:,.0f}<extra></extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=df["net_pnl"],
            name="Net PnL",
            mode="lines+markers",
            line=dict(color="#2c3e50", width=2),
            marker=dict(size=5),
            hovertemplate="%{x|%d %b}<br>Net £%{y:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Daily PnL Attribution — selected month",
        xaxis_title="Date",
        yaxis_title="PnL (£)",
        barmode="relative",
        bargap=0.15,
        template="plotly_white",
        height=380,
        legend=dict(orientation="h", x=0, y=1.12),
        hovermode="x unified",
    )
    return fig


# ---------------------------------------------------------------------------
# Live GB BESS benchmark builders
#
# The four functions below back the live-benchmark figure-export CLI and the
# static site's data pipeline. They take plain DataFrames/dicts (no dependency
# on this project's later modules) so they stay generic and reusable, and they
# reuse the shared COLORS palette to stay on-brand with the rest of the file.
# ---------------------------------------------------------------------------

# Ordered fallback palette for the per-series builders below, drawn from the
# shared COLORS values so a new category gets an on-brand colour.
_SERIES_PALETTE = [COLORS["da"], COLORS["intraday"], COLORS["cost"], COLORS["net"]]


def _palette_for(labels: list[str]) -> dict[str, str]:
    """Assign a stable colour to each label, cycling the shared palette."""
    return {label: _SERIES_PALETTE[i % len(_SERIES_PALETTE)] for i, label in enumerate(labels)}


def chart_duration_comparison(
    df: pd.DataFrame,
    duration_col: str = "duration",
    value_col: str = "net_pnl",
    title: str = "Duration Comparison",
    value_label: str = "Net PnL (£)",
) -> go.Figure:
    """Compare the 1h/2h/4h reference assets on a single metric.

    ``df`` carries one row per duration with a duration label (``duration_col``)
    and the metric to compare (``value_col``, e.g. net PnL or cycles). Each
    duration gets its own on-brand colour so the bars read consistently across
    the benchmark figures.
    """
    d = df.copy()
    durations = [str(v) for v in d[duration_col]]
    palette = _palette_for(durations)

    fig = go.Figure(
        go.Bar(
            x=durations,
            y=d[value_col].values,
            marker_color=[palette[v] for v in durations],
            text=[f"{v:,.0f}" for v in d[value_col].values],
            textposition="outside",
            hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Duration",
        yaxis_title=value_label,
        template="plotly_white",
        height=DEFAULT_CHART_HEIGHT,
        showlegend=False,
    )
    return fig


def chart_daytype_scatter(
    df: pd.DataFrame,
    spread_col: str = "da_spread",
    pnl_col: str = "net_pnl",
    daytype_col: str = "day_type",
) -> go.Figure:
    """Scatter of day-ahead price spread (x) vs net PnL (y), by day-type.

    Each day-type label (e.g. windy / sunny / calm) gets its own colour and
    legend entry, so the relationship between the day-ahead spread the battery
    had to work with and the PnL it earned is visible per regime.
    """
    d = df.copy()
    labels = [str(v) for v in d[daytype_col].unique()]
    palette = _palette_for(labels)

    fig = go.Figure()
    for label in labels:
        sub = d[d[daytype_col].astype(str) == label]
        fig.add_trace(
            go.Scatter(
                x=sub[spread_col].values,
                y=sub[pnl_col].values,
                mode="markers",
                name=label,
                marker=dict(color=palette[label], size=8, line=dict(width=0.5, color="white")),
                hovertemplate=(
                    label + "<br>Spread £%{x:,.1f}<br>Net PnL £%{y:,.0f}<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        title="Day-Ahead Spread vs Net PnL by Day-Type",
        xaxis_title="DA Price Spread (£/MWh)",
        yaxis_title="Net PnL (£)",
        template="plotly_white",
        height=DEFAULT_CHART_HEIGHT,
        legend=dict(orientation="h", x=0, y=1.12),
        hovermode="closest",
    )
    return fig


def chart_equity_curve(
    df: pd.DataFrame,
    date_col: str = "date",
    pnl_col: str = "net_pnl",
    duration_col: str = "duration",
) -> go.Figure:
    """Cumulative PnL per duration over time, one line per duration.

    ``df`` holds one row per (duration, date) with that day's PnL. The daily
    PnL is accumulated within each duration, so the lines show how the 1h/2h/4h
    assets compound their returns across the benchmark window.
    """
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col])
    d = d.sort_values(date_col)

    durations = [str(v) for v in d[duration_col].unique()]
    palette = _palette_for(durations)

    fig = go.Figure()
    for label in durations:
        sub = d[d[duration_col].astype(str) == label]
        cum = sub[pnl_col].cumsum()
        fig.add_trace(
            go.Scatter(
                x=sub[date_col].values,
                y=cum.values,
                mode="lines",
                name=label,
                line=dict(color=palette[label], width=2),
                hovertemplate=(label + "<br>%{x|%d %b}<br>Cumulative £%{y:,.0f}<extra></extra>"),
            )
        )
    fig.update_layout(
        title="Equity Curve — Cumulative PnL by Duration",
        xaxis_title="Date",
        yaxis_title="Cumulative PnL (£)",
        template="plotly_white",
        height=DEFAULT_CHART_HEIGHT,
        legend=dict(orientation="h", x=0, y=1.12),
        hovermode="x unified",
    )
    return fig


def chart_daytype_profiles(
    df: pd.DataFrame,
    hour_col: str = "hour",
    value_col: str = "soc",
    daytype_col: str = "day_type",
    value_label: str = "Mean SOC (%)",
) -> go.Figure:
    """Mean dispatch/SOC shape by hour-of-day, one line per day-type.

    Averages ``value_col`` (e.g. dispatch MW or SOC) over every day of each
    day-type label, so the typical windy vs sunny vs calm profile across the
    day can be compared side by side.
    """
    d = df.copy()
    profiles = d.groupby([daytype_col, hour_col])[value_col].mean().reset_index()

    labels = [str(v) for v in profiles[daytype_col].unique()]
    palette = _palette_for(labels)

    fig = go.Figure()
    for label in labels:
        sub = profiles[profiles[daytype_col].astype(str) == label].sort_values(hour_col)
        fig.add_trace(
            go.Scatter(
                x=sub[hour_col].values,
                y=sub[value_col].values,
                mode="lines+markers",
                name=label,
                line=dict(color=palette[label], width=2),
                marker=dict(size=5),
                hovertemplate=label + "<br>Hour %{x}<br>%{y:,.2f}<extra></extra>",
            )
        )
    fig.update_layout(
        title="Mean Profile by Day-Type",
        xaxis=dict(title="Hour of Day", dtick=2),
        yaxis_title=value_label,
        template="plotly_white",
        height=DEFAULT_CHART_HEIGHT,
        legend=dict(orientation="h", x=0, y=1.12),
        hovermode="x unified",
    )
    return fig
