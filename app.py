import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.bess.bess_asset import BESSAsset  # noqa: E402
from src.bess.da_optimizer import optimize_da_schedule  # noqa: E402
from src.bess.intraday_manager import run_intraday_session  # noqa: E402


def _naive_da_forecast(price_history, lookback=7, n_hours=24):
    window = price_history[-lookback:]
    forecast = []
    for h in range(n_hours):
        values = [day[h] for day in window if h < len(day)]
        if values:
            forecast.append(sum(values) / len(values))
        else:
            forecast.append(sum(price_history[-1]) / len(price_history[-1]))
    return forecast


st.set_page_config(page_title="Power Trading Dashboard", layout="wide")

PROCESSED_DATA = Path(os.environ.get("PT_PROCESSED_DATA", "data/processed/processed_data.parquet"))
CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "config.yaml"
CONFIG_FALLBACK_PATH = Path(__file__).resolve().parent / "configs" / "config.example.yaml"


def _load_config() -> dict:
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_FALLBACK_PATH
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ── Data loading (cached) ────────────────────────────────────────────────────

@st.cache_data
def load_prices() -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DATA)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    return df


def available_months(df: pd.DataFrame) -> list[str]:
    months = df.index.to_period("M").unique().sort_values()
    return [str(m) for m in months]


# ── BESS simulation ──────────────────────────────────────────────────────────

def run_bess_simulation(
    prices: pd.DataFrame,
    month_str: str,
    capacity_mwh: float,
    power_mw: float,
    degradation_cost: float,
    lookback_days: int,
    charge_efficiency: float = 0.94,
    discharge_efficiency: float = 0.94,
    initial_soc_pct: float = 0.50,
    min_soc_pct: float = 0.0,
    max_soc_pct: float = 1.0,
    target_daily_cycles: float | None = None,
    resolution_h: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    period = pd.Period(month_str, freq="M")
    start = period.start_time.tz_localize("UTC")
    end = period.end_time.tz_localize("UTC")
    month_df = prices.loc[start:end].copy()

    resample_freq = f"{int(resolution_h * 3600)}s"
    periods_per_day = int(24 / resolution_h)
    hourly = month_df[["day_ahead_price", "mid_price", "system_buy_price"]].resample(resample_freq).mean().dropna()

    bess_cfg = {
        "capacity_mwh": capacity_mwh,
        "power_mw": power_mw,
        "charge_efficiency": charge_efficiency,
        "discharge_efficiency": discharge_efficiency,
        "degradation_cost_per_mwh": degradation_cost,
        "initial_soc_pct": initial_soc_pct,
        "min_soc_pct": min_soc_pct,
        "max_soc_pct": max_soc_pct,
    }
    sim_cfg = {**bess_cfg, "resolution_h": resolution_h}

    daily_results = []
    all_dispatch_logs = []
    all_da_schedules = []
    price_history: list[list[float]] = []

    dst_delta = int(1 / resolution_h)
    valid_period_counts = {periods_per_day - dst_delta, periods_per_day, periods_per_day + dst_delta}

    for date, day_df in hourly.groupby(hourly.index.date):
        if len(day_df) not in valid_period_counts:
            continue

        asset = BESSAsset(**bess_cfg)
        da_prices = day_df["day_ahead_price"].tolist()
        if not price_history:
            price_history.append(da_prices)
            continue
        forecast = _naive_da_forecast(price_history, n_hours=len(day_df))
        schedule = optimize_da_schedule(
            forecast, asset, duration_h=resolution_h,
            target_daily_cycles=target_daily_cycles,
        )

        asset.reset()
        result = run_intraday_session(
            da_schedule=schedule,
            da_price_actual=da_prices,
            mid_prices=day_df["mid_price"].tolist(),
            imbalance_prices=day_df["system_buy_price"].tolist(),
            asset=asset,
            config=sim_cfg,
        )

        daily_results.append({
            "date": pd.Timestamp(date),
            "da_revenue": result["da_revenue"],
            "intraday_pnl": result["intraday_pnl"],
            "imbalance_pnl": result["imbalance_pnl"],
            "degradation_cost": result["total_degradation_cost"],
            "net_pnl": result["net_pnl"],
        })

        for entry in result["dispatch_log"]:
            entry["date"] = date
            entry["hour"] = entry["period"]
            entry["timestamp"] = day_df.index[entry["period"]]
        all_dispatch_logs.extend(result["dispatch_log"])

        for h, mw in enumerate(schedule):
            all_da_schedules.append({
                "date": date,
                "hour": h,
                "timestamp": day_df.index[h],
                "da_mw": mw,
            })
        price_history.append(da_prices)
        if len(price_history) > lookback_days:
            price_history.pop(0)

    results_df = pd.DataFrame(daily_results)
    dispatch_df = pd.DataFrame(all_dispatch_logs)
    da_sched_df = pd.DataFrame(all_da_schedules)

    return results_df, dispatch_df, da_sched_df


# ── BESS charts ───────────────────────────────────────────────────────────────

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
    sched_mw = sched.sort_values("timestamp").set_index("timestamp")["da_mw"]

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


# ── Main app ──────────────────────────────────────────────────────────────────

def main():
    st.title("BESS Dispatch Dashboard")
    render_bess(load_prices())


def render_bess(prices: pd.DataFrame):
    cfg = _load_config()
    bess_cfg = cfg.get("bess", {})

    months = available_months(prices)
    selected_month = st.sidebar.selectbox("Month", months, index=0)

    st.sidebar.markdown("### Asset Parameters")
    capacity = st.sidebar.slider("Battery Capacity (MWh)", 20, 500, 100, step=10)
    power = st.sidebar.slider("Max Power (MW)", 10, 200, 50, step=5)
    degradation = st.sidebar.slider("Degradation Cost (£/MWh)", 0.0, 30.0, 5.00, step=0.50)
    charge_eff = st.sidebar.slider("Charge Efficiency", 0.70, 1.00, 0.94, step=0.01)
    discharge_eff = st.sidebar.slider("Discharge Efficiency", 0.70, 1.00, 0.94, step=0.01)
    initial_soc = st.sidebar.slider("Initial SOC (%)", 0, 100, 50, step=5)

    st.sidebar.markdown("### SOC & Throughput Limits")
    default_min_soc = int(round(bess_cfg.get("min_soc_pct", 0.0) * 100))
    default_max_soc = int(round(bess_cfg.get("max_soc_pct", 1.0) * 100))
    min_soc, max_soc = st.sidebar.slider(
        "SOC Bounds (%)", 0, 100, (default_min_soc, default_max_soc), step=5,
    )
    _cfg_cycles = bess_cfg.get("target_daily_cycles")
    limit_cycles = st.sidebar.checkbox("Limit daily cycles", value=_cfg_cycles is not None)
    target_daily_cycles = None
    if limit_cycles:
        target_daily_cycles = st.sidebar.slider(
            "Target Daily Cycles", 0.5, 4.0,
            float(_cfg_cycles) if _cfg_cycles is not None else 1.5, step=0.5,
        )

    if st.sidebar.button("Run Simulation", type="primary"):
        lookback = bess_cfg.get("price_history_lookback_days", 7)
        resolution_h = bess_cfg.get("resolution_h", 1.0)
        with st.spinner("Running BESS simulation..."):
            results_df, dispatch_df, da_sched_df = run_bess_simulation(
                prices, selected_month, capacity, power, degradation,
                charge_efficiency=charge_eff,
                discharge_efficiency=discharge_eff,
                initial_soc_pct=initial_soc / 100.0,
                min_soc_pct=min_soc / 100.0,
                max_soc_pct=max_soc / 100.0,
                target_daily_cycles=target_daily_cycles,
                lookback_days=lookback,
                resolution_h=resolution_h,
            )

        if results_df.empty:
            st.error("No complete 24-hour days found in the selected month.")
            return

        st.session_state["bess_results"] = (
            results_df, dispatch_df, da_sched_df, selected_month, prices,
            {"min_soc_pct": min_soc / 100.0, "max_soc_pct": max_soc / 100.0,
             "initial_soc_pct": initial_soc / 100.0},
        )

    if "bess_results" not in st.session_state:
        st.info("Configure parameters and click **Run Simulation** to begin.")
        return

    results_df, dispatch_df, da_sched_df, month_str, cached_prices, soc_bounds = st.session_state["bess_results"]

    # KPI row
    total_da = results_df["da_revenue"].sum()
    total_intraday = results_df["intraday_pnl"].sum()
    total_imbalance = results_df["imbalance_pnl"].sum()
    total_degradation = results_df["degradation_cost"].sum()
    total_net = results_df["net_pnl"].sum()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("DA Revenue", f"£{total_da:,.0f}")
    k2.metric("Intraday PnL", f"£{total_intraday:,.0f}")
    k3.metric("Imbalance Penalty", f"£{total_imbalance:,.0f}")
    k4.metric("Degradation Cost", f"£{total_degradation:,.0f}")
    k5.metric("Net PnL", f"£{total_net:,.0f}")

    # Pick sample day: highest DA spread
    period = pd.Period(month_str, freq="M")
    start = period.start_time.tz_localize("UTC")
    end = period.end_time.tz_localize("UTC")
    hourly = (
        cached_prices.loc[start:end, ["day_ahead_price", "mid_price", "system_buy_price"]]
        .resample("1h").mean().dropna()
    )
    valid_dates = set(da_sched_df["date"].unique())
    valid_hourly = hourly[[d in valid_dates for d in hourly.index.date]]
    daily_spread = valid_hourly.groupby(valid_hourly.index.date)["day_ahead_price"].apply(
        lambda x: x.max() - x.min()
    )
    if daily_spread.empty:
        st.warning("No valid price data for the selected month.")
        return
    sample_date = daily_spread.idxmax()

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            chart_price_dispatch(hourly, da_sched_df, sample_date),
            use_container_width=True,
        )
    with col2:
        st.plotly_chart(
            chart_soc_tracker(
                dispatch_df,
                min_soc_pct=soc_bounds["min_soc_pct"],
                max_soc_pct=soc_bounds["max_soc_pct"],
                initial_soc_pct=soc_bounds["initial_soc_pct"],
            ),
            use_container_width=True,
        )

    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(
            chart_rebalancing(dispatch_df, da_sched_df, sample_date),
            use_container_width=True,
        )
    with col4:
        st.plotly_chart(chart_pnl_waterfall(results_df), use_container_width=True)

    # Operation explorer: a 24-hour viewport dragged across the month via the date strip
    st.markdown("---")
    st.subheader("Dispatch Explorer")
    st.caption(
        "Drag the date strip at the top of the chart to scroll through the month, or "
        "stretch its handles to view any time span (it opens on the first day). All three "
        "panels move together: market prices (top), the LP day-ahead plan versus what was "
        "actually dispatched (middle), and the resulting state of charge (bottom). Hover "
        "any hour to see the decision taken."
    )
    st.plotly_chart(
        chart_operation_explorer(
            hourly, dispatch_df, da_sched_df,
            min_soc_pct=soc_bounds["min_soc_pct"],
            max_soc_pct=soc_bounds["max_soc_pct"],
        ),
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
