import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
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
VIRTUAL_PNL = Path(os.environ.get("PT_VIRTUAL_PNL", "artifacts/da_imbalance/xgb_wf_v1/trading/pnl.csv"))
VIRTUAL_SIGNALS = Path(os.environ.get("PT_VIRTUAL_SIGNALS", "artifacts/da_imbalance/xgb_wf_v1/trading/signals.csv"))
VIRTUAL_PREDICTIONS = Path(
    os.environ.get("PT_VIRTUAL_PREDICTIONS", "artifacts/da_imbalance/xgb_wf_v1/trading/predictions.csv")
)
CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "config.yaml"


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


# ── Data loading (cached) ────────────────────────────────────────────────────

@st.cache_data
def load_prices() -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DATA)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    return df


@st.cache_data
def load_virtual_artifacts() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pnl = pd.read_csv(VIRTUAL_PNL)
    pnl["time"] = pd.to_datetime(pnl["time"], utc=True)

    signals = pd.read_csv(VIRTUAL_SIGNALS)
    signals["delivery_time"] = pd.to_datetime(signals["delivery_time"], utc=True)

    predictions = pd.read_csv(VIRTUAL_PREDICTIONS)
    predictions["time"] = pd.to_datetime(predictions["time"], utc=True)

    return pnl, signals, predictions


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
    charge_efficiency: float = 0.88,
    discharge_efficiency: float = 1.0,
    initial_soc_pct: float = 0.50,
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
        schedule = optimize_da_schedule(forecast, asset, duration_h=resolution_h)

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


def chart_soc_tracker(dispatch_df: pd.DataFrame):
    dispatch_df = dispatch_df.copy()
    dispatch_df["timestamp"] = pd.to_datetime(dispatch_df["timestamp"])
    soc = dispatch_df.set_index("timestamp")["soc_after"].sort_index()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=soc.index, y=soc.values * 100,
        mode="lines", name="SOC", line=dict(color="#1f77b4", width=1),
        fill="tozeroy", fillcolor="rgba(31,119,180,0.1)",
    ))
    fig.add_hline(y=50, line_dash="dash", line_color="grey", annotation_text="Initial SOC (50%)")
    fig.update_layout(
        title="State of Charge — Selected Month",
        xaxis_title="Date", yaxis_title="SOC (%)",
        yaxis=dict(range=[0, 105]),
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


# ── Virtual Trading charts ────────────────────────────────────────────────────

def chart_virtual_cumulative_pnl(pnl_df: pd.DataFrame):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pnl_df["time"], y=pnl_df["cumulative_pnl"],
        mode="lines", name="Cumulative PnL",
        line=dict(color="#1f77b4", width=2),
        fill="tozeroy", fillcolor="rgba(31,119,180,0.1)",
    ))
    fig.update_layout(
        title="Cumulative PnL — Virtual Trading",
        xaxis_title="Date", yaxis_title="£",
        template="plotly_white", height=400,
    )
    return fig


def chart_virtual_signal_distribution(signals_df: pd.DataFrame):
    counts = signals_df["direction"].value_counts()
    colors = {"BUY": "#2ecc71", "SELL": "#e74c3c", "NEUTRAL": "#95a5a6"}
    fig = go.Figure(go.Bar(
        x=counts.index.tolist(),
        y=counts.values,
        marker_color=[colors.get(d, "#999") for d in counts.index],
    ))
    fig.update_layout(
        title="Signal Distribution",
        xaxis_title="Direction", yaxis_title="Count",
        template="plotly_white", height=350,
    )
    return fig


def chart_virtual_daily_pnl(pnl_df: pd.DataFrame):
    daily = pnl_df.set_index("time").resample("1D")["pnl"].sum().reset_index()
    daily = daily[daily["pnl"] != 0]
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in daily["pnl"]]
    fig = go.Figure(go.Bar(
        x=daily["time"], y=daily["pnl"], marker_color=colors,
    ))
    fig.update_layout(
        title="Daily PnL — Virtual Trading",
        xaxis_title="Date", yaxis_title="£",
        template="plotly_white", height=350,
    )
    return fig


def chart_virtual_spread_scatter(predictions_df: pd.DataFrame):
    fig = go.Figure()
    fig.add_trace(go.Scattergl(
        x=predictions_df["predicted_spread"],
        y=predictions_df["actual_spread"],
        mode="markers",
        marker=dict(size=3, color="#1f77b4", opacity=0.4),
        name="Periods",
    ))
    spread_range = [
        min(predictions_df["predicted_spread"].min(), predictions_df["actual_spread"].min()),
        max(predictions_df["predicted_spread"].max(), predictions_df["actual_spread"].max()),
    ]
    fig.add_trace(go.Scatter(
        x=spread_range, y=spread_range,
        mode="lines", line=dict(color="grey", dash="dash", width=1),
        name="Perfect forecast",
    ))
    fig.update_layout(
        title="Predicted vs Actual Spread",
        xaxis_title="Predicted Spread (£/MWh)",
        yaxis_title="Actual Spread (£/MWh)",
        template="plotly_white", height=400,
    )
    return fig


# ── Main app ──────────────────────────────────────────────────────────────────

def main():
    st.title("Power Trading Dashboard")

    prices = load_prices()

    strategy = st.sidebar.selectbox(
        "Strategy",
        ["Phase 3: Physical BESS", "Phase 2: Virtual Trading"],
    )

    if strategy == "Phase 3: Physical BESS":
        render_bess(prices)
    else:
        render_virtual(prices)


def render_bess(prices: pd.DataFrame):
    months = available_months(prices)
    selected_month = st.sidebar.selectbox("Month", months, index=0)

    st.sidebar.markdown("### Asset Parameters")
    capacity = st.sidebar.slider("Battery Capacity (MWh)", 20, 500, 100, step=10)
    power = st.sidebar.slider("Max Power (MW)", 10, 200, 50, step=5)
    degradation = st.sidebar.slider("Degradation Cost (£/MWh)", 0.0, 30.0, 8.50, step=0.50)
    charge_eff = st.sidebar.slider("Charge Efficiency", 0.70, 1.00, 0.88, step=0.01)
    discharge_eff = st.sidebar.slider("Discharge Efficiency", 0.70, 1.00, 1.00, step=0.01)
    initial_soc = st.sidebar.slider("Initial SOC (%)", 0, 100, 50, step=5)

    if st.sidebar.button("Run Simulation", type="primary"):
        cfg = _load_config()
        bess_cfg = cfg["bess"]
        lookback = bess_cfg["price_history_lookback_days"]
        resolution_h = bess_cfg.get("resolution_h", 1.0)
        with st.spinner("Running BESS simulation..."):
            results_df, dispatch_df, da_sched_df = run_bess_simulation(
                prices, selected_month, capacity, power, degradation,
                charge_efficiency=charge_eff,
                discharge_efficiency=discharge_eff,
                initial_soc_pct=initial_soc / 100.0,
                lookback_days=lookback,
                resolution_h=resolution_h,
            )

        if results_df.empty:
            st.error("No complete 24-hour days found in the selected month.")
            return

        st.session_state["bess_results"] = (results_df, dispatch_df, da_sched_df, selected_month, prices)

    if "bess_results" not in st.session_state:
        st.info("Configure parameters and click **Run Simulation** to begin.")
        return

    results_df, dispatch_df, da_sched_df, month_str, cached_prices = st.session_state["bess_results"]

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
    hourly = cached_prices.loc[start:end, ["day_ahead_price"]].resample("1h").mean().dropna()
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
            chart_price_dispatch(
                cached_prices.loc[start:end, ["day_ahead_price"]].resample("1h").mean().dropna(),
                da_sched_df, sample_date,
            ),
            use_container_width=True,
        )
    with col2:
        st.plotly_chart(chart_soc_tracker(dispatch_df), use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(
            chart_rebalancing(dispatch_df, da_sched_df, sample_date),
            use_container_width=True,
        )
    with col4:
        st.plotly_chart(chart_pnl_waterfall(results_df), use_container_width=True)


def render_virtual(prices: pd.DataFrame):
    if not VIRTUAL_PNL.exists():
        st.error("Virtual trading artifacts not found. Run the pipeline first.")
        return

    pnl_raw, signals_raw, predictions_raw = load_virtual_artifacts()

    # Determine available months from the PnL data
    pnl_raw["_period"] = pnl_raw["time"].dt.to_period("M")
    avail = sorted(pnl_raw["_period"].unique(), key=str)
    month_labels = [str(m) for m in avail]
    selected_month = st.sidebar.selectbox("Month", month_labels, index=0)

    if st.sidebar.button("Run Simulation", type="primary"):
        st.session_state["virtual_month"] = selected_month

    month = st.session_state.get("virtual_month", selected_month)
    period = pd.Period(month, freq="M")

    # Filter to selected month
    pnl_df = pnl_raw[pnl_raw["_period"] == period].copy()
    pnl_df["cumulative_pnl"] = pnl_df["pnl"].cumsum()

    signals_df = signals_raw[
        signals_raw["delivery_time"].dt.to_period("M") == period
    ].copy()

    predictions_df = predictions_raw[
        predictions_raw["time"].dt.to_period("M") == period
    ].copy()

    if pnl_df.empty:
        st.warning("No virtual trading data available for the selected month.")
        return

    # KPIs
    total_pnl = pnl_df["pnl"].sum()
    n_trades = int((signals_df["signal"] != 0).sum())
    win_periods = int((pnl_df["pnl"] > 0).sum())
    loss_periods = int((pnl_df["pnl"] < 0).sum())
    win_rate = win_periods / max(win_periods + loss_periods, 1) * 100

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Net PnL", f"£{total_pnl:,.0f}")
    k2.metric("Active Trades", f"{n_trades}")
    k3.metric("Win Rate", f"{win_rate:.1f}%")
    k4.metric("Best Day", f"£{pnl_df.set_index('time').resample('1D')['pnl'].sum().max():,.0f}")

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(chart_virtual_cumulative_pnl(pnl_df), use_container_width=True)
    with col2:
        st.plotly_chart(chart_virtual_signal_distribution(signals_df), use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(chart_virtual_daily_pnl(pnl_df), use_container_width=True)
    with col4:
        st.plotly_chart(chart_virtual_spread_scatter(predictions_df), use_container_width=True)


if __name__ == "__main__":
    main()
