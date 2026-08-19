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
    "bm": "#008300",  # Balancing Mechanism — its own green; violet stays SOC-only
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

# Days the operation explorer opens on. Its rangeslider still spans everything
# selected; this is only the starting viewport.
EXPLORER_VIEW_DAYS = 5


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
    re-optimisation reshaped the committed schedule. Faint reference bars are the locked DA
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

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=da_commit.index,
            y=da_commit.values,
            name="Mean DA commitment MW",
            yaxis="y2",
            marker_color=COLORS["ghost"],
            opacity=0.45,
        )
    )
    fig.add_trace(
        go.Bar(
            x=mean_mw.index,
            y=mean_mw.values,
            name="Mean realised dispatch MW",
            yaxis="y2",
            marker_color=_dispatch_bar_colors(mean_mw.values),
            opacity=0.65,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=da_by_hour.index,
            y=da_by_hour.values,
            name="Mean DA price (decision proxy)",
            yaxis="y",
            line=dict(color=COLORS["da"], width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=mid_by_hour.index,
            y=mid_by_hour.values,
            name="Mean MID price (settlement)",
            yaxis="y",
            line=dict(color=COLORS["mid"], width=2),
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
        height=400,
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
            line=dict(color=COLORS["soc"], width=1),
            fill="tozeroy",
            fillcolor="rgba(74,58,167,0.1)",
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
        line_color=COLORS["cost"],
        annotation_text=f"Min SOC ({min_pct:.0f}%)",
        annotation_position="bottom right",
    )
    fig.add_hline(
        y=max_pct,
        line_dash="dot",
        line_color=COLORS["cost"],
        annotation_text=f"Max SOC ({max_pct:.0f}%)",
        annotation_position="top right",
    )
    fig.update_layout(
        title="State of Charge",
        xaxis_title="Date",
        yaxis_title="SOC (%)",
        yaxis=dict(range=[max(0, min_pct - 10), min(105, max_pct + 10)]),
        template="plotly_white",
        height=350,
    )
    return fig


def chart_capture_spread_daily(df: pd.DataFrame, degradation_cost: float = 0.0) -> go.Figure:
    """The benchmark's gross margin per MWh discharged, day by day.

    ``df`` columns: ``date`` and ``capture_spread`` (£/MWh). The same measure
    the fleet page reports, so the simulated battery and the real ones can be
    compared on margin rather than only on £/MW/day. ``degradation_cost``
    draws the wear line the lever is set to: days below it earned less per MWh
    than the cycling cost, which is the point at which trading destroys value.
    """
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    values = pd.to_numeric(d["capture_spread"], errors="coerce")
    fig = go.Figure(
        go.Scatter(
            x=d["date"], y=values, mode="lines",
            name="Capture spread",
            line=dict(color=COLORS["da"], width=2),
            hovertemplate="Capture £%{y:,.1f}/MWh<extra></extra>",
        )
    )
    mean = float(values.mean()) if values.notna().any() else 0.0
    fig.add_hline(
        y=mean, line=dict(color=_MUTED, width=1, dash="dash"),
        annotation_text=f"window mean £{mean:,.1f}",
        annotation_position="top left",
        annotation_font=dict(size=11, color=_MUTED),
    )
    if degradation_cost > 0:
        fig.add_hline(
            y=degradation_cost, line=dict(color=COLORS["cost"], width=1, dash="dot"),
            annotation_text=f"degradation £{degradation_cost:,.1f}/MWh",
            annotation_position="bottom left",
            annotation_font=dict(size=11, color=COLORS["cost"]),
        )
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT,
                title="Capture spread by day — margin on every MWh discharged")
    fig.update_layout(hovermode="x unified", showlegend=False)
    fig.update_yaxes(title_text="Capture spread (£/MWh)")
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

    # Open on the first EXPLORER_VIEW_DAYS days; drag the date strip at the top
    # to scroll. A single day was too tight to read a pattern out of — the
    # slider exists to pan, not to be the only way to see more than one day.
    window_start = times.iloc[0].normalize()
    window_end = min(
        window_start + pd.Timedelta(days=EXPLORER_VIEW_DAYS), times.iloc[-1]
    )
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
                hovertemplate="" + name + " £%{y:,.0f}<extra></extra>",
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
            hovertemplate="Net £%{y:,.0f}<extra></extra>",
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


# The two day-type families share one colour each across every day-type chart:
# what caused the day (driver) vs how prices behaved (price character).
FAMILY_COLORS = {"driver": COLORS["da"], "price": COLORS["mid"]}
FAMILY_NAMES = {"driver": "Driver (weather / demand)", "price": "Price character"}


def _daytype_order(df: pd.DataFrame, value_col: str) -> list[str]:
    """Tags ordered drivers-then-price, each family by descending median value,
    so the capture and frequency charts line up row for row."""
    order: list[str] = []
    for family in ("driver", "price"):
        sub = df[df["family"] == family]
        medians = sub.groupby("tag")[value_col].median().sort_values()
        order.extend(medians.index.tolist())
    return order


def chart_daytype_capture(df: pd.DataFrame) -> go.Figure:
    """Capture-rate distribution per day-type tag — the skill view.

    ``df`` has one row per (day, tag) membership with columns ``tag``,
    ``family`` (``driver``/``price``) and ``capture`` (realised net PnL over
    the perfect-foresight DA ceiling). Because capture normalises away how big
    the opportunity was, differences between tags read as strategy fit, not as
    'volatile days pay more'.
    """
    order = _daytype_order(df, "capture")
    fig = go.Figure()
    seen: set[str] = set()
    for tag in order:
        sub = df[df["tag"] == tag]
        family = str(sub["family"].iloc[0])
        fig.add_trace(
            go.Box(
                x=sub["capture"].values,
                y=[tag] * len(sub),
                orientation="h",
                name=FAMILY_NAMES[family],
                legendgroup=family,
                showlegend=family not in seen,
                marker=dict(color=FAMILY_COLORS[family], size=6),
                line=dict(color=FAMILY_COLORS[family], width=2),
                boxpoints="all",
                jitter=0.4,
                pointpos=0,
                hovertemplate=tag + "<br>Capture %{x:.0%}<extra></extra>",
            )
        )
        seen.add(family)
    apply_theme(
        fig,
        height=max(DEFAULT_CHART_HEIGHT, 34 * len(order) + 120),
        title="Capture rate by day-type — share of the perfect-foresight ceiling",
    )
    fig.update_xaxes(title_text="Capture rate", tickformat=".0%")
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    return fig


def chart_daytype_frequency(df: pd.DataFrame) -> go.Figure:
    """How many days carried each tag in the window, drivers vs price tags.

    Same row order as :func:`chart_daytype_capture` so the two read together —
    a tag with a striking capture number but two days of support shouldn't be
    over-read.
    """
    counts = (
        df.groupby(["tag", "family"], as_index=False)
        .agg(days=("date", "nunique"))
    )
    order = [t for t in _daytype_order(df, "capture") if t in set(counts["tag"])]
    counts = counts.set_index("tag").loc[order].reset_index()
    fig = go.Figure(
        go.Bar(
            x=counts["days"],
            y=counts["tag"],
            orientation="h",
            marker_color=[FAMILY_COLORS[f] for f in counts["family"]],
            text=counts["days"],
            textposition="outside",
            textfont=dict(size=11, color=_INK),
            hovertemplate="%{y}<br>%{x} day(s)<extra></extra>",
        )
    )
    apply_theme(
        fig,
        height=max(HEIGHT_SM, 30 * len(counts) + 110),
        title="Days per type in the window",
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title_text="Days tagged")
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    return fig


def chart_daytype_matrix(matrix: pd.DataFrame) -> go.Figure:
    """Driver × price-character day counts — do windy days turn volatile?

    ``matrix`` is a frame indexed by driver tag with price-character tags as
    columns and day counts as values (a day holding several tags counts in
    every combination it belongs to). Counts are annotated on the cells, so
    the sequential ramp only has to carry magnitude, not exact values.
    """
    fig = go.Figure(
        go.Heatmap(
            z=matrix.values,
            x=list(matrix.columns),
            y=list(matrix.index),
            colorscale=[[0.0, "#fcfcfb"], [1.0, COLORS["da"]]],
            zmin=0,
            texttemplate="%{z}",
            textfont=dict(size=12, color=_INK),
            xgap=2,
            ygap=2,
            showscale=False,
            hovertemplate="%{y} × %{x}<br>%{z} day(s)<extra></extra>",
        )
    )
    apply_theme(
        fig,
        height=max(HEIGHT_SM, 34 * len(matrix.index) + 140),
        title="Drivers × price character — day counts",
    )
    fig.update_xaxes(title_text="Price character", side="bottom")
    fig.update_yaxes(title_text="Driver")
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
                hovertemplate=(label + "<br>Cumulative £%{y:,.0f}<extra></extra>"),
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
    mid_col: str = "mid_price",
    days: int | None = None,
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

    ``days`` divides those sums into a per-day average. Over a window, totals
    say as much about how many days were selected as about the battery, so a
    range view should pass it; a single day should not.
    """
    df = dispatch_df[[hour_col, mw_col, price_col]].dropna()
    hours = list(range(24))

    # Average realised MID by hour, when the frame carries it (live dashboard).
    avg_mid = None
    if mid_col in dispatch_df.columns:
        mid_df = dispatch_df[[hour_col, mid_col]].dropna()
        if not mid_df.empty:
            avg_mid = mid_df.groupby(hour_col)[mid_col].mean()

    discharge = df[df[mw_col] > 0]
    charge = df[df[mw_col] < 0]
    scale = float(days) if days else 1.0
    dis_mwh = (discharge[mw_col] * duration_h).groupby(discharge[hour_col]).sum() / scale
    chg_mwh = (-charge[mw_col] * duration_h).groupby(charge[hour_col]).sum() / scale
    avg_da = df.groupby(hour_col)[price_col].mean()

    dis_e = discharge[mw_col] * duration_h
    chg_e = -charge[mw_col] * duration_h
    w_dis = (discharge[price_col] * dis_e).sum() / dis_e.sum() if dis_e.sum() > 0 else 0.0
    w_chg = (charge[price_col] * chg_e).sum() / chg_e.sum() if chg_e.sum() > 0 else 0.0
    spread = w_dis - w_chg

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=hours,
            y=[float(dis_mwh.get(h, 0.0)) for h in hours],
            name="Discharge (sell)",
            marker_color=COLORS["discharge"],
            opacity=0.85,
            hovertemplate="Discharge %{y:,.1f} MWh<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=hours,
            y=[float(chg_mwh.get(h, 0.0)) for h in hours],
            name="Charge (buy)",
            marker_color=COLORS["charge"],
            opacity=0.85,
            hovertemplate="Charge %{y:,.1f} MWh<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=hours,
            y=[float(avg_da.get(h)) if h in avg_da.index else None for h in hours],
            name="Avg DA price",
            mode="lines",
            line=dict(color=COLORS["da"], width=2, dash="dash"),
            hovertemplate="%{x:02d}:00<br>Avg DA £%{y:.1f}<extra></extra>",
        ),
        secondary_y=True,
    )
    if avg_mid is not None:
        fig.add_trace(
            go.Scatter(
                x=hours,
                y=[float(avg_mid.get(h)) if h in avg_mid.index else None for h in hours],
                name="Avg MID price",
                mode="lines",
                line=dict(color=COLORS["mid"], width=2, dash="dot"),
                hovertemplate="%{x:02d}:00<br>Avg MID £%{y:.1f}<extra></extra>",
            ),
            secondary_y=True,
        )
    fig.update_layout(
        title=f"Price Capture — charge/discharge vs DA price (achieved spread £{spread:,.2f}/MWh)",
        barmode="group",
        template="plotly_white",
        height=400,
        legend=dict(orientation="h", x=0, y=1.12),
    )
    fig.update_xaxes(title_text="Hour of Day", dtick=2)
    fig.update_yaxes(
        title_text="Energy per day (MWh)" if days else "Energy (MWh)", secondary_y=False
    )
    fig.update_yaxes(title_text="Avg Price (£/MWh)", secondary_y=True)
    return fig


# --------------------------------------------------------------------------- #
# Live GB fleet tab (real batteries, per-BMU Elexon data)
# --------------------------------------------------------------------------- #
# One spec per single-magnitude fleet metric: value column, text format,
# axis title, chart-title fragment. "volume" is special-cased everywhere
# because it plots two signed series (discharge up, charge down).
_FLEET_METRIC_SPECS = {
    "revenue": ("gbp_per_mw_day", "£{:,.0f}", "Estimated revenue (£/MW/day)", "estimated £/MW/day"),
    "capture": ("capture_spread", "£{:,.1f}", "Capture spread (£/MWh)", "£/MWh discharged"),
    "cycles": ("cycles_per_day", "{:.2f}", "Cycles per day", "cycles/day"),
    "capacity": ("power_mw", "{:,.0f}", "Nameplate power (MW)", "nameplate MW"),
}


def _volume_pair(fig: go.Figure, keys, discharge, charge, horizontal: bool = False):
    """Add the signed discharge/charge bar pair shared by the volume views."""
    for name, values, color in (
        ("Discharged", discharge, COLORS["discharge"]),
        ("Charged", [-v for v in charge], COLORS["charge"]),
    ):
        axes = dict(x=values, y=keys, orientation="h") if horizontal else dict(x=keys, y=values)
        key_ref, val_ref = ("%{y}", "%{x:,.0f}") if horizontal else ("%{x}", "%{y:,.0f}")
        fig.add_trace(
            go.Bar(
                name=name,
                marker_color=color,
                hovertemplate=f"{key_ref}<br>{name} {val_ref} MWh<extra></extra>",
                **axes,
            )
        )
    fig.update_layout(barmode="relative")


def chart_fleet_leaderboard(site_df: pd.DataFrame, metric: str = "revenue"):
    """Ranked horizontal leaderboard of real GB battery sites.

    ``site_df`` is the per-site summary frame from
    :func:`fleet.performance.summarise_by_site`. ``metric`` selects what the
    bars encode: est. £/MW/day (default), avg charge/discharge volume,
    cycles/day or nameplate MW. Single-magnitude bars share one hue and flip
    to the cost red only when negative; the optimiser is carried in the
    y-label, not a hue.
    """
    height = max(DEFAULT_CHART_HEIGHT, 26 * len(site_df) + 120)

    if metric == "volume":
        df = site_df.assign(vol=site_df["discharge_mwh"] / site_df["days"]).sort_values("vol")
        labels = [f"{s}  ·  {o}" for s, o in zip(df["site"], df["optimiser"])]
        fig = go.Figure()
        _volume_pair(fig, labels, df["vol"], df["charge_mwh"] / df["days"], horizontal=True)
        apply_theme(fig, height=height, title="Site leaderboard — avg MWh per day")
        fig.update_xaxes(title_text="Energy (MWh/day; charge shown negative)")
        return fig

    col, fmt, axis, fragment = _FLEET_METRIC_SPECS[metric]
    df = site_df.sort_values(col)
    labels = [f"{s}  ·  {o}" for s, o in zip(df["site"], df["optimiser"])]
    # Revenue and capture spread are the two metrics that can go negative —
    # a site can pay more to charge than it earns discharging — and a
    # negative there means something has gone wrong, so it flips to red.
    # Cycles, volume and capacity cannot be negative.
    negative_flips = metric in ("revenue", "capture")
    colors = [
        COLORS["cost"] if (negative_flips and v < 0) else COLORS["da"] for v in df[col]
    ]
    fig = go.Figure(
        go.Bar(
            x=df[col],
            y=labels,
            orientation="h",
            marker_color=colors,
            text=[fmt.format(v) for v in df[col]],
            textposition="outside",
            textfont=dict(size=11, color=_INK),
            customdata=df[["power_mw", "days", "total_gbp"]].values,
            hovertemplate=(
                "%{y}<br>" + axis + ": %{x:,.2f}"
                "<br>%{customdata[0]:,.0f} MW · %{customdata[1]:.0f} days"
                "<br>Total £%{customdata[2]:,.0f}<extra></extra>"
            ),
        )
    )
    apply_theme(fig, height=height, title=f"Site leaderboard — {fragment}")
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title_text=axis)
    return fig


def _chart_fleet_grouped(df: pd.DataFrame, key: str, label: str, metric: str):
    """Shared metric bar for the optimiser/region groupings."""
    if metric == "volume":
        df = df.sort_values("discharge_mwh_day", ascending=False)
        fig = go.Figure()
        _volume_pair(fig, df[key], df["discharge_mwh_day"], df["charge_mwh_day"])
        apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title=f"{label} — avg MWh per day")
        fig.update_yaxes(title_text="Energy (MWh/day; charge shown negative)")
        return fig

    col, fmt, axis, fragment = _FLEET_METRIC_SPECS[metric]
    df = df.sort_values(col, ascending=False)
    # Revenue and capture spread are the two metrics that can go negative —
    # a site can pay more to charge than it earns discharging — and a
    # negative there means something has gone wrong, so it flips to red.
    # Cycles, volume and capacity cannot be negative.
    negative_flips = metric in ("revenue", "capture")
    colors = [
        COLORS["cost"] if (negative_flips and v < 0) else COLORS["da"] for v in df[col]
    ]
    fig = go.Figure(
        go.Bar(
            x=df[key],
            y=df[col],
            marker_color=colors,
            text=[fmt.format(v) for v in df[col]],
            textposition="outside",
            textfont=dict(size=11, color=_INK),
            customdata=df[["sites", "power_mw", "total_gbp"]].values,
            hovertemplate=(
                "%{x}<br>" + axis + ": %{y:,.2f}"
                "<br>%{customdata[0]:.0f} site(s) · %{customdata[1]:,.0f} MW"
                "<br>Total £%{customdata[2]:,.0f}<extra></extra>"
            ),
        )
    )
    # Revenue is the only MW-weighted average; the others are plain totals/rates.
    weighted = " — MW-weighted" if metric == "revenue" else " —"
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title=f"{label}{weighted} {fragment}")
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title_text=axis)
    return fig


def chart_fleet_spread(dist: pd.DataFrame, metric: str = "revenue") -> go.Figure:
    """What a typical site did each day, and how far apart the sites were.

    ``dist`` is :func:`fleet.performance.fleet_daily_distribution` — ``date``,
    ``median``, ``p25``, ``p75``, ``min`` and ``max``. The fleet total answers "how did the fleet
    do"; this answers "how did a site do", which is a different question when
    one 500 MW battery can carry a day on its own. A widening band is
    dispersion opening up between operators.
    """
    d = dist.copy()
    d["date"] = pd.to_datetime(d["date"])
    _col, fmt, axis, _fragment = _FLEET_METRIC_SPECS.get(
        metric, ("", "{:,.2f}", "Value", "")
    )
    fig = go.Figure()
    # Two nested bands: the full range faintest, the interquartile range darker
    # inside it. The gap between them is the tail — one site having an
    # exceptional day, which the quartiles deliberately refuse to show.
    for lo, hi, fill, edge, label in (
        ("min", "max", "rgba(42, 120, 214, 0.16)", "rgba(42, 120, 214, 0.55)", "Min–max"),
        ("p25", "p75", "rgba(42, 120, 214, 0.30)", "rgba(0, 0, 0, 0)", "P25–P75"),
    ):
        # No silent skip: a missing bound means the caller handed over a frame
        # without it, and dropping the band quietly is how a chart ends up
        # titled "full range" while showing none.
        if lo not in d.columns or hi not in d.columns:
            raise KeyError(
                f"chart_fleet_spread needs '{lo}' and '{hi}'; got {list(d.columns)}"
            )
        # The outer band gets a visible edge: at a fill alpha low enough to sit
        # under the inner band, the extremes are otherwise invisible.
        fig.add_trace(
            go.Scatter(
                x=d["date"], y=d[hi], mode="lines",
                line=dict(width=1, color=edge, dash="dot"),
                hoverinfo="skip", showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=d["date"], y=d[lo], mode="lines",
                line=dict(width=1, color=edge, dash="dot"),
                fill="tonexty", fillcolor=fill, name=label,
                customdata=d[hi],
                hovertemplate=(
                    f"{label} %{{y:,.2f}} → %{{customdata:,.2f}}<extra></extra>"
                ),
            )
        )
    fig.add_trace(
        go.Scatter(
            x=d["date"], y=d["median"], mode="lines", name="Median site",
            line=dict(color=COLORS["da"], width=2),
            hovertemplate="Median %{y:,.2f}<extra></extra>",
        )
    )
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT,
                title="Typical site by day — median, interquartile and full range")
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text=axis)
    return fig


def chart_fleet_by_optimiser(opt_df: pd.DataFrame, metric: str = "revenue"):
    """Fleet metric by optimiser (route-to-market party).

    ``opt_df`` comes from :func:`fleet.performance.summarise_by_optimiser`;
    for the revenue metric every site-day is weighted by its MW, so a 500 MW
    site moves its optimiser's average more than a 50 MW one.
    """
    return _chart_fleet_grouped(opt_df, "optimiser", "By optimiser", metric)


def chart_fleet_by_region(region_df: pd.DataFrame, metric: str = "revenue"):
    """Fleet metric by region — the locational split."""
    return _chart_fleet_grouped(region_df, "region", "By region", metric)


def chart_fleet_daily(daily_df: pd.DataFrame, metric: str = "revenue"):
    """Whole-fleet daily view of the selected metric.

    ``daily_df`` is :func:`fleet.performance.fleet_daily`. Revenue stacks the
    wholesale proxy vs BM — the two can take opposite signs (e.g. paying to
    charge in the BM while long in the wholesale proxy), so bars use plotly's
    signed stacking (``barmode "relative"``) with a net-total line over the
    top. Volume shows discharge up / charge down; cycles and capacity are a
    single daily series (capacity doubles as a data-coverage view — it dips
    when a site's data is missing).
    """
    dates = pd.to_datetime(daily_df["date"])

    if metric == "volume":
        fig = go.Figure()
        _volume_pair(fig, dates, daily_df["discharge_mwh"], daily_df["charge_mwh"])
        apply_theme(
            fig, height=DEFAULT_CHART_HEIGHT, title="Fleet energy by day — discharge vs charge"
        )
        fig.update_layout(hovermode="x unified")
        fig.update_yaxes(title_text="Energy (MWh; charge shown negative)")
        return fig

    if metric in ("cycles", "capacity", "capture"):
        col, title, axis = {
            "cycles": ("cycles", "Fleet cycles per day", "Cycles per day"),
            "capture": (
                "capture_spread",
                "Fleet capture spread by day",
                "Capture spread (£/MWh discharged)",
            ),
            "capacity": (
                "mw",
                "Fleet nameplate reporting by day — coverage",
                "Nameplate power reporting (MW)",
            ),
        }[metric]
        fig = go.Figure(
            go.Bar(
                x=dates,
                y=daily_df[col],
                marker_color=COLORS["da"],
                hovertemplate="%{y:,.2f}<extra></extra>",
            )
        )
        apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title=title)
        fig.update_layout(showlegend=False)
        fig.update_yaxes(title_text=axis)
        return fig

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=dates,
            y=daily_df["wholesale_gbp"],
            name="Wholesale proxy (PN × MID)",
            marker_color=COLORS["da"],
            hovertemplate="Wholesale £%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=dates,
            y=daily_df["bm_gbp"],
            name="Balancing Mechanism",
            marker_color=COLORS["bm"],
            hovertemplate="BM £%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=daily_df["total_gbp"],
            name="Net total",
            mode="lines",
            line=dict(color=COLORS["net"], width=2),
            hovertemplate="Net £%{y:,.0f}<extra></extra>",
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


# --------------------------------------------------------------------------- #
# Sim vs fleet comparison
# --------------------------------------------------------------------------- #
def chart_sim_vs_fleet_sites(df: pd.DataFrame, sim_gbp: float, sim_label: str) -> go.Figure:
    """Per-site £/MW/day split wholesale vs BM, against the sim ceiling.

    ``df`` has one row per site: ``site``, ``optimiser``, ``wholesale`` and
    ``bm`` (£/MW/day over the common days) and ``ratio`` (wholesale ÷ sim).
    Only the wholesale leg is comparable to the simulation — the BM segment is
    revenue from a market the sim does not play, so it is stacked separately
    and excluded from the ratio labels. ``sim_gbp`` is drawn as a reference
    line, not a bar: it is a perfect-foresight ceiling, not a competitor.
    """
    df = df.sort_values("wholesale")
    labels = [f"{s}  ·  {o}" for s, o in zip(df["site"], df["optimiser"])]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["wholesale"],
            y=labels,
            orientation="h",
            name="Wholesale leg (PN × MID)",
            marker_color=COLORS["da"],
            text=[f"{r:.0%}" for r in df["ratio"]],
            textposition="outside",
            textfont=dict(size=11, color=_INK),
            hovertemplate=(
                "%{y}<br>Wholesale £%{x:,.0f}/MW/day"
                "<br>%{text} of the sim ceiling<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Bar(
            x=df["bm"],
            y=labels,
            orientation="h",
            name="BM (not in the sim)",
            marker_color=COLORS["bm"],
            hovertemplate="%{y}<br>BM £%{x:,.0f}/MW/day<extra></extra>",
        )
    )
    fig.add_vline(
        x=sim_gbp,
        line=dict(color=COLORS["net"], width=2, dash="dash"),
        annotation_text=sim_label,
        annotation_position="top",
    )
    apply_theme(
        fig,
        height=max(DEFAULT_CHART_HEIGHT, 30 * len(df) + 140),
        title="Sites vs the sim ceiling — like legs compared, BM shown apart",
    )
    fig.update_layout(barmode="relative")
    fig.update_xaxes(title_text="Estimated revenue (£/MW/day)")
    return fig


def chart_sim_vs_fleet_daily(df: pd.DataFrame) -> go.Figure:
    """Daily £/MW/day: sim ceiling vs the matched fleet wholesale average.

    The area between the lines is the day's foresight-plus-skill gap; shading
    it makes decoupling episodes visible at a glance.
    """
    dates = pd.to_datetime(df["date"])
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=df["fleet"],
            name="Fleet wholesale avg",
            mode="lines",
            line=dict(color=COLORS["da"], width=2),
            hovertemplate="Fleet £%{y:,.0f}/MW<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=df["sim"],
            name="Sim ceiling",
            mode="lines",
            line=dict(color=COLORS["net"], width=2, dash="dash"),
            fill="tonexty",
            fillcolor="rgba(137, 135, 129, 0.15)",
            hovertemplate="Sim £%{y:,.0f}/MW<extra></extra>",
        )
    )
    apply_theme(
        fig,
        height=DEFAULT_CHART_HEIGHT,
        title="Daily £/MW/day — sim ceiling vs fleet wholesale (gap shaded)",
    )
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="Estimated revenue (£/MW/day)")
    return fig


def chart_shape_overlay(df: pd.DataFrame) -> go.Figure:
    """Mean hourly dispatch shape: sim vs fleet, as a share of nameplate MW.

    Both series are normalised (net MW ÷ nameplate MW, positive = discharge)
    so a 50 MW sim and a multi-GW fleet share one axis honestly.
    """
    fig = go.Figure()
    for col, name, color, dash in (
        ("fleet", "Fleet (aggregate PN)", COLORS["da"], None),
        ("sim", "Sim dispatch", COLORS["net"], "dash"),
    ):
        fig.add_trace(
            go.Scatter(
                x=df["hour"],
                y=df[col],
                name=name,
                mode="lines+markers",
                line=dict(color=color, width=2, dash=dash),
                marker=dict(size=5),
                hovertemplate=name + "<br>Hour %{x}<br>%{y:.1%} of nameplate<extra></extra>",
            )
        )
    fig.add_hline(y=0.0, line=dict(color=_AXIS, width=1))
    apply_theme(
        fig,
        height=DEFAULT_CHART_HEIGHT,
        title="When batteries move — mean net output by hour (discharge positive)",
    )
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(title_text="Hour of day (UTC)", dtick=2)
    fig.update_yaxes(title_text="Net output (share of nameplate)", tickformat=".0%")
    return fig


def chart_cycles_vs_revenue(df: pd.DataFrame, sim_cycles: float, sim_gbp: float) -> go.Figure:
    """Work-rate vs earnings: each site by cycles/day and £/MW/day, sim starred.

    ``df`` columns: ``site``, ``optimiser``, ``cycles_per_day``,
    ``gbp_per_mw_day`` and ``excluded`` (⚠ ancillary-tilted sites, shown as
    ghosts so the eye discounts them without losing them).
    """
    fig = go.Figure()
    for excluded, name, color in (
        (False, "Sites", COLORS["da"]),
        (True, "⚠ ancillary-tilted (excluded)", COLORS["ghost"]),
    ):
        sub = df[df["excluded"] == excluded]
        if sub.empty:
            continue
        hover = [f"{s} · {o}" for s, o in zip(sub["site"], sub["optimiser"])]
        fig.add_trace(
            go.Scatter(
                x=sub["cycles_per_day"],
                y=sub["gbp_per_mw_day"],
                mode="markers",
                name=name,
                marker=dict(color=color, size=10, line=dict(width=1, color="white")),
                customdata=hover,
                hovertemplate=(
                    "%{customdata}<br>%{x:.2f} cycles/day · £%{y:,.0f}/MW/day<extra></extra>"
                ),
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[sim_cycles],
            y=[sim_gbp],
            mode="markers",
            name="Sim (perfect foresight)",
            marker=dict(color=COLORS["net"], size=14, symbol="star"),
            hovertemplate=(
                "Sim<br>%{x:.2f} cycles/day · £%{y:,.0f}/MW/day<extra></extra>"
            ),
        )
    )
    apply_theme(
        fig, height=DEFAULT_CHART_HEIGHT, title="Cycles vs revenue — work-rate against earnings"
    )
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title_text="Cycles per day")
    fig.update_yaxes(title_text="Estimated revenue (£/MW/day)")
    return fig


def chart_daytype_ratio(df: pd.DataFrame) -> go.Figure:
    """Fleet-wholesale ÷ sim-ceiling ratio per day-type tag.

    Shows where reality gets closest to perfect foresight; same family colours
    as the Day types page. ``df`` columns: ``tag``, ``family``, ``ratio``,
    ``days``.
    """
    order = _daytype_order(df, "ratio")
    d = df.set_index("tag").loc[order].reset_index()
    fig = go.Figure(
        go.Bar(
            x=d["ratio"],
            y=d["tag"],
            orientation="h",
            marker_color=[FAMILY_COLORS[f] for f in d["family"]],
            text=[f"{r:.0%}" for r in d["ratio"]],
            textposition="outside",
            textfont=dict(size=11, color=_INK),
            customdata=d["days"],
            hovertemplate="%{y}<br>%{x:.0%} of sim · %{customdata} day(s)<extra></extra>",
        )
    )
    apply_theme(
        fig,
        height=max(HEIGHT_SM, 30 * len(d) + 110),
        title="Realisation by day-type — fleet wholesale as a share of the sim",
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title_text="Fleet wholesale ÷ sim ceiling", tickformat=".0%")
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    return fig


# --------------------------------------------------------------------------- #
# System overview
# --------------------------------------------------------------------------- #
# Each generation group keeps a fixed hue (colour follows the fuel, never its
# rank in the stack); order matches fetch_live.GENERATION_GROUP_ORDER. The hues
# are the conventional energy-sector ones — blue for wind, yellow for solar,
# purple for nuclear, an earthy rust for thermal gas, green for biomass, deep
# marine for hydro, a synthetic lilac for traded interconnector power, and grey
# for the residual.
#
# Two adjacent pairs sit closer than the usual separation thresholds:
# Gas/Biomass are a red-green pair that deuteranopes struggle to split, and
# Interconnectors/Other are close even in normal vision. Both stacks therefore
# draw a hairline in the surface colour between bands, which is the secondary
# encoding that keeps them readable — do not remove it.
GENERATION_COLORS = {
    "Wind": "#4A90E2",
    "Solar": "#F2C94C",
    "Nuclear": "#9B51E0",
    "Gas": "#D06A4C",
    "Biomass": "#66BB6A",
    "Hydro": "#2F80ED",
    "Interconnectors": "#A29BFE",
    "Other": "#B2BEC3",
}


def chart_generation_mix(groups: pd.DataFrame, demand: pd.Series | None = None) -> go.Figure:
    """Stacked half-hourly generation mix (MW) with demand overlaid.

    ``groups`` is the grouped frame from :func:`live.fetch_live.group_generation`
    — one column per fuel group, already in stack order. Net interconnectors
    can dip negative (GB exporting), which plotly stacks below the baseline.
    ``demand`` (actual outturn, MW) is drawn as a dotted reference line so the
    supply stack can be read against the load it served.
    """
    fig = go.Figure()
    for name in groups.columns:
        color = GENERATION_COLORS.get(name, _OVERFLOW)
        fig.add_trace(
            go.Scatter(
                x=groups.index,
                y=groups[name],
                name=name,
                mode="lines",
                # A hairline in the surface colour gives the 2px gap between bands.
                line=dict(width=1, color="rgba(255,255,255,0.85)"),
                stackgroup="gen",
                fillcolor=color,
                hovertemplate=name + ": %{y:,.0f} MW<extra></extra>",
            )
        )
    if demand is not None and not demand.empty:
        fig.add_trace(
            go.Scatter(
                x=demand.index,
                y=demand.values,
                name="Demand (outturn)",
                mode="lines",
                line=dict(color=COLORS["net"], width=2, dash="dot"),
                hovertemplate="Demand<br>%{y:,.0f} MW<extra></extra>",
            )
        )
    apply_theme(fig, height=HEIGHT_LG, title="Generation mix — half-hourly (MW)")
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="Power (MW)")
    return fig


def chart_price_volatility(df: pd.DataFrame) -> go.Figure:
    """Each day's day-ahead price spread, as a min–max band around the mean.

    ``df`` columns: ``date``, ``da_min``, ``da_p10``, ``avg_da``, ``da_p90``,
    ``da_max``. Two nested bands — full range in the faintest ink, the P10–P90
    interdecile range darker inside it — with the daily mean as the only solid
    line. A day whose bands are wide is a day worth trading; the mean alone
    hides exactly that.
    """
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    fig = go.Figure()
    for lo, hi, fill, label in (
        ("da_min", "da_max", "rgba(42, 120, 214, 0.16)", "Min–max"),
        ("da_p10", "da_p90", "rgba(42, 120, 214, 0.30)", "P10–P90"),
    ):
        if lo not in d.columns or hi not in d.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=d["date"], y=d[hi], mode="lines", line=dict(width=0),
                hoverinfo="skip", showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=d["date"], y=d[lo], mode="lines", line=dict(width=0),
                fill="tonexty", fillcolor=fill, name=label,
                # The trace is named for a range but only carries its lower
                # edge, so the upper edge rides along as customdata — otherwise
                # the tooltip reads "Min–max" beside a single number, which is
                # the min.
                customdata=d[hi],
                hovertemplate=(
                    f"{label} £%{{y:,.0f}} → £%{{customdata:,.0f}}<extra></extra>"
                ),
            )
        )
    fig.add_trace(
        go.Scatter(
            x=d["date"], y=d["avg_da"], mode="lines", name="Daily mean",
            line=dict(color=COLORS["da"], width=2),
            hovertemplate="Mean £%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_hline(y=0, line=dict(color=_MUTED, width=1, dash="dot"))
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT,
                title="Daily price volatility — day-ahead £/MWh")
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="Day-ahead price (£/MWh)")
    return fig


def chart_stress_vs_demand(df: pd.DataFrame) -> go.Figure:
    """Daily peak demand against daily peak residual load.

    ``df`` columns: ``date``, ``peak_demand_gw``, ``peak_residual_gw``. The gap
    between the two lines is what wind and solar covered at the moment the
    system was working hardest — the residual line is the part the dispatchable
    fleet actually had to serve.
    """
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=d["date"], y=d["peak_demand_gw"], mode="lines", name="Peak demand",
            line=dict(color=COLORS["net"], width=2),
            hovertemplate="Peak demand %{y:,.1f} GW<extra></extra>",
        )
    )
    if "peak_residual_gw" in d.columns:
        fig.add_trace(
            go.Scatter(
                x=d["date"], y=d["peak_residual_gw"], mode="lines",
                name="Peak residual load", line=dict(color=COLORS["cost"], width=2),
                fill="tonexty", fillcolor="rgba(27, 175, 122, 0.16)",
                hovertemplate="Peak residual %{y:,.1f} GW<extra></extra>",
            )
        )
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT,
                title="Stress vs total demand — shaded gap is the renewable contribution")
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="GW")
    return fig


def chart_stress_frequency(df: pd.DataFrame) -> go.Figure:
    """How often each day was tight, and how often power was being given away.

    ``df`` columns: ``date``, ``stress`` (top-decile residual load) and
    ``negative`` (day-ahead hours below £0) — the two ends of the same story,
    scarcity and glut. Grouped rather than stacked: the two can coincide, and
    stacking would imply a total that does not exist.
    """
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    fig = go.Figure()
    for col, name, colour in (
        ("stress", "Top-decile stress", COLORS["cost"]),
        ("negative", "Negative price", COLORS["soc"]),
    ):
        if col not in d.columns:
            continue
        fig.add_trace(
            go.Bar(
                x=d["date"], y=d[col], name=name, marker_color=colour,
                hovertemplate=f"{name}: %{{y}} period(s)<extra></extra>",
            )
        )
    apply_theme(fig, height=HEIGHT_SM,
                title="Stress & negative-price frequency — periods per day")
    fig.update_layout(barmode="group", bargap=0.25, hovermode="x unified")
    fig.update_yaxes(title_text="Periods per day")
    return fig


def chart_system_prices(
    prices: pd.DataFrame,
    title: str = "Wholesale prices — £/MWh",
    hover_fmt: str = "%H:%M",
) -> go.Figure:
    """Day-ahead and MID prices on one shared £/MWh axis.

    ``prices`` has columns ``day_ahead_price`` and ``mid_price`` on a datetime
    index — half-hourly for one day (:func:`live.fetch_live.get_day_prices`) or
    one point per day for a window average. Both are prices in the same unit,
    so they share one axis — never a second scale. ``hover_fmt`` switches the
    hover label between an intraday clock and a calendar date.
    """
    fig = go.Figure()
    for col, name, color in (
        ("day_ahead_price", "Day-ahead (N2EX)", COLORS["da"]),
        ("mid_price", "MID (intraday)", COLORS["mid"]),
    ):
        if col not in prices.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=prices.index,
                y=prices[col],
                name=name,
                mode="lines",
                line=dict(color=color, width=2),
                hovertemplate=name + "<br>£%{y:,.1f}/MWh<extra></extra>",
            )
        )
    fig.add_hline(y=0.0, line=dict(color=_AXIS, width=1))
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title=title)
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="Price (£/MWh)")
    return fig


def chart_generation_daily(daily: pd.DataFrame, group_cols: list[str]) -> go.Figure:
    """Daily generation energy by source (GWh), stacked one bar per day.

    The range analogue of :func:`chart_generation_mix`: ``daily`` has a
    ``date`` column and one column per generation group (daily energy in GWh),
    with groups in stack order. Net interconnectors can be negative (export
    days), which relative stacking places below the baseline.
    """
    dates = pd.to_datetime(daily["date"])
    fig = go.Figure()
    for name in group_cols:
        fig.add_trace(
            go.Bar(
                x=dates,
                y=daily[name],
                name=name,
                marker_color=GENERATION_COLORS.get(name, _OVERFLOW),
                # Hairline in the surface colour, matching the half-hourly mix:
                # it separates adjacent bands whose hues are close.
                marker_line=dict(width=1, color="rgba(255,255,255,0.85)"),
                hovertemplate=name + ": %{y:,.0f} GWh<extra></extra>",
            )
        )
    apply_theme(fig, height=HEIGHT_LG, title="Daily generation by source (GWh)")
    fig.update_layout(barmode="relative", hovermode="x unified")
    fig.update_yaxes(title_text="Energy (GWh/day)")
    return fig


def chart_renewable_daily(daily: pd.DataFrame, renewable_cols: list[str]) -> go.Figure:
    """Daily renewable share of GB generation, with energy in hover.

    Renewables rather than low-carbon: nuclear is clean but runs as flat
    baseload, so including it adds a near-constant offset and damps exactly the
    variability this page exists to show. Wind and solar swinging is what moves
    prices and what a battery trades against.

    ``renewable_cols`` are the generation groups counted as renewable — see
    :data:`live.fetch_live.RENEWABLE_GROUPS`, which notes that the hydro band
    also carries pumped storage.
    """
    dates = pd.to_datetime(daily["date"])
    generation_cols = [
        c for c in GENERATION_COLORS if c in daily.columns and c != "Interconnectors"
    ]
    total = daily[generation_cols].fillna(0.0).sum(axis=1)
    renewable = daily[renewable_cols].fillna(0.0).sum(axis=1)
    fig = go.Figure(
        go.Scatter(
            x=dates,
            y=renewable.div(total.where(total > 0)),
            customdata=renewable,
            name="Renewable share",
            mode="lines+markers",
            line=dict(color=GENERATION_COLORS["Biomass"], width=3),
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor="rgba(102, 187, 106, 0.18)",
            hovertemplate=(
                "Renewable share: %{y:.1%}<br>"
                "Renewable generation: %{customdata:,.0f} GWh<extra></extra>"
            ),
        )
    )
    apply_theme(fig, height=DEFAULT_CHART_HEIGHT, title="Daily renewable generation share")
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="Share of GB generation", tickformat=".0%", range=[0, 1])
    return fig


# --------------------------------------------------------------------------- #
# Alignment (dispatch vs system state)
# --------------------------------------------------------------------------- #
# Shading for classified periods: stress leans on the cost red, surplus on the
# discharge teal, both at low alpha so the data marks stay dominant.
_STRESS_FILL = "rgba(227, 73, 72, 0.14)"
_SURPLUS_FILL = "rgba(27, 175, 122, 0.12)"


def _flag_spans(flags: pd.Series) -> list[tuple]:
    """Contiguous True spans of a boolean series → [(start, end), …]."""
    spans = []
    start = None
    for ts, val in flags.items():
        if val and start is None:
            start = ts
        elif not val and start is not None:
            spans.append((start, ts))
            start = None
    if start is not None:
        spans.append((start, flags.index[-1]))
    return spans


def chart_alignment_day(day_flags: pd.DataFrame, dispatch_mw: pd.Series) -> go.Figure:
    """One day: residual load with stress/surplus shading over battery dispatch.

    ``day_flags`` is the half-hourly classification frame (``residual_mw``,
    ``stress``, ``surplus``) for a single day; ``dispatch_mw`` the benchmark's
    hourly net dispatch (positive = discharge). Two stacked panels share the
    time axis — residual load is a system quantity in GW, dispatch a battery
    quantity in MW, so they never share a y-axis.
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        row_heights=[0.55, 0.45],
    )
    fig.add_trace(
        go.Scatter(
            x=day_flags.index,
            y=day_flags["residual_mw"] / 1000.0,
            name="Residual load",
            mode="lines",
            line=dict(color=COLORS["net"], width=2),
            hovertemplate="Residual %{y:,.1f} GW<extra></extra>",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Bar(
            x=dispatch_mw.index,
            y=dispatch_mw.values,
            name="Benchmark dispatch",
            marker_color=_dispatch_bar_colors(dispatch_mw.values),
            hovertemplate="%{y:,.0f} MW<extra></extra>",
        ),
        row=2, col=1,
    )
    # ISO strings keep the shapes serialisable for every renderer (kaleido's
    # JSON encoder rejects raw Timestamps).
    for start, end in _flag_spans(day_flags["stress"]):
        fig.add_vrect(x0=str(start), x1=str(end), fillcolor=_STRESS_FILL, line_width=0)
    for start, end in _flag_spans(day_flags["surplus"]):
        fig.add_vrect(x0=str(start), x1=str(end), fillcolor=_SURPLUS_FILL, line_width=0)

    apply_theme(
        fig,
        height=HEIGHT_LG,
        title="Dispatch against system state — stress (red) and surplus (green) shaded",
    )
    fig.update_layout(hovermode="x unified", showlegend=True)
    fig.update_yaxes(title_text="Residual load (GW)", row=1, col=1)
    fig.update_yaxes(title_text="Dispatch (MW)", row=2, col=1)
    return fig


# Tier shading escalates within the stress-red family: tier 2 (system-confirmed
# tight) at the familiar low alpha, tier 3 (declared CMN) noticeably stronger.
_TIER2_FILL = "rgba(227, 73, 72, 0.14)"
_TIER3_FILL = "rgba(227, 73, 72, 0.30)"


def chart_system_tightness(
    tiers: pd.DataFrame,
    dispatch_mw: pd.Series | None = None,
    drm_tight_mw: float = 2000.0,
) -> go.Figure:
    """De-rated margin, LoLP and the tier ladder over the window, with dispatch.

    ``tiers`` is the half-hourly frame from ``resilience.classify_tiers``
    (columns ``drm_mw``, ``lolp``, ``tier2``, ``tier3``); ``dispatch_mw`` the
    benchmark's net dispatch (positive = discharge). Two stacked panels share
    the time axis — margin is a system quantity, dispatch a battery quantity,
    so they never share a y-axis. Tier-2 tight periods are shaded like stress,
    tier-3 (declared CMN) darker with a label. Survives an empty or all-NaN
    frame: the theme and threshold still render, just with no marks.
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        row_heights=[0.6, 0.4],
    )
    drm = tiers["drm_mw"].dropna() if "drm_mw" in tiers.columns else pd.Series(dtype=float)
    if len(drm):
        fig.add_trace(
            go.Scatter(
                x=drm.index,
                y=drm.values,
                name="De-rated margin",
                mode="lines",
                line=dict(color=COLORS["net"], width=2),
                hovertemplate="DRM %{y:,.0f} MW<extra></extra>",
            ),
            row=1, col=1,
        )
        lolp_hot = tiers[(tiers["lolp"] > 0.0) & tiers["drm_mw"].notna()]
        if len(lolp_hot):
            fig.add_trace(
                go.Scatter(
                    x=lolp_hot.index,
                    y=lolp_hot["drm_mw"].values,
                    name="LoLP > 0",
                    mode="markers",
                    marker=dict(color=COLORS["cost"], size=8,
                                line=dict(width=1, color="white")),
                    customdata=lolp_hot["lolp"].values,
                    hovertemplate=(
                        "LoLP %{customdata:.1%} · "
                        "DRM %{y:,.0f} MW<extra></extra>"
                    ),
                ),
                row=1, col=1,
            )
    fig.add_hline(
        y=drm_tight_mw,
        row=1, col=1,
        line=dict(color=COLORS["cost"], width=1, dash="dot"),
        annotation_text=f"tight < {drm_tight_mw:,.0f} MW",
        annotation_position="bottom right",
        annotation_font=dict(size=11, color=COLORS["cost"]),
    )
    if dispatch_mw is not None and len(dispatch_mw):
        fig.add_trace(
            go.Bar(
                x=dispatch_mw.index,
                y=dispatch_mw.values,
                name="Benchmark dispatch",
                marker_color=_dispatch_bar_colors(dispatch_mw.values),
                hovertemplate="%{y:,.0f} MW<extra></extra>",
            ),
            row=2, col=1,
        )
    # ISO strings keep the shapes serialisable for every renderer (kaleido's
    # JSON encoder rejects raw Timestamps).
    if "tier2" in tiers.columns:
        for start, end in _flag_spans(tiers["tier2"].fillna(False)):
            fig.add_vrect(x0=str(start), x1=str(end), fillcolor=_TIER2_FILL, line_width=0)
    if "tier3" in tiers.columns:
        for start, end in _flag_spans(tiers["tier3"].fillna(False)):
            fig.add_vrect(
                x0=str(start), x1=str(end), fillcolor=_TIER3_FILL, line_width=0,
                annotation_text="CMN", annotation_position="top left",
                annotation_font=dict(size=11, color=COLORS["cost"]),
            )

    apply_theme(
        fig,
        height=HEIGHT_LG,
        title="System tightness — de-rated margin, LoLP and declared notices",
    )
    fig.update_layout(hovermode="x unified", showlegend=True)
    fig.update_yaxes(title_text="De-rated margin (MW)", row=1, col=1)
    fig.update_yaxes(title_text="Dispatch (MW)", row=2, col=1)
    return fig


def chart_alignment_scatter(df: pd.DataFrame, sim_coverage: float | None,
                            sim_gbp: float) -> go.Figure:
    """Profit vs alignment: each fleet site by stress coverage and £/MW/day.

    The poster-level view: where do real GB batteries sit on the
    profit/resilience plane, and where does the profit-optimal benchmark sit?
    ``df`` columns: ``site``, ``optimiser``, ``stress_coverage`` (0–1),
    ``gbp_per_mw_day``, ``excluded`` (⚠ ancillary-tilted, ghosted).
    """
    fig = go.Figure()
    for excluded, name, color in (
        (False, "Fleet sites", COLORS["da"]),
        (True, "⚠ ancillary-tilted (excluded)", COLORS["ghost"]),
    ):
        sub = df[df["excluded"] == excluded]
        if sub.empty:
            continue
        hover = [f"{s} · {o}" for s, o in zip(sub["site"], sub["optimiser"])]
        fig.add_trace(
            go.Scatter(
                x=sub["stress_coverage"],
                y=sub["gbp_per_mw_day"],
                mode="markers",
                name=name,
                marker=dict(color=color, size=10, line=dict(width=1, color="white")),
                customdata=hover,
                hovertemplate=(
                    "%{customdata}<br>Stress coverage %{x:.0%} · "
                    "£%{y:,.0f}/MW/day<extra></extra>"
                ),
            )
        )
    if sim_coverage is not None:
        fig.add_trace(
            go.Scatter(
                x=[sim_coverage],
                y=[sim_gbp],
                mode="markers",
                name="Benchmark (profit-optimal)",
                marker=dict(color=COLORS["net"], size=14, symbol="star"),
                hovertemplate=(
                    "Benchmark<br>Stress coverage %{x:.0%} · "
                    "£%{y:,.0f}/MW/day<extra></extra>"
                ),
            )
        )
    apply_theme(
        fig, height=DEFAULT_CHART_HEIGHT,
        title="Profit vs alignment — revenue against stress coverage",
    )
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title_text="Stress coverage (share of discharge in stress hours)",
                     tickformat=".0%")
    fig.update_yaxes(title_text="Estimated revenue (£/MW/day)")
    return fig


def chart_gap_by_daytype(df: pd.DataFrame) -> go.Figure:
    """Profit cost of full alignment per day-type tag (£/MW/day).

    ``df`` columns: ``tag``, ``family``, ``gap`` (£/MW/day), ``days``. Same
    family colours and ordering conventions as the Day types page.
    """
    order = _daytype_order(df.rename(columns={"gap": "capture"}), "capture")
    d = df.set_index("tag").loc[order].reset_index()
    fig = go.Figure(
        go.Bar(
            x=d["gap"],
            y=d["tag"],
            orientation="h",
            marker_color=[FAMILY_COLORS[f] for f in d["family"]],
            text=[f"£{v:,.0f}" for v in d["gap"]],
            textposition="outside",
            textfont=dict(size=11, color=_INK),
            customdata=d["days"],
            hovertemplate="%{y}<br>£%{x:,.0f}/MW/day · %{customdata} day(s)<extra></extra>",
        )
    )
    apply_theme(
        fig,
        height=max(HEIGHT_SM, 30 * len(d) + 110),
        title="Profit cost of full alignment by day-type",
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title_text="Forgone DA value (£/MW/day)")
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    return fig


def chart_day_composite(
    prices: pd.DataFrame,
    dispatch_mw: pd.Series,
    da_mw: pd.Series,
    soc_pct: pd.Series,
    day_flags: pd.DataFrame,
    min_soc_pct: float,
    max_soc_pct: float,
) -> go.Figure:
    """One day on one timeline: prices, action, state and system, aligned.

    Four stacked panels sharing the x-axis — DA/MID prices; dispatch bars with
    the locked DA commitment as a step reference; the SOC path inside its
    band; residual load — with stress (red) and surplus (green) periods shaded
    across all panels. Empty ``day_flags`` simply omits the shading and the
    residual panel's data.
    """
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.28, 0.28, 0.22, 0.22],
    )
    for col, name, color in (
        ("day_ahead_price", "DA price", COLORS["da"]),
        ("mid_price", "MID price", COLORS["mid"]),
    ):
        if col in prices.columns:
            fig.add_trace(
                go.Scatter(
                    x=prices.index, y=prices[col], name=name, mode="lines",
                    line=dict(color=color, width=2),
                    hovertemplate=name + "<br>£%{y:,.1f}/MWh<extra></extra>",
                ),
                row=1, col=1,
            )
    fig.add_trace(
        go.Scatter(
            x=da_mw.index, y=da_mw.values, name="DA commitment",
            mode="lines", line=dict(color=COLORS["ghost"], width=2, shape="hvh"),
            hovertemplate="DA commitment<br>%{y:,.0f} MW<extra></extra>",
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Bar(
            x=dispatch_mw.index, y=dispatch_mw.values, name="Dispatch",
            marker_color=_dispatch_bar_colors(dispatch_mw.values),
            hovertemplate="Dispatch<br>%{y:,.0f} MW<extra></extra>",
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=soc_pct.index, y=soc_pct.values, name="SOC",
            mode="lines", line=dict(color=COLORS["soc"], width=2),
            hovertemplate="SOC<br>%{y:.0%}<extra></extra>",
        ),
        row=3, col=1,
    )
    for level in (min_soc_pct, max_soc_pct):
        fig.add_hline(y=level, line=dict(color=_AXIS, width=1, dash="dot"), row=3, col=1)
    if not day_flags.empty:
        fig.add_trace(
            go.Scatter(
                x=day_flags.index, y=day_flags["residual_mw"] / 1000.0,
                name="Residual load", mode="lines",
                line=dict(color=COLORS["net"], width=2),
                hovertemplate="Residual<br>%{y:,.1f} GW<extra></extra>",
            ),
            row=4, col=1,
        )
        for start, end in _flag_spans(day_flags["stress"]):
            fig.add_vrect(x0=str(start), x1=str(end), fillcolor=_STRESS_FILL, line_width=0)
        for start, end in _flag_spans(day_flags["surplus"]):
            fig.add_vrect(x0=str(start), x1=str(end), fillcolor=_SURPLUS_FILL, line_width=0)

    apply_theme(
        fig, height=640,
        title="The day on one timeline — prices, action, state, system "
              "(stress red / surplus green)",
    )
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title_text="£/MWh", row=1, col=1)
    fig.update_yaxes(title_text="MW", row=2, col=1)
    fig.update_yaxes(title_text="SOC", tickformat=".0%", row=3, col=1)
    fig.update_yaxes(title_text="GW", row=4, col=1)
    return fig


def chart_day_in_window(daily_gbp_per_mw: pd.Series, current: float) -> go.Figure:
    """Where this day sits in the window's daily net £/MW distribution."""
    fig = go.Figure(
        go.Histogram(
            x=daily_gbp_per_mw.values,
            nbinsx=20,
            marker_color=COLORS["ghost"],
            name="Window days",
            hovertemplate="£%{x:,.0f}/MW · %{y} day(s)<extra></extra>",
        )
    )
    fig.add_vline(
        x=current,
        line=dict(color=COLORS["da"], width=3),
        annotation_text="this day",
        annotation_position="top",
    )
    apply_theme(fig, height=HEIGHT_SM, title="This day within the window — net £/MW per day")
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title_text="Net PnL (£/MW/day)")
    fig.update_yaxes(title_text="Days")
    return fig
