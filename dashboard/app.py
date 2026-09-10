"""Streamlit dashboard for debugging the BESS dispatch model.

The pipeline only persists aggregate BESS results (daily PnL and summary
metrics), which show how much the battery earned but not why it acted as it
did. This app closes that gap: it faithfully replays the same strategy the
pipeline runs — the walk-forward ML day-ahead forecast, the LP schedule, and
the rolling intraday re-optimisation (against the DA-proxy MID) with continuous
state-of-charge carry-over — and surfaces the per-hour decision trail (prices,
schedule vs. actual dispatch, SOC) so the model's behaviour can be inspected.

Run with ``make dashboard`` or ``streamlit run dashboard/app.py``.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.bess.bess_asset import BESSAsset  # noqa: E402
from src.bess.da_optimizer import optimize_da_schedule  # noqa: E402
from src.bess.intraday_manager import run_intraday_session  # noqa: E402
from src.data.market_calendar import complete_resample, market_day_grid  # noqa: E402

from dashboard.charts import (  # noqa: E402
    chart_da_commitment_shape,
    chart_daily_attribution,
    chart_operation_explorer,
    chart_pnl_waterfall,
    chart_realized_shape,
    chart_soc_tracker,
)

st.set_page_config(page_title="Power Trading Dashboard", layout="wide")

PROCESSED_DATA = Path(
    os.environ.get("PT_PROCESSED_DATA", PROJECT_ROOT / "data/processed/processed_data.parquet")
)
CONFIG_PATH = PROJECT_ROOT / "configs" / "config.yaml"
CONFIG_FALLBACK_PATH = PROJECT_ROOT / "configs" / "config.example.yaml"


def _load_config() -> dict:
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_FALLBACK_PATH
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ── Data loading (cached) ────────────────────────────────────────────────────


@st.cache_data(ttl=900)
def load_prices() -> pd.DataFrame:
    import json

    if os.environ.get("PT_PROCESSED_DATA"):
        df = pd.read_parquet(PROCESSED_DATA)
    else:
        manifest = PROJECT_ROOT / "artifacts/da_positioning/best_run.json"
        run = json.loads(manifest.read_text())["best_run"]
        df = pd.read_csv(
            PROJECT_ROOT / "artifacts/da_positioning" / run / "bess/trading/dispatch_prices.csv"
        )
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    return df


@st.cache_data(show_spinner="Loading the selected fold forecasts…", ttl=900)
def load_da_price_forecast(model_cfg: dict, val_cfg: dict) -> pd.Series:
    """The exact day-ahead price forecast the BESS pipeline schedules against.

    Reads the selected run's persisted fold forecasts. Missing artifacts fail
    explicitly rather than rebuilding from a potentially stale processed cache.
    """
    import json

    manifest = PROJECT_ROOT / "artifacts/da_positioning/best_run.json"
    if not manifest.exists():
        raise FileNotFoundError(
            "Run notebook 01, then the BESS pipeline, before opening the replay."
        )
    run = json.loads(manifest.read_text())["best_run"]
    artifact = PROJECT_ROOT / "artifacts/da_positioning" / run / "bess/trading/da_forecast.csv"
    if not artifact.exists():
        raise FileNotFoundError(f"Missing fold forecast: {artifact}. Run main.py --mode bess.")
    predictions_df = pd.read_csv(artifact)

    # The walk-forward predictions *are* the forecast. Keeping only the dates
    # they cover and then re-scoring those dates with `da_model` — the single
    # last-fitted estimator — hands most of the window to a model that trained
    # on it. This is a replay of a backtest, so it has to replay the fold that
    # actually produced each prediction.
    forecast = (
        predictions_df.assign(time=pd.to_datetime(predictions_df["time"], utc=True))
        .set_index("time")["predicted_da_price"]
        .astype(float)
        .sort_index()
    )
    forecast.index.name = "time"
    return forecast


def available_months(forecast: pd.Series) -> list[str]:
    """Months the dashboard can simulate — only those with out-of-sample
    forecast coverage, since the LP schedules against the ML prediction."""
    months = forecast.index.to_period("M").unique().sort_values()
    return [str(m) for m in months]


def _slice_month(df: pd.DataFrame, period: pd.Period) -> pd.DataFrame:
    """Filter a per-day or per-period frame (with a ``date`` column) to one month."""
    if df.empty:
        return df
    return df[pd.to_datetime(df["date"]).dt.to_period("M") == period]


# ── BESS simulation ──────────────────────────────────────────────────────────


@st.cache_data(show_spinner="Running BESS research replay…", ttl=900)
def run_bess_simulation(
    capacity_mwh: float,
    power_mw: float,
    degradation_cost: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    initial_soc_pct: float,
    min_soc_pct: float,
    max_soc_pct: float,
    target_daily_cycles: float | None,
    resolution_h: float,
    soc_drift_tolerance: float,
    slippage: float = 2.00,
    margin_buy: float = 0.0,
    margin_sell: float = 0.0,
    commit_fraction: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Replay the BESS strategy exactly as pipeline._run_bess_pipeline does.

    One asset, one continuous SOC chain across every out-of-sample day: each
    day starts from the previous day's *actual* ending SOC (the first from
    ``initial_soc_pct``), the LP schedules against the ML forecast, the intraday
    engine re-optimises the physical schedule deciding on the DA-proxy MID
    (cleared DA price ± the basis) and settling the deviations at the real MID,
    and any residual shortfall uses SBP (short) / SSP (long). Cached on the asset
    parameters so toggling the month only re-slices; changing a slider re-runs.
    Covers the full OOS range — callers slice the month they want.
    """
    prices = load_prices()
    cfg = _load_config()
    da_forecast = load_da_price_forecast(cfg.get("model", {}), cfg.get("validation", {}))

    combined = prices[["day_ahead_price", "mid_price"]].copy()
    combined["da_price_pred"] = da_forecast.reindex(combined.index)

    resample_freq = f"{int(resolution_h * 3600)}s"
    hourly = complete_resample(combined, resample_freq).dropna(
        subset=["day_ahead_price", "mid_price"]
    )

    asset_kwargs = {
        "capacity_mwh": capacity_mwh,
        "power_mw": power_mw,
        "charge_efficiency": charge_efficiency,
        "discharge_efficiency": discharge_efficiency,
        "degradation_cost_per_mwh": degradation_cost,
        "initial_soc_pct": initial_soc_pct,
        "min_soc_pct": min_soc_pct,
        "max_soc_pct": max_soc_pct,
    }
    sim_cfg = {
        "degradation_cost_per_mwh": degradation_cost,
        "resolution_h": resolution_h,
        "soc_drift_tolerance": soc_drift_tolerance,
        # The intraday engine reads target_daily_cycles from its config to freeze
        # the physical envelope once intraday throughput exhausts the daily budget.
        # Without this passthrough the cycle cap never engaged intraday, even with
        # "Limit daily cycles" set (the LP got it directly via optimize_da_schedule).
        "target_daily_cycles": target_daily_cycles,
        # Netting hurdles and the per-MWh execution-cost buffer, mirroring the
        # pipeline config so the dashboard replays the exact intraday economics.
        "margin_buy": margin_buy,
        "margin_sell": margin_sell,
        "execution": {"slippage": slippage},
    }

    daily_results = []
    all_dispatch_logs = []
    all_da_schedules = []

    asset = BESSAsset(**asset_kwargs)
    prev_soc_pct: float | None = None

    for date, day_df in hourly.groupby(hourly.index.tz_convert("Europe/London").date):
        if not day_df.index.equals(market_day_grid(date, resample_freq)):
            continue

        forecast = day_df["da_price_pred"].tolist()
        if any(pd.isna(forecast)):
            continue  # no ML forecast for this day — outside OOS coverage

        carry_soc = prev_soc_pct if prev_soc_pct is not None else initial_soc_pct
        carry_soc = min(max(carry_soc, min_soc_pct), max_soc_pct)
        asset.reset(soc_pct=carry_soc)

        da_prices = day_df["day_ahead_price"].tolist()
        schedule = optimize_da_schedule(
            forecast,
            asset,
            duration_h=resolution_h,
            target_daily_cycles=target_daily_cycles,
            commit_fraction=commit_fraction,
        )
        if len(schedule) != len(forecast):
            raise ValueError(
                f"Day-ahead schedule length {len(schedule)} does not match "
                f"forecast length {len(forecast)} for {date}. This indicates an "
                f"upstream data problem; refusing to continue with incomplete data."
            )
        result = run_intraday_session(
            da_schedule=schedule,
            da_price_actual=da_prices,
            mid_prices=day_df["mid_price"].tolist(),
            asset=asset,
            config=sim_cfg,
        )
        prev_soc_pct = asset.soc_pct

        daily_results.append(
            {
                "date": pd.Timestamp(date),
                "cycles_saved_mwh": result["cycles_saved_mwh"],
                "degradation_cost": result["total_degradation_cost"],
                "benchmark_da_revenue": result["benchmark_da_revenue"],
                "intraday_da_improvement": result["intraday_da_improvement"],
                "execution_costs_paid": result["execution_costs_paid"],
                "net_pnl": result["net_pnl"],
            }
        )

        for entry in result["dispatch_log"]:
            entry["date"] = date
            entry["hour"] = entry["period"]
            entry["timestamp"] = day_df.index[entry["period"]]
        all_dispatch_logs.extend(result["dispatch_log"])

        for h, mw in enumerate(schedule):
            all_da_schedules.append(
                {
                    "date": date,
                    "hour": h,
                    "timestamp": day_df.index[h],
                    "da_mw": mw,
                    "da_price_pred": forecast[h],
                }
            )

    results_df = pd.DataFrame(daily_results)
    dispatch_df = pd.DataFrame(all_dispatch_logs)
    da_sched_df = pd.DataFrame(all_da_schedules)

    return results_df, dispatch_df, da_sched_df


# ── Main app ──────────────────────────────────────────────────────────────────


def main():
    st.title("BESS Dispatch Dashboard")
    render_bess(load_prices())


def render_bess(prices: pd.DataFrame):
    cfg = _load_config()
    bess_cfg = cfg.get("bess", {})

    da_forecast = load_da_price_forecast(cfg.get("model", {}), cfg.get("validation", {}))
    months = available_months(da_forecast)
    if not months:
        st.error("No out-of-sample forecast available. Check the model/validation config.")
        return
    selected_month = st.sidebar.selectbox("Month", months, index=0)
    st.sidebar.caption("Months are limited to the model's out-of-sample (walk-forward) range.")

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
        "SOC Bounds (%)",
        0,
        100,
        (default_min_soc, default_max_soc),
        step=5,
    )
    _cfg_cycles = bess_cfg.get("target_daily_cycles")
    limit_cycles = st.sidebar.checkbox("Limit daily cycles", value=_cfg_cycles is not None)
    target_daily_cycles = None
    if limit_cycles:
        target_daily_cycles = st.sidebar.slider(
            "Target Daily Cycles",
            0.5,
            4.0,
            float(_cfg_cycles) if _cfg_cycles is not None else 1.5,
            step=0.5,
        )

    st.sidebar.markdown("### Market Allocation")
    commit_pct = st.sidebar.slider(
        "DA Commitment (%)",
        0,
        100,
        int(round(bess_cfg.get("da_commit_fraction", 1.0) * 100)),
        step=5,
        help="Share of the battery's power and of its daily cycle budget the "
        "day-ahead auction may commit (100% = greedy all-in bid). The "
        "held-back share of both stays free for the intraday stage — it can "
        "chase MID without first unwinding a DA position and paying slippage "
        "on the unwind.",
    )

    st.sidebar.markdown("### Intraday Re-optimisation Levers")
    basis_margin = st.sidebar.slider(
        "MID-Proxy Basis (£/MWh)",
        0.0,
        50.0,
        float(bess_cfg.get("margin_buy", 0.0)),
        step=1.0,
        help="The DA→MID basis used to proxy the (unobservable) intraday MID from "
        "the cleared DA price: discharge clears at DA − basis, charge at DA + "
        "basis. It is the hurdle a deviation must beat — higher = the LP "
        "deviates from the locked DA plan less often.",
    )
    slippage = st.sidebar.slider(
        "Execution Buffer / Slippage (£/MWh)",
        0.0,
        10.0,
        float(cfg.get("execution", {}).get("slippage", 2.00)),
        step=0.50,
        help="Per-MWh execution cost charged on every deviated MWh, and an extra "
        "hurdle in the re-optimisation objective, so a higher buffer makes the "
        "engine deviate from the DA plan less often.",
    )

    # The simulation runs over the whole out-of-sample period and is cached on
    # the asset parameters: changing a slider re-runs it, switching month just
    # re-slices the cached result below.
    full_results, full_dispatch, full_sched = run_bess_simulation(
        capacity_mwh=capacity,
        power_mw=power,
        degradation_cost=degradation,
        charge_efficiency=charge_eff,
        discharge_efficiency=discharge_eff,
        initial_soc_pct=initial_soc / 100.0,
        min_soc_pct=min_soc / 100.0,
        max_soc_pct=max_soc / 100.0,
        target_daily_cycles=target_daily_cycles,
        resolution_h=bess_cfg.get("resolution_h", 1.0),
        soc_drift_tolerance=bess_cfg.get("soc_drift_tolerance", 0.05),
        slippage=slippage,
        margin_buy=basis_margin,
        margin_sell=basis_margin,
        commit_fraction=commit_pct / 100.0,
    )

    soc_bounds = {
        "min_soc_pct": min_soc / 100.0,
        "max_soc_pct": max_soc / 100.0,
        "initial_soc_pct": initial_soc / 100.0,
    }

    month_period = pd.Period(selected_month, freq="M")
    results_df = _slice_month(full_results, month_period)
    dispatch_df = _slice_month(full_dispatch, month_period)
    da_sched_df = _slice_month(full_sched, month_period)
    month_str = selected_month

    if results_df.empty:
        st.warning("No out-of-sample days fall in the selected month.")
        return

    # KPI row — Trader's ledger view: frozen DA benchmark, the consolidated
    # intraday improvement, then execution friction and the cost buckets.
    total_benchmark = results_df["benchmark_da_revenue"].sum()
    total_intraday = results_df["intraday_da_improvement"].sum()
    total_execution = results_df["execution_costs_paid"].sum()
    total_degradation = results_df["degradation_cost"].sum()
    total_net = results_df["net_pnl"].sum()
    total_cycles_saved = results_df["cycles_saved_mwh"].sum()

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("DA Benchmark", f"£{total_benchmark:,.0f}")
    k2.metric("Intraday DA Improvement", f"£{total_intraday:,.0f}")
    k3.metric("Execution Friction", f"-£{total_execution:,.0f}")
    k4.metric("Degradation Cost", f"£{total_degradation:,.0f}")
    k5.metric("Net PnL", f"£{total_net:,.0f}")
    k6.metric("Wear Avoided", f"{total_cycles_saved:,.0f} MWh")

    period = pd.Period(month_str, freq="M")
    start = period.start_time.tz_localize("UTC")
    end = period.end_time.tz_localize("UTC")
    hourly = (
        prices.loc[start:end, ["day_ahead_price", "mid_price", "system_buy_price"]]
        .resample("1h")
        .mean()
        .dropna()
    )
    if hourly.empty:
        st.warning("No valid price data for the selected month.")
        return

    top_left, top_right = st.columns(2)
    with top_left:
        st.plotly_chart(
            chart_realized_shape(dispatch_df, hourly, da_sched_df),
            use_container_width=True,
            key=f"realized_shape_{month_str}",
        )
    with top_right:
        st.plotly_chart(
            chart_soc_tracker(
                dispatch_df,
                min_soc_pct=soc_bounds["min_soc_pct"],
                max_soc_pct=soc_bounds["max_soc_pct"],
                initial_soc_pct=soc_bounds["initial_soc_pct"],
            ),
            use_container_width=True,
            key=f"soc_tracker_{month_str}",
        )

    bottom_left, bottom_right = st.columns(2)
    with bottom_left:
        st.plotly_chart(
            chart_da_commitment_shape(da_sched_df, hourly),
            use_container_width=True,
            key=f"da_commit_shape_{month_str}",
        )
    with bottom_right:
        st.plotly_chart(
            chart_pnl_waterfall(results_df),
            use_container_width=True,
            key=f"waterfall_{month_str}",
        )

    # Daily attribution: monthly variance view — what each day earned, by source
    st.markdown("---")
    st.subheader("Daily PnL Attribution")
    st.caption(
        "Each bar is a day's PnL broken into its sources (returns above zero, costs "
        "below); the black line is daily net. Shows whether the month earned steadily "
        "or on a handful of volatile days."
    )
    st.plotly_chart(
        chart_daily_attribution(results_df),
        use_container_width=True,
        key=f"daily_attr_{month_str}",
    )

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
            hourly,
            dispatch_df,
            da_sched_df,
            min_soc_pct=soc_bounds["min_soc_pct"],
            max_soc_pct=soc_bounds["max_soc_pct"],
        ),
        use_container_width=True,
        key=f"explorer_{month_str}",
    )


if __name__ == "__main__":
    main()
