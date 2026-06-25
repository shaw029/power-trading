"""Live GB BESS benchmark — interactive Streamlit dashboard.

Fetches recent GB market data live (Nord Pool N2EX day-ahead prices + Elexon
MID / generation / demand — both public, no API key), settles the reference
batteries with user-chosen parameters, and renders three tabs (Latest, History,
Day-types). Because the engine re-runs on each parameter change, the dashboard
is interactive rather than precomputed; it is meant to run on Streamlit Cloud.

Only four levers are exposed as controls — duration, cycle target, degradation
cost and the SOC band; every other modelling choice (MID basis, slippage,
efficiency, power rating) is a fixed, stated assumption shown in the sidebar.

Run with ``streamlit run dashboard/live_app.py``.
"""

import datetime as dt
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.charts import (  # noqa: E402
    chart_daily_attribution,
    chart_daytype_profiles,
    chart_daytype_scatter,
    chart_duration_comparison,
    chart_pnl_waterfall,
    chart_price_capture,
    chart_realized_shape,
    chart_soc_tracker,
)
from live import classify as classify_mod  # noqa: E402
from live import fetch_live  # noqa: E402
from live.assets import (  # noqa: E402
    DEFAULT_START_SOC,
    REFERENCE_DURATION,
    REFERENCE_DURATIONS,
    REFERENCE_POWER_MW,
    bess_config,
)
from live.settle import settle_day  # noqa: E402
from src.bess.bess_asset import BESSAsset  # noqa: E402

METHODOLOGY = """
This is a **transparent benchmark** of a GB battery (BESS) trading strategy — not
a live trading account. No real money, broker or exchange is involved and no
orders are placed. Every figure is the settlement engine run over published
market data, so the rules behind each day's PnL are fully stated below.

#### Reference assets
A single **50 MW** battery at three storage durations, run side by side:
**1h** (50 MWh), **2h** (100 MWh) and **4h** (200 MWh). Only the energy capacity
changes; the power rating is fixed at 50 MW.

#### Data sources (live, no subscription)
- **Nord Pool N2EX** — the GB day-ahead auction price (£/MWh) used to schedule
  the day-ahead trades.
- **Elexon** — the Market Index (MID) price used for intraday re-optimisation,
  plus generation mix and demand for day-type context.

#### How a day is traded
The day-ahead schedule is optimised against the **actual cleared day-ahead
price** — published the day before (~11:00), so it is legitimate information, not
lookahead. The intraday layer then re-optimises the physical dispatch against the
**realised MID curve** for the whole day. Because this is a benchmark on settled
historical data, that intraday step is **perfect-foresight** — an idealised
best-case, consistent with the perfect-foresight DA schedule it sits on. It is
the value the realised prices made available, not a live-replicable intraday
strategy.

#### Configurable here
**Duration, cycle target, degradation cost and the SOC band** are adjustable in
the sidebar and re-run the engine live. Slippage, round-trip efficiency and power
rating are fixed, stated assumptions.

#### Out of scope
No real execution or order book, no imbalance settlement, and no broker/exchange
fees beyond the slippage and degradation frictions modelled. Results are
illustrative of the strategy under these assumptions, not a guarantee of
replicable trading returns.
"""

RESOLUTION_H = 1.0
# Nord Pool serves recent GB day-ahead prices without a subscription back to
# roughly 65 days; 60 leaves a safety margin. Older days simply 401 → their DA
# frame comes back empty and the day is skipped, so the window self-trims.
_MAX_HISTORY_DAYS = 60


def _duration_hours(duration: str) -> int:
    return int(duration.removesuffix("h"))


# --------------------------------------------------------------------------- #
# Data + settlement (cached)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _fetch_day(date_iso: str):
    """Live prices + context for one day. Cached on the date alone, so changing
    a parameter slider never re-fetches — only re-settles."""
    date = dt.date.fromisoformat(date_iso)
    prices = fetch_live.get_day_prices(date)
    context = fetch_live.get_day_context(date)
    return prices, context


def _make_cfg(cycle_target, degradation, soc_min, soc_max) -> dict:
    cfg = dict(bess_config())
    cfg.update(
        target_daily_cycles=cycle_target,
        degradation_cost_per_mwh=degradation,
        min_soc_pct=soc_min,
        max_soc_pct=soc_max,
        resolution_h=RESOLUTION_H,
    )
    return cfg


def _build_assets(cfg, degradation, soc_min, soc_max) -> dict:
    assets = {}
    for duration in REFERENCE_DURATIONS:
        assets[duration] = BESSAsset(
            capacity_mwh=REFERENCE_POWER_MW * _duration_hours(duration),
            power_mw=REFERENCE_POWER_MW,
            charge_efficiency=cfg["charge_efficiency"],
            discharge_efficiency=cfg["discharge_efficiency"],
            degradation_cost_per_mwh=degradation,
            initial_soc_pct=min(max(DEFAULT_START_SOC, soc_min), soc_max),
            min_soc_pct=soc_min,
            max_soc_pct=soc_max,
        )
    return assets


@st.cache_data(show_spinner="Fetching live data and settling…")
def _settle_range(date_isos: tuple, cycle_target, degradation, soc_min, soc_max):
    """Settle every day in ``date_isos`` (oldest first) carrying SOC forward.

    Cached on the dates plus the four parameter levers, so the engine only
    re-runs when one of those actually changes. Returns one record per settled
    day with its per-duration result, context and labels.
    """
    cfg = _make_cfg(cycle_target, degradation, soc_min, soc_max)
    assets = _build_assets(cfg, degradation, soc_min, soc_max)
    prev = {d: min(max(DEFAULT_START_SOC, soc_min), soc_max) for d in REFERENCE_DURATIONS}

    out = []
    for iso in date_isos:
        try:
            prices, context = _fetch_day(iso)
        except Exception:
            continue
        result = settle_day(dt.date.fromisoformat(iso), prices, cfg, assets, prev)
        if result is None:
            continue
        prev = {dur: r.end_soc for dur, r in result.durations.items()}
        out.append(
            {
                "date": iso,
                "result": result,
                "context": context,
                "labels": classify_mod.classify(prices, context),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Frame builders (DurationResult -> the frames the chart builders expect)
# --------------------------------------------------------------------------- #
def _dispatch_frame(date_iso: str, dur_result) -> pd.DataFrame:
    log = dur_result.dispatch_log
    base = pd.Timestamp(date_iso, tz="UTC")
    ts = [base + pd.Timedelta(hours=i) for i in range(len(log))]
    return pd.DataFrame(
        {
            "timestamp": ts,
            "hour": [t.hour for t in ts],
            "da_mw": [e["da_mw"] for e in log],
            "intraday_mw": [e["intraday_mw"] for e in log],
            "final_mw": [e["final_mw"] for e in log],
            "soc_after": [e["soc_after"] for e in log],
            "da_price": [e["da_price_actual"] for e in log],
            "mid_price": [e["mid_price"] for e in log],
        }
    )


def _prices_hourly(dispatch_df: pd.DataFrame) -> pd.DataFrame:
    return (
        dispatch_df.set_index("timestamp")[["da_price", "mid_price"]]
        .rename(columns={"da_price": "day_ahead_price"})
        .sort_index()
    )


def _da_sched_frame(dispatch_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": dispatch_df["timestamp"],
            "da_mw": dispatch_df["da_mw"],
            "da_price_pred": dispatch_df["da_price"],
        }
    )


def _pnl_row(date_iso, dur_result) -> dict:
    return {
        "date": date_iso,
        "benchmark_da_revenue": dur_result.benchmark_da_revenue,
        "intraday_da_improvement": dur_result.intraday_da_improvement,
        "execution_costs_paid": dur_result.execution_costs_paid,
        "degradation_cost": dur_result.degradation_cost,
        "net_pnl": dur_result.net_pnl,
    }


def _day_type(labels) -> str:
    return labels[0] if labels else "untagged"


# --------------------------------------------------------------------------- #
# Tab renderers
# --------------------------------------------------------------------------- #
def _render_latest(days, duration, soc_min, soc_max):
    record = days[-1]
    dur_result = record["result"].durations[duration]
    st.subheader(f"Latest settled day — {record['date']}  ·  {duration} battery")
    if record["labels"]:
        st.write(" ".join(f"`{label}`" for label in record["labels"]))

    cols = st.columns(4)
    cols[0].metric("Net PnL", f"£{dur_result.net_pnl:,.0f}")
    cols[1].metric("DA benchmark", f"£{dur_result.benchmark_da_revenue:,.0f}")
    cols[2].metric("Cycles", f"{dur_result.cycles:.2f}")
    cols[3].metric("Capture", f"{dur_result.capture:.2f}")

    dispatch = _dispatch_frame(record["date"], dur_result)
    prices_hourly = _prices_hourly(dispatch)
    da_sched = _da_sched_frame(dispatch)

    # A single settled day is already zoomed in, so no scrollable explorer here —
    # just the by-hour dispatch shape, the SOC path and the PnL bridge.
    st.plotly_chart(chart_realized_shape(dispatch, prices_hourly, da_sched), width="stretch")
    left, right = st.columns(2)
    left.plotly_chart(
        chart_soc_tracker(
            dispatch, min_soc_pct=soc_min, max_soc_pct=soc_max, initial_soc_pct=DEFAULT_START_SOC
        ),
        width="stretch",
    )
    right.plotly_chart(
        chart_pnl_waterfall(pd.DataFrame([_pnl_row(record["date"], dur_result)])),
        width="stretch",
    )


def _range_dispatch(days, duration) -> pd.DataFrame:
    """One continuous dispatch frame spanning every settled day in order."""
    frames = [_dispatch_frame(d["date"], d["result"].durations[duration]) for d in days]
    return pd.concat(frames, ignore_index=True)


def _render_history(days, duration):
    rows = [_pnl_row(d["date"], d["result"].durations[duration]) for d in days]
    results_df = pd.DataFrame(rows)
    st.subheader(f"History — {len(days)} day(s)  ·  {duration} battery")

    cols = st.columns(3)
    cols[0].metric("Total net PnL", f"£{results_df['net_pnl'].sum():,.0f}")
    cols[1].metric("Mean / day", f"£{results_df['net_pnl'].mean():,.0f}")
    cols[2].metric("Positive days", f"{int((results_df['net_pnl'] > 0).sum())}/{len(results_df)}")

    st.plotly_chart(chart_daily_attribution(results_df), width="stretch")

    totals = [
        {"duration": d, "net_pnl": sum(rec["result"].durations[d].net_pnl for rec in days)}
        for d in REFERENCE_DURATIONS
    ]
    st.plotly_chart(chart_duration_comparison(pd.DataFrame(totals)), width="stretch")

    # Price-capture profile aggregated over the whole range: charge/discharge by
    # hour of day against the average DA price.
    dispatch = _range_dispatch(days, duration)
    st.plotly_chart(chart_price_capture(dispatch, duration_h=RESOLUTION_H), width="stretch")


def _render_day_types(days, duration):
    st.subheader(f"Day-types — {duration} battery")
    scatter_rows, profile_rows = [], []
    for record in days:
        dur_result = record["result"].durations[duration]
        da = [e["da_price_actual"] for e in dur_result.dispatch_log]
        day_type = _day_type(record["labels"])
        if da:
            scatter_rows.append(
                {
                    "da_spread": max(da) - min(da),
                    "net_pnl": dur_result.net_pnl,
                    "day_type": day_type,
                }
            )
        for i, entry in enumerate(dur_result.dispatch_log):
            profile_rows.append({"hour": i % 24, "soc": entry["soc_after"], "day_type": day_type})

    st.plotly_chart(chart_daytype_scatter(pd.DataFrame(scatter_rows)), width="stretch")
    st.plotly_chart(chart_daytype_profiles(pd.DataFrame(profile_rows)), width="stretch")


def _render_methodology():
    st.subheader("Methodology")
    st.markdown(METHODOLOGY)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="Live GB BESS Benchmark", layout="wide")
    st.title("Live GB BESS Benchmark")
    st.caption(
        "Reference 50 MW GB batteries settled on live market data "
        "(Nord Pool N2EX day-ahead + Elexon MID/generation/demand)."
    )

    cfg = bess_config()
    sb = st.sidebar
    sb.header("Parameters")
    # Always load the full free Nord Pool window — no reason to show less history.
    n_days = _MAX_HISTORY_DAYS
    duration = sb.radio(
        "Duration",
        list(REFERENCE_DURATIONS),
        index=list(REFERENCE_DURATIONS).index(REFERENCE_DURATION),
        horizontal=True,
    )
    cycle_target = sb.slider(
        "Cycle target (cycles/day)", 0.5, 3.0, float(cfg.get("target_daily_cycles") or 1.5), 0.5
    )
    degradation = sb.slider(
        "Degradation cost (£/MWh)", 0.0, 20.0, float(cfg["degradation_cost_per_mwh"]), 0.5
    )
    soc_min, soc_max = sb.slider(
        "SOC band (%)", 0, 100, (int(cfg["min_soc_pct"] * 100), int(cfg["max_soc_pct"] * 100)), 5
    )
    soc_min, soc_max = soc_min / 100.0, soc_max / 100.0

    sb.divider()
    sb.caption(f"History: last {n_days} days (the full free Nord Pool window).")
    sb.caption(
        "Fixed assumptions: "
        f"slippage £{cfg.get('execution', {}).get('slippage', 0):.2f}/MWh · "
        f"round-trip {cfg['charge_efficiency'] * cfg['discharge_efficiency']:.0%} · "
        f"{REFERENCE_POWER_MW:.0f} MW power."
    )

    yesterday = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    date_isos = tuple(
        (yesterday - dt.timedelta(days=i)).isoformat() for i in range(n_days - 1, -1, -1)
    )
    days = _settle_range(date_isos, cycle_target, degradation, soc_min, soc_max)

    if not days:
        st.warning("No days could be settled — live data may be temporarily unavailable.")
        return

    latest_tab, history_tab, daytype_tab, method_tab = st.tabs(
        ["Latest", "History", "Day-types", "Methodology"]
    )
    with latest_tab:
        _render_latest(days, duration, soc_min, soc_max)
    with history_tab:
        _render_history(days, duration)
    with daytype_tab:
        _render_day_types(days, duration)
    with method_tab:
        _render_methodology()


if __name__ == "__main__":
    main()
