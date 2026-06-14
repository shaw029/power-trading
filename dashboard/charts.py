"""Plotly chart builders for the BESS dispatch dashboard (dashboard/app.py).

Each function takes already-sliced simulation frames and returns a Plotly
figure; they hold no Streamlit or data-loading logic so they can be reused and
tested in isolation.
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


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
    fig.add_trace(go.Bar(
        x=mean_mw.index, y=mean_mw.values, name="Mean DA commitment MW", yaxis="y2",
        marker_color=colors, opacity=0.5,
    ))
    fig.add_trace(go.Scatter(
        x=da_by_hour.index, y=da_by_hour.values,
        name="Mean DA price (actual)", yaxis="y", line=dict(color="#1f77b4", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=fc_by_hour.index, y=fc_by_hour.values,
        name="Mean DA forecast", yaxis="y",
        line=dict(color="#7fb3e0", width=1.5, dash="dash"),
    ))
    fig.update_layout(
        title="DA Commitment Shape — committed dispatch & DA price by hour",
        xaxis=dict(title="Hour of Day", dtick=1),
        yaxis=dict(title="DA Price (£/MWh)", side="left", title_font=dict(color="#1f77b4")),
        yaxis2=dict(
            title="Mean DA Commitment (MW, + discharge / − charge)",
            side="right", overlaying="y", title_font=dict(color="#555"),
        ),
        legend=dict(x=0, y=1.12, orientation="h"),
        template="plotly_white",
        height=400,
    )
    return fig


def chart_realized_shape(
    dispatch_df: pd.DataFrame,
    prices_hourly: pd.DataFrame,
    da_sched_df: pd.DataFrame,
):
    """Mean realised physical dispatch and execution prices by hour-of-day.

    The execution layer: what the battery physically did after the intraday
    engine reshaped the committed schedule against MID. Faint ghost bars are the
    DA commitment, so the gap to the solid bars is the volume the intraday rules
    settled financially (buyback / sellback) rather than physically moving the
    pack. Lines show realised DA against MID — the spread the intraday rules
    trade.
    """
    d = dispatch_df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    signed = d["mw"].where(d["action"] == "discharge", -d["mw"])
    d["signed_mw"] = signed.where(d["action"] != "idle", 0.0)
    mean_mw = d.groupby(d["timestamp"].dt.hour)["signed_mw"].mean()

    sched = da_sched_df.copy()
    sched["hod"] = pd.to_datetime(sched["timestamp"]).dt.hour
    da_commit = sched.groupby("hod")["da_mw"].mean()

    da_by_hour = prices_hourly.groupby(prices_hourly.index.hour)["day_ahead_price"].mean()
    mid_by_hour = prices_hourly.groupby(prices_hourly.index.hour)["mid_price"].mean()

    colors = ["#e74c3c" if v > 0 else "#2ecc71" for v in mean_mw.values]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=da_commit.index, y=da_commit.values, name="DA commitment (ghost)", yaxis="y2",
        marker_color="#999999", opacity=0.25,
    ))
    fig.add_trace(go.Bar(
        x=mean_mw.index, y=mean_mw.values, name="Mean realised dispatch MW", yaxis="y2",
        marker_color=colors, opacity=0.65,
    ))
    fig.add_trace(go.Scatter(
        x=da_by_hour.index, y=da_by_hour.values,
        name="Mean DA price (actual)", yaxis="y", line=dict(color="#1f77b4", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=mid_by_hour.index, y=mid_by_hour.values,
        name="Mean MID price", yaxis="y",
        line=dict(color="#9467bd", width=2),
    ))
    fig.update_layout(
        title="Realised Dispatch Shape — physical dispatch & execution price by hour",
        xaxis=dict(title="Hour of Day", dtick=1),
        yaxis=dict(title="Price (£/MWh)", side="left"),
        yaxis2=dict(
            title="Mean Dispatch (MW, + discharge / − charge)",
            side="right", overlaying="y", title_font=dict(color="#555"),
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
    fig.add_trace(go.Scatter(
        x=soc.index, y=soc.values * 100,
        mode="lines", name="SOC", line=dict(color="#1f77b4", width=1),
        fill="tozeroy", fillcolor="rgba(31,119,180,0.1)",
    ))
    fig.add_hline(
        y=initial_soc_pct * 100, line_dash="dash", line_color="grey",
        annotation_text=f"Initial SOC ({initial_soc_pct * 100:.0f}%)",
    )
    fig.add_hline(
        y=min_pct, line_dash="dot", line_color="#e74c3c",
        annotation_text=f"Min SOC ({min_pct:.0f}%)", annotation_position="bottom right",
    )
    fig.add_hline(
        y=max_pct, line_dash="dot", line_color="#e74c3c",
        annotation_text=f"Max SOC ({max_pct:.0f}%)", annotation_position="top right",
    )
    fig.update_layout(
        title="State of Charge — Selected Month",
        xaxis_title="Date", yaxis_title="SOC (%)",
        yaxis=dict(range=[max(0, min_pct - 10), min(105, max_pct + 10)]),
        template="plotly_white", height=350,
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

    # Build the trade tape. The DA leg is the day-ahead commitment itself (always
    # shown when da_mw != 0, regardless of how it was later resolved); the intraday
    # leg is the rule's trade, shown in its true buy/sell direction. Buy = ▲,
    # Sell = ▼; venue = colour (DA blue, Intraday/MID green).
    buy_da_x, buy_da_y, sell_da_x, sell_da_y = [], [], [], []
    buy_id_x, buy_id_y, sell_id_x, sell_id_y = [], [], [], []
    for _, row in dispatch.iterrows():
        ts = row["timestamp"]
        da_p = da_price_map.get(ts)
        mid_p = mid_map.get(ts)
        da_v = row["da_mw"]
        label = row["rule_label"]
        if da_p is not None:
            if da_v > 1e-6:         # committed to discharge → sold on DA
                sell_da_x.append(ts)
                sell_da_y.append(da_p)
            elif da_v < -1e-6:      # committed to charge → bought on DA
                buy_da_x.append(ts)
                buy_da_y.append(da_p)
        if mid_p is not None:
            if "Buy-Back" in label:          # bought the discharge back at MID
                buy_id_x.append(ts)
                buy_id_y.append(mid_p)
            elif "Sell-Back" in label:        # sold the charge back at MID
                sell_id_x.append(ts)
                sell_id_y.append(mid_p)
            spread = row.get("spread_mw", 0.0)  # Rule 4 physical extra at MID
            if spread > 1e-6:                # extra discharge sold at MID
                sell_id_x.append(ts)
                sell_id_y.append(mid_p)
            elif spread < -1e-6:             # extra charge bought at MID
                buy_id_x.append(ts)
                buy_id_y.append(mid_p)

    # Row 1 is a thin strip that only hosts the rangeslider. Its sole trace is
    # day-number text, so the slider band renders dates as its background and,
    # being row 1, the slider sits at the top of the figure.
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.095,
        subplot_titles=("", "Market Prices & Trades", "Traded Volume — DA vs Intraday", "State of Charge"),
        row_heights=[0.02, 0.327, 0.327, 0.326],
    )

    day_marks = pd.date_range(
        times.iloc[0].normalize(), times.iloc[-1].normalize(), freq="D"
    ) + pd.Timedelta(hours=12)
    fig.add_trace(go.Scatter(
        x=day_marks, y=[0] * len(day_marks),
        mode="text", text=[str(t.day) for t in day_marks],
        textfont=dict(size=10, color="#7f8c8d"),
        showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    # Strip y-range excludes the text (y=0) so it only appears inside the
    # rangeslider band, whose miniature autoranges to the data independently.
    fig.update_yaxes(visible=False, fixedrange=True, range=[5, 6], row=1, col=1)

    fig.add_trace(go.Scatter(
        x=prices_hourly.index, y=prices_hourly["day_ahead_price"].values,
        name="DA Price", line=dict(color="#1f77b4", width=2),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=da_price_pred.index, y=da_price_pred.values,
        name="DA Forecast", line=dict(color="#7fb3e0", width=1.2, dash="dash"),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=prices_hourly.index, y=prices_hourly["mid_price"].values,
        name="MID Price", line=dict(color="#27ae60", width=1.6),
    ), row=2, col=1)

    # Trade markers sit on the price line of the venue they executed on:
    # DA (blue) and Intraday/MID (green); ▲ = buy (charge), ▼ = sell (discharge).
    da_mk = dict(color="#1f3b6d", line=dict(width=0.5, color="white"))
    id_mk = dict(color="#1e8449", line=dict(width=0.5, color="white"))
    fig.add_trace(go.Scatter(
        x=buy_da_x, y=buy_da_y, mode="markers", name="Buy on DA",
        marker=dict(symbol="triangle-up", size=11, **da_mk),
        hovertemplate="Buy (charge) on DA @ £%{y:.1f}<extra></extra>",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=sell_da_x, y=sell_da_y, mode="markers", name="Sell on DA",
        marker=dict(symbol="triangle-down", size=11, **da_mk),
        hovertemplate="Sell (discharge) on DA @ £%{y:.1f}<extra></extra>",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=buy_id_x, y=buy_id_y, mode="markers", name="Buy on Intraday",
        marker=dict(symbol="triangle-up", size=11, **id_mk),
        hovertemplate="Buy-back on Intraday @ £%{y:.1f}<extra></extra>",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=sell_id_x, y=sell_id_y, mode="markers", name="Sell on Intraday",
        marker=dict(symbol="triangle-down", size=11, **id_mk),
        hovertemplate="Sell on Intraday @ £%{y:.1f}<extra></extra>",
    ), row=2, col=1)

    # How much, by venue, signed the same way as the markers (+ sell/discharge,
    # − buy/charge): the blue bar is the full DA commitment; the green bar is the
    # intraday trade in its true direction — a buyback shows below zero (a buy),
    # a sellback above zero (a sell).
    da_vol = dispatch["da_mw"].values
    intraday_vol = []
    for _, row in dispatch.iterrows():
        # Rule 2 netting (buyback −, sellback +) plus Rule 4's physical extra.
        v = row["netting_mw"] if abs(row["netting_mw"]) > 1e-6 else 0.0
        v += row.get("spread_mw", 0.0)  # Rule 4 physical extra (+ sell / − buy)
        intraday_vol.append(v)
    da_y = [v if abs(v) > 1e-6 else None for v in da_vol]
    id_y = [v if abs(v) > 1e-6 else None for v in intraday_vol]

    fig.add_trace(go.Bar(
        x=times, y=da_y, name="DA trade volume",
        marker_color="#1f77b4",
        hovertemplate="DA %{y:+.1f} MW<extra></extra>",
    ), row=3, col=1)
    fig.add_trace(go.Bar(
        x=times, y=id_y, name="Intraday trade volume",
        marker_color="#27ae60",
        hovertemplate="Intraday %{y:+.1f} MW<extra></extra>",
    ), row=3, col=1)

    fig.add_trace(go.Scatter(
        x=times, y=dispatch["soc_after"].values * 100,
        name="SOC", mode="lines",
        line=dict(color="#34495e", width=2),
        hovertemplate="SOC %{y:.1f}%<extra></extra>",
    ), row=4, col=1)
    fig.add_hline(
        y=min_soc_pct * 100, line_dash="dot", line_color="#e74c3c",
        annotation_text=f"Min SOC ({min_soc_pct * 100:.0f}%)",
        annotation_position="bottom right", row=4, col=1,
    )
    fig.add_hline(
        y=max_soc_pct * 100, line_dash="dot", line_color="#e74c3c",
        annotation_text=f"Max SOC ({max_soc_pct * 100:.0f}%)",
        annotation_position="top right", row=4, col=1,
    )

    # Open on the first simulated day; drag the date strip at the top to scroll
    window_start = times.iloc[0].normalize()
    window_end = window_start + pd.Timedelta(hours=24)
    fig.update_xaxes(range=[window_start.isoformat(), window_end.isoformat()])
    # rangemode "auto" lets the slider miniature autorange onto the date text,
    # which the strip itself keeps out of view via its [5, 6] y-range
    fig.update_xaxes(
        rangeslider=dict(visible=True, thickness=0.05, yaxis=dict(rangemode="auto")),
        row=1, col=1,
    )
    for ann in fig.layout.annotations:
        if ann.text == "Market Prices":
            ann.update(y=ann.y - 0.022)

    fig.update_yaxes(title_text="£/MWh", row=2, col=1)
    fig.update_yaxes(title_text="MW (+ discharge / − charge)", row=3, col=1)
    fig.update_yaxes(title_text="SOC (%)", range=[0, 105], row=4, col=1)
    fig.update_layout(
        template="plotly_white", height=850,
        legend=dict(x=0, y=1.05, orientation="h"),
        hovermode="x unified",
        barmode="relative",
        bargap=0.2,
    )
    return fig


def chart_pnl_waterfall(results_df: pd.DataFrame):
    """Trader's View PnL waterfall.

    DA revenue is split into the volume physically delivered against the day-ahead
    schedule and the financial spread captured by netting that schedule at MID
    (Rule 2 buyback/sellback). Physical intraday re-trading, imbalance settlement
    and degradation then bridge to the net result.
    """
    components = [
        ("Baseline DA Delivery", results_df["da_revenue_delivered"].sum()),
        ("Financial Spread", results_df["financial_spread_captured"].sum()),
        ("Physical Intraday", results_df["physical_dispatch_pnl"].sum()),
        ("Imbalance Penalty", results_df["imbalance_pnl"].sum()),
        ("Degradation", -results_df["degradation_cost"].sum()),
    ]
    net = sum(v for _, v in components)

    labels = [c[0] for c in components] + ["Net PnL"]
    values = [c[1] for c in components] + [net]
    measures = ["relative"] * len(components) + ["total"]

    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=measures,
        textposition="outside",
        text=[f"£{v:,.0f}" for v in values],
        increasing=dict(marker_color="#2ecc71"),
        decreasing=dict(marker_color="#e74c3c"),
        totals=dict(marker_color="#2ecc71" if net >= 0 else "#e74c3c"),
        connector_line_color="rgba(0,0,0,0)",
    ))
    fig.update_layout(
        title="PnL Waterfall — Trader's View",
        yaxis_title="£", template="plotly_white", height=450,
    )
    return fig


def chart_daily_attribution(results_df: pd.DataFrame):
    """Daily PnL attribution across the selected month.

    The waterfall shows *what* made the money over the whole month; this shows
    *when*. Each day stacks its positive returns above zero (DA delivery,
    financial spread, physical intraday, positive imbalance) and its costs below
    (degradation, negative imbalance) via barmode='relative', so you can see at a
    glance whether the month earned steadily or on a handful of volatile days.
    The black line is each day's net PnL.
    """
    df = results_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    x = df["date"]

    components = [
        ("Baseline DA", df["da_revenue_delivered"], "#1f77b4"),
        ("Financial Spread", df["financial_spread_captured"], "#2ecc71"),
        ("Physical Intraday", df["physical_dispatch_pnl"], "#9b59b6"),
        ("Imbalance", df["imbalance_pnl"], "#e67e22"),
        ("Degradation", -df["degradation_cost"], "#c0392b"),
    ]

    fig = go.Figure()
    for name, y, color in components:
        fig.add_trace(go.Bar(
            x=x, y=y, name=name, marker_color=color,
            hovertemplate="%{x|%d %b}<br>" + name + " £%{y:,.0f}<extra></extra>",
        ))
    fig.add_trace(go.Scatter(
        x=x, y=df["net_pnl"], name="Net PnL", mode="lines+markers",
        line=dict(color="#2c3e50", width=2), marker=dict(size=5),
        hovertemplate="%{x|%d %b}<br>Net £%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title="Daily PnL Attribution — selected month",
        xaxis_title="Date", yaxis_title="PnL (£)",
        barmode="relative", bargap=0.15,
        template="plotly_white", height=380,
        legend=dict(orientation="h", x=0, y=1.12),
        hovermode="x unified",
    )
    return fig
