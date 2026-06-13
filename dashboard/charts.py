"""Plotly chart builders for the BESS dispatch dashboard (dashboard/app.py).

Each function takes already-sliced simulation frames and returns a Plotly
figure; they hold no Streamlit or data-loading logic so they can be reused and
tested in isolation.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def chart_price_dispatch(prices_hourly: pd.DataFrame, da_sched_df: pd.DataFrame, sample_date):
    day_prices = prices_hourly.loc[prices_hourly.index.date == sample_date]
    day_sched = da_sched_df[da_sched_df["date"] == sample_date]
    hours = list(range(24))
    da_mw = day_sched["da_mw"].values

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hours, y=day_prices["day_ahead_price"].values,
        name="DA Price", yaxis="y", line=dict(color="#1f77b4", width=2),
    ))

    colors = ["#e74c3c" if mw > 0 else "#2ecc71" for mw in da_mw]
    fig.add_trace(go.Bar(
        x=hours, y=da_mw, name="Dispatch MW", yaxis="y2",
        marker_color=colors, opacity=0.6,
    ))

    fig.update_layout(
        title=f"Price & Dispatch Overlay — {sample_date}",
        xaxis=dict(title="Hour of Day", dtick=1),
        yaxis=dict(title="DA Price (£/MWh)", side="left", title_font=dict(color="#1f77b4")),
        yaxis2=dict(title="Dispatch (MW)", side="right", overlaying="y", title_font=dict(color="#555")),
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


def chart_rebalancing(dispatch_df: pd.DataFrame, da_sched_df: pd.DataFrame, sample_date):
    day_sched = da_sched_df[da_sched_df["date"] == sample_date].sort_values("hour")
    day_dispatch = dispatch_df[dispatch_df["date"] == sample_date].sort_values("hour")
    hours = list(range(24))

    da_mw = day_sched["da_mw"].values
    actual_mw = []
    for _, row in day_dispatch.iterrows():
        if row["action"] == "discharge":
            actual_mw.append(row["mw"])
        elif row["action"] == "charge":
            actual_mw.append(-row["mw"])
        else:
            actual_mw.append(0.0)
    actual_mw_arr = np.array(actual_mw)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hours, y=da_mw, name="DA Schedule (LP)",
        line=dict(color="#1f77b4", width=2, shape="hvh"),
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=actual_mw_arr, name="Final Dispatch",
        line=dict(color="#e74c3c", width=2, dash="dash", shape="hvh"),
    ))
    fig.update_layout(
        title=f"Rebalancing Impact — {sample_date}",
        xaxis=dict(title="Hour of Day", dtick=1),
        yaxis_title="MW (+ discharge / − charge)",
        template="plotly_white", height=400,
        legend=dict(x=0, y=1.12, orientation="h"),
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
    sched_mw = sched["da_mw"]
    da_price_pred = sched["da_price_pred"]

    actual_mw = []
    decisions = []
    for _, row in dispatch.iterrows():
        scheduled = sched_mw.get(row["timestamp"], 0.0)
        if row["action"] == "discharge":
            signed = row["mw"]
            text = f"Discharge {row['mw']:.1f} MW @ £{row['price']:.2f}/MWh"
        elif row["action"] == "charge":
            signed = -row["mw"]
            text = f"Charge {row['mw']:.1f} MW @ £{row['price']:.2f}/MWh"
        else:
            signed = 0.0
            text = "Idle — no DA position"
        if row["action"] != "idle" and abs(scheduled) - abs(signed) > 1e-6:
            text += f"<br>Curtailed from {abs(scheduled):.1f} MW scheduled (SOC/power limit)"
        actual_mw.append(signed)
        decisions.append(text)

    bar_colors = ["#e74c3c" if mw > 0 else "#2ecc71" if mw < 0 else "#bdc3c7" for mw in actual_mw]
    times = dispatch["timestamp"]

    # Row 1 is a thin strip that only hosts the rangeslider. Its sole trace is
    # day-number text, so the slider band renders dates as its background and,
    # being row 1, the slider sits at the top of the figure.
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.095,
        subplot_titles=("", "Market Prices", "Dispatch Decisions", "State of Charge"),
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
        name="DA Forecast (pred)", line=dict(color="#7fb3e0", width=1.5, dash="dash"),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=prices_hourly.index, y=prices_hourly["mid_price"].values,
        name="MID Price", line=dict(color="#f39c12", width=1.5),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=prices_hourly.index, y=prices_hourly["system_buy_price"].values,
        name="Imbalance (SBP)", line=dict(color="#95a5a6", width=1, dash="dot"),
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=sched_mw.index, y=sched_mw.values, name="DA Schedule (LP)",
        line=dict(color="#1f77b4", width=2, shape="hvh"),
    ), row=3, col=1)
    fig.add_trace(go.Bar(
        x=times, y=actual_mw, name="Final Dispatch",
        marker_color=bar_colors, opacity=0.7,
        width=3600 * 1000 * 0.7,  # bar width in ms: 70% of an hour
        customdata=decisions,
        hovertemplate="%{x|%d %b %H:%M}<br>%{customdata}<extra></extra>",
    ), row=3, col=1)

    fig.add_trace(go.Scatter(
        x=times, y=dispatch["soc_after"].values * 100,
        name="SOC", mode="lines+markers",
        line=dict(color="#8e44ad", width=2),
        marker=dict(size=5, color=bar_colors),
        customdata=decisions,
        hovertemplate="%{x|%d %b %H:%M}<br>SOC %{y:.1f}%<br>%{customdata}<extra></extra>",
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
        bargap=0,
    )
    return fig


def chart_pnl_waterfall(results_df: pd.DataFrame):
    components = [
        ("DA Revenue", results_df["da_revenue"].sum()),
        ("Intraday PnL", results_df["intraday_pnl"].sum()),
        ("Imbalance PnL", results_df["imbalance_pnl"].sum()),
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
        totals=dict(marker_color="#3498db"),
        connector_line_color="rgba(0,0,0,0)",
    ))
    fig.update_layout(
        title="PnL Waterfall — BESS Strategy",
        yaxis_title="£", template="plotly_white", height=450,
    )
    return fig
