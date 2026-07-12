"""Plotly chart builders for the BESS dispatch dashboard (dashboard/app.py).

Each function takes already-sliced simulation frames and returns a Plotly
figure; they hold no Streamlit or data-loading logic so they can be reused and
tested in isolation.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --------------------------------------------------------------------------- #
# Design system
#
# One semantic palette shared by every builder, CVD-validated on the light
# surface the app renders on. A colour always means the same market object:
# blue = day-ahead, amber = MID/intraday settlement price, teal = discharge /
# sell / gain, orange = charge / buy, violet = state of charge, red = cost.
# --------------------------------------------------------------------------- #
COLORS = {
    "da": "#2a78d6",  # day-ahead price & DA-leg volume
    "forecast": "#86b6ef",  # DA forecast (lighter step of the DA blue)
    "mid": "#c98500",  # MID / intraday settlement price
    "discharge": "#1baf7a",  # sell / +MW
    "charge": "#eb6834",  # buy / −MW
    "soc": "#4a3aa7",  # state of charge
    "intraday": "#1baf7a",  # intraday improvement leg (same teal as discharge)
    "gain": "#1baf7a",
    "cost": "#e34948",
    "net": "#0b0b0b",  # net/total line rides in primary ink
    "ghost": "#c3c2b7",  # reference/ghost bars
}

# Fixed-order categorical slots for label-keyed series (day-types etc.).
# Assigned in order, never cycled; overflow folds into muted grey.
CATEGORICAL = [
    "#2a78d6",
    "#1baf7a",
    "#eda100",
    "#008300",
    "#4a3aa7",
    "#e34948",
    "#e87ba4",
    "#eb6834",
]
_OVERFLOW = "#898781"

# Chart chrome (light surface).
_INK = "#0b0b0b"
_INK_2 = "#52514e"
_MUTED = "#898781"
_GRID = "#e1e0d9"
_AXIS = "#c3c2b7"
_FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Height scale (px): compact panels, the standard single-panel builder, and
# tall multi-panel views.
HEIGHT_SM = 320
DEFAULT_CHART_HEIGHT = 380
HEIGHT_LG = 460


def apply_theme(fig: go.Figure, height: int = DEFAULT_CHART_HEIGHT, title: str | None = None):
    """Stamp the shared look onto a figure: transparent surfaces so charts sit
    on the app background, hairline grid, muted axis ink, a left-aligned title
    and a horizontal legend directly under it."""
    fig.update_layout(
        template="plotly_white",
        height=height,
        font=dict(family=_FONT, size=12, color=_INK_2),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=64 if title else 40, b=10),
        legend=dict(
            orientation="h",
            x=0,
            xanchor="left",
            y=1.0,
            yanchor="bottom",
            font=dict(size=11, color=_INK_2),
        ),
        hoverlabel=dict(
            bgcolor="#ffffff", bordercolor=_GRID, font=dict(family=_FONT, size=12, color=_INK)
        ),
    )
    if title:
        fig.update_layout(
            title=dict(
                text=title,
                x=0,
                xanchor="left",
                y=1.0,
                yanchor="top",
                pad=dict(t=8),
                font=dict(size=15, color=_INK),
            )
        )
    fig.update_xaxes(
        gridcolor=_GRID,
        linecolor=_AXIS,
        zerolinecolor=_AXIS,
        title_font=dict(size=12, color=_MUTED),
        tickfont=dict(size=11, color=_MUTED),
    )
    fig.update_yaxes(
        gridcolor=_GRID,
        linecolor=_AXIS,
        zerolinecolor=_AXIS,
        title_font=dict(size=12, color=_MUTED),
        tickfont=dict(size=11, color=_MUTED),
    )
    return fig


def _dispatch_bar_colors(values) -> list[str]:
    """+MW discharges (teal), −MW charges (orange)."""
    return [COLORS["discharge"] if v > 0 else COLORS["charge"] for v in values]


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

    # Price panel above, committed volume below, sharing the hour axis — no
    # dual y-axis; the two measures live on their own scales.
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.55, 0.45]
    )
    fig.add_trace(
        go.Scatter(
            x=da_by_hour.index,
            y=da_by_hour.values,
            name="DA price (actual)",
            line=dict(color=COLORS["da"], width=2),
            hovertemplate="%{x:02d}:00<br>DA actual £%{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=fc_by_hour.index,
            y=fc_by_hour.values,
            name="DA forecast",
            line=dict(color=COLORS["forecast"], width=2, dash="dash"),
            hovertemplate="%{x:02d}:00<br>DA forecast £%{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=mean_mw.index,
            y=mean_mw.values,
            name="DA commitment (+ discharge / − charge)",
            marker_color=_dispatch_bar_colors(mean_mw.values),
            hovertemplate="%{x:02d}:00<br>Committed %{y:+.1f} MW<extra></extra>",
        ),
        row=2,
        col=1,
    )
    apply_theme(fig, height=HEIGHT_LG, title="Day-ahead commitment — price and dispatch by hour")
    fig.update_xaxes(dtick=2)
    fig.update_xaxes(title_text="Hour of day", row=2, col=1)
    fig.update_yaxes(title_text="£/MWh", row=1, col=1)
    fig.update_yaxes(title_text="MW", row=2, col=1)
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

    # Prices on top, dispatch below (shared hour axis, no dual y-axis). The
    # ghost bars are the DA commitment; the gap to the solid bars is the net
    # intraday reshaping.
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.5, 0.5]
    )
    fig.add_trace(
        go.Scatter(
            x=da_by_hour.index,
            y=da_by_hour.values,
            name="DA price (decision proxy)",
            line=dict(color=COLORS["da"], width=2),
            hovertemplate="%{x:02d}:00<br>DA £%{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=mid_by_hour.index,
            y=mid_by_hour.values,
            name="MID price (settlement)",
            line=dict(color=COLORS["mid"], width=2),
            hovertemplate="%{x:02d}:00<br>MID £%{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=da_commit.index,
            y=da_commit.values,
            name="DA commitment (ghost)",
            marker_color=COLORS["ghost"],
            opacity=0.55,
            hovertemplate="%{x:02d}:00<br>DA commitment %{y:+.1f} MW<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=mean_mw.index,
            y=mean_mw.values,
            name="Realised dispatch (+ discharge / − charge)",
            marker_color=_dispatch_bar_colors(mean_mw.values),
            hovertemplate="%{x:02d}:00<br>Realised %{y:+.1f} MW<extra></extra>",
        ),
        row=2,
        col=1,
    )
    apply_theme(fig, height=HEIGHT_LG, title="Realised dispatch — execution prices and physical dispatch by hour")
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(dtick=2)
    fig.update_xaxes(title_text="Hour of day", row=2, col=1)
    fig.update_yaxes(title_text="£/MWh", row=1, col=1)
    fig.update_yaxes(title_text="MW", row=2, col=1)
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
            line=dict(color=COLORS["soc"], width=2),
            fill="tozeroy",
            fillcolor="rgba(74,58,167,0.08)",
            hovertemplate="%{x|%d %b %H:%M}<br>SOC %{y:.1f}%<extra></extra>",
        )
    )
    fig.add_hline(
        y=initial_soc_pct * 100,
        line_dash="dash",
        line_color=_MUTED,
        annotation_text=f"Start ({initial_soc_pct * 100:.0f}%)",
    )
    fig.add_hline(
        y=min_pct,
        line_dash="dot",
        line_color=COLORS["cost"],
        annotation_text=f"Min ({min_pct:.0f}%)",
        annotation_position="bottom right",
    )
    fig.add_hline(
        y=max_pct,
        line_dash="dot",
        line_color=COLORS["cost"],
        annotation_text=f"Max ({max_pct:.0f}%)",
        annotation_position="top right",
    )
    apply_theme(fig, height=HEIGHT_SM, title="State of charge")
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title_text="SOC (%)", range=[max(0, min_pct - 10), min(105, max_pct + 10)])
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
            name="DA price",
            line=dict(color=COLORS["da"], width=2),
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=da_price_pred.index,
            y=da_price_pred.values,
            name="DA forecast",
            line=dict(color=COLORS["forecast"], width=1.5, dash="dash"),
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=prices_hourly.index,
            y=prices_hourly["mid_price"].values,
            name="MID price (settlement)",
            line=dict(color=COLORS["mid"], width=2),
        ),
        row=2,
        col=1,
    )

    # DA-leg markers sit on the DA price line; intraday re-opt markers sit on the
    # MID line where they settle. DA in a darker DA blue, intraday in a darker
    # teal; ▲ = buy (charge), ▼ = sell (discharge).
    da_mk = dict(color="#1c5cab", line=dict(width=1, color="white"))
    id_mk = dict(color="#0f7f57", line=dict(width=1, color="white"))
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
            marker_color=COLORS["da"],
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
            marker_color=COLORS["intraday"],
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
            line=dict(color=COLORS["soc"], width=2),
            hovertemplate="%{x|%d %b %H:%M}<br>SOC %{y:.1f}%<extra></extra>",
        ),
        row=4,
        col=1,
    )
    fig.add_hline(
        y=min_soc_pct * 100,
        line_dash="dot",
        line_color=COLORS["cost"],
        annotation_text=f"Min SOC ({min_soc_pct * 100:.0f}%)",
        annotation_position="bottom right",
        row=4,
        col=1,
    )
    fig.add_hline(
        y=max_soc_pct * 100,
        line_dash="dot",
        line_color=COLORS["cost"],
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

    apply_theme(fig, height=780)
    fig.update_yaxes(title_text="£/MWh", row=2, col=1)
    fig.update_yaxes(title_text="MW (+ discharge / − charge)", row=3, col=1)
    fig.update_yaxes(title_text="SOC (%)", range=[0, 105], row=4, col=1)
    # Restore the strip row's hidden axis, which the theme pass re-styled.
    fig.update_yaxes(visible=False, fixedrange=True, range=[5, 6], row=1, col=1)
    for ann in fig.layout.annotations:
        ann.update(font=dict(size=13, color=_INK))
    fig.update_layout(
        # Ten legend entries wrap to two rows; give them their own headroom.
        margin=dict(t=96),
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
            textfont=dict(size=12, color=_INK),
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
            line=dict(color=_AXIS, width=1),
        )
        running += v

    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title="PnL bridge — where the money came from")
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title_text="£")
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
        ("DA benchmark", df["benchmark_da_revenue"], COLORS["da"]),
        ("Intraday improvement", df["intraday_da_improvement"], COLORS["intraday"]),
        ("Execution costs", -df["execution_costs_paid"], COLORS["ghost"]),
        ("Degradation", -df["degradation_cost"], COLORS["cost"]),
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
            line=dict(color=COLORS["net"], width=2),
            marker=dict(size=5),
            hovertemplate="%{x|%d %b}<br>Net £%{y:,.0f}<extra></extra>",
        )
    )
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title="Daily PnL attribution")
    fig.update_layout(barmode="relative", bargap=0.15, hovermode="x unified")
    fig.update_yaxes(title_text="PnL (£)")
    return fig


# ---------------------------------------------------------------------------
# Live GB BESS benchmark builders
#
# The four functions below back the live-benchmark figure-export CLI and the
# static site's data pipeline. They take plain DataFrames/dicts (no dependency
# on this project's later modules) so they stay generic and reusable, and they
# reuse the shared COLORS palette to stay on-brand with the rest of the file.
# ---------------------------------------------------------------------------

def _palette_for(labels: list[str]) -> dict[str, str]:
    """Assign the fixed-order categorical slots to each label. Slots are never
    cycled — labels beyond the eighth fold into the muted overflow grey."""
    return {
        label: CATEGORICAL[i] if i < len(CATEGORICAL) else _OVERFLOW
        for i, label in enumerate(labels)
    }


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
            textfont=dict(size=12, color=_INK),
            hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>",
        )
    )
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title=title)
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title_text="Duration")
    fig.update_yaxes(title_text=value_label)
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
                marker=dict(color=palette[label], size=9, line=dict(width=1, color="white")),
                hovertemplate=(
                    label + "<br>Spread £%{x:,.1f}<br>Net PnL £%{y:,.0f}<extra></extra>"
                ),
            )
        )
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title="Day-ahead spread vs net PnL by day-type")
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title_text="DA price spread (£/MWh)")
    fig.update_yaxes(title_text="Net PnL (£)")
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
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title="Equity curve — cumulative PnL by duration")
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="Cumulative PnL (£)")
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
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title="Mean daily profile by day-type")
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(title_text="Hour of day", dtick=2)
    fig.update_yaxes(title_text=value_label)
    return fig


def chart_price_capture(
    dispatch_df: pd.DataFrame,
    duration_h: float = 1.0,
    mw_col: str = "final_mw",
    price_col: str = "da_price",
    hour_col: str = "hour",
):
    """Charge/discharge energy by hour of day against the average DA price.

    A well-optimised battery discharges into high-price hours and charges in
    low-price hours; the gap between the volume-weighted discharge price and the
    volume-weighted charge price is the **achieved price spread** — the headline
    driver of day-ahead revenue, surfaced in the title.

    ``dispatch_df`` is a per-period frame with an hour-of-day column, a signed
    dispatch column (``+`` discharge / ``−`` charge MW) and the DA price each
    period settled at. Energy is ``MW × duration_h``; bars are summed over every
    period in the frame, so the chart works for a single day or a whole range.
    """
    df = dispatch_df[[hour_col, mw_col, price_col]].dropna()
    hours = list(range(24))

    discharge = df[df[mw_col] > 0]
    charge = df[df[mw_col] < 0]
    dis_mwh = (discharge[mw_col] * duration_h).groupby(discharge[hour_col]).sum()
    chg_mwh = (-charge[mw_col] * duration_h).groupby(charge[hour_col]).sum()
    avg_da = df.groupby(hour_col)[price_col].mean()

    dis_e = discharge[mw_col] * duration_h
    chg_e = -charge[mw_col] * duration_h
    w_dis = (discharge[price_col] * dis_e).sum() / dis_e.sum() if dis_e.sum() > 0 else 0.0
    w_chg = (charge[price_col] * chg_e).sum() / chg_e.sum() if chg_e.sum() > 0 else 0.0
    spread = w_dis - w_chg

    # Price on top, energy below on a shared hour axis — no dual y-axis.
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.4, 0.6]
    )
    fig.add_trace(
        go.Scatter(
            x=hours,
            y=[float(avg_da.get(h)) if h in avg_da.index else None for h in hours],
            name="Avg DA price",
            mode="lines",
            line=dict(color=COLORS["da"], width=2),
            hovertemplate="%{x:02d}:00<br>Avg DA £%{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=hours,
            y=[float(dis_mwh.get(h, 0.0)) for h in hours],
            name="Discharge (sell)",
            marker_color=COLORS["discharge"],
            hovertemplate="%{x:02d}:00<br>Discharge %{y:,.1f} MWh<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=hours,
            y=[float(chg_mwh.get(h, 0.0)) for h in hours],
            name="Charge (buy)",
            marker_color=COLORS["charge"],
            hovertemplate="%{x:02d}:00<br>Charge %{y:,.1f} MWh<extra></extra>",
        ),
        row=2,
        col=1,
    )
    apply_theme(
        fig,
        height=HEIGHT_LG,
        title=f"Price capture — achieved spread £{spread:,.2f}/MWh",
    )
    fig.update_layout(barmode="group")
    fig.update_xaxes(dtick=2)
    fig.update_xaxes(title_text="Hour of day", row=2, col=1)
    fig.update_yaxes(title_text="£/MWh", row=1, col=1)
    fig.update_yaxes(title_text="Energy (MWh)", row=2, col=1)
    return fig


# --------------------------------------------------------------------------- #
# Live GB fleet tab (real batteries, per-BMU Elexon data)
# --------------------------------------------------------------------------- #
def chart_fleet_leaderboard(site_df: pd.DataFrame):
    """Ranked horizontal leaderboard of real GB battery sites by est. £/MW/day.

    ``site_df`` is the per-site summary frame from
    :func:`fleet.performance.summarise_by_site`. Bars encode one magnitude, so
    they share a single hue and flip to the cost red only when a site's window
    average is negative; the optimiser is carried in the y-label, not a hue.
    """
    df = site_df.sort_values("gbp_per_mw_day")
    labels = [f"{s}  ·  {o}" for s, o in zip(df["site"], df["optimiser"])]
    colors = [COLORS["cost"] if v < 0 else COLORS["da"] for v in df["gbp_per_mw_day"]]

    fig = go.Figure(
        go.Bar(
            x=df["gbp_per_mw_day"],
            y=labels,
            orientation="h",
            marker_color=colors,
            text=[f"£{v:,.0f}" for v in df["gbp_per_mw_day"]],
            textposition="outside",
            textfont=dict(size=11, color=_INK),
            customdata=df[["power_mw", "days", "total_gbp"]].values,
            hovertemplate=(
                "%{y}<br>£%{x:,.0f}/MW/day"
                "<br>%{customdata[0]:,.0f} MW · %{customdata[1]:.0f} days"
                "<br>Total £%{customdata[2]:,.0f}<extra></extra>"
            ),
        )
    )
    apply_theme(
        fig,
        height=max(DEFAULT_CHART_HEIGHT, 26 * len(df) + 120),
        title="Site leaderboard — estimated £/MW/day",
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title_text="Estimated revenue (£/MW/day)")
    return fig


def _chart_fleet_grouped(df: pd.DataFrame, key: str, title: str):
    """Shared magnitude bar for the optimiser/region groupings."""
    df = df.sort_values("gbp_per_mw_day", ascending=False)
    colors = [COLORS["cost"] if v < 0 else COLORS["da"] for v in df["gbp_per_mw_day"]]
    fig = go.Figure(
        go.Bar(
            x=df[key],
            y=df["gbp_per_mw_day"],
            marker_color=colors,
            text=[f"£{v:,.0f}" for v in df["gbp_per_mw_day"]],
            textposition="outside",
            textfont=dict(size=11, color=_INK),
            customdata=df[["sites", "power_mw", "total_gbp"]].values,
            hovertemplate=(
                "%{x}<br>£%{y:,.0f}/MW/day"
                "<br>%{customdata[0]:.0f} site(s) · %{customdata[1]:,.0f} MW"
                "<br>Total £%{customdata[2]:,.0f}<extra></extra>"
            ),
        )
    )
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title=title)
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title_text="Estimated revenue (£/MW/day)")
    return fig


def chart_fleet_by_optimiser(opt_df: pd.DataFrame):
    """MW-weighted est. £/MW/day by optimiser (route-to-market party).

    ``opt_df`` comes from :func:`fleet.performance.summarise_by_optimiser`;
    every site-day is weighted by its MW, so a 500 MW site moves its
    optimiser's average more than a 50 MW one.
    """
    return _chart_fleet_grouped(
        opt_df, "optimiser", "By optimiser — MW-weighted estimated £/MW/day"
    )


def chart_fleet_by_region(region_df: pd.DataFrame):
    """MW-weighted est. £/MW/day by region — the locational split."""
    return _chart_fleet_grouped(
        region_df, "region", "By region — MW-weighted estimated £/MW/day"
    )


def chart_fleet_daily(daily_df: pd.DataFrame):
    """Whole-fleet estimated revenue per day, stacked wholesale proxy vs BM.

    ``daily_df`` is :func:`fleet.performance.fleet_daily`. The two components
    can take opposite signs (e.g. paying to charge in the BM while long in the
    wholesale proxy), so bars use plotly's signed stacking (``barmode
    "relative"``) with a net-total line over the top.
    """
    dates = pd.to_datetime(daily_df["date"])
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=dates,
            y=daily_df["wholesale_gbp"],
            name="Wholesale proxy (PN × MID)",
            marker_color=COLORS["da"],
            hovertemplate="%{x|%Y-%m-%d}<br>Wholesale £%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=dates,
            y=daily_df["bm_gbp"],
            name="Balancing Mechanism",
            marker_color=COLORS["intraday"],
            hovertemplate="%{x|%Y-%m-%d}<br>BM £%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=daily_df["total_gbp"],
            name="Net total",
            mode="lines",
            line=dict(color=COLORS["net"], width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>Net £%{y:,.0f}<extra></extra>",
        )
    )
    apply_theme(
        fig,
        height=DEFAULT_CHART_HEIGHT,
        title="Fleet estimated revenue by day — wholesale proxy vs Balancing Mechanism",
    )
    fig.update_layout(barmode="relative", hovermode="x unified")
    fig.update_yaxes(title_text="Estimated revenue (£/day)")
    return fig
