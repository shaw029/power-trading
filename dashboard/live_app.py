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
    chart_fleet_by_optimiser,
    chart_fleet_by_region,
    chart_fleet_daily,
    chart_fleet_leaderboard,
    chart_operation_explorer,
    chart_pnl_waterfall,
    chart_price_capture,
    chart_realized_shape,
    chart_soc_tracker,
)
from fleet import fetch_fleet  # noqa: E402
from fleet import performance as fleet_perf  # noqa: E402
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
A **transparent simulation** — no real money, broker or orders. Every figure is
the settlement engine run over published market data.

- **Asset** — one 50 MW battery; the parameter panel picks its duration
  (1h / 2h / 4h).
- **Data (live, free)** — Nord Pool N2EX day-ahead price; Elexon MID price plus
  generation and demand for day-type context.
- **Trading** — the day-ahead schedule optimises against the actual cleared DA
  price (published the day before, so legitimate information). The intraday
  layer then re-optimises against the realised MID curve with **perfect
  foresight** — an idealised best case, not a live-replicable strategy.
- **Levers** — duration, cycle target, degradation cost, SOC band (the panel
  at the top of the tab). Fixed: slippage, round-trip efficiency, 50 MW power.
- **Out of scope** — real execution, imbalance settlement, and any fees beyond
  the slippage and degradation modelled. Illustrative, not a guarantee of
  replicable returns.
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


def _build_asset(cfg, duration, degradation, soc_min, soc_max) -> dict:
    """A single-duration ``{duration: BESSAsset}`` map — only the duration the
    user has selected is settled, so a re-settle solves one LP set, not three."""
    return {
        duration: BESSAsset(
            capacity_mwh=REFERENCE_POWER_MW * _duration_hours(duration),
            power_mw=REFERENCE_POWER_MW,
            charge_efficiency=cfg["charge_efficiency"],
            discharge_efficiency=cfg["discharge_efficiency"],
            degradation_cost_per_mwh=degradation,
            initial_soc_pct=min(max(DEFAULT_START_SOC, soc_min), soc_max),
            min_soc_pct=soc_min,
            max_soc_pct=soc_max,
        )
    }


@st.cache_data(show_spinner="Fetching live data and settling…")
def _settle_range(date_isos: tuple, duration, cycle_target, degradation, soc_min, soc_max):
    """Settle every day in ``date_isos`` (oldest first) carrying SOC forward, for
    the single selected ``duration``.

    Cached on the dates, the duration and the four parameter levers, so the engine
    only re-runs when one of those actually changes. Returns one record per
    settled day with its result, context and labels.
    """
    cfg = _make_cfg(cycle_target, degradation, soc_min, soc_max)
    assets = _build_asset(cfg, duration, degradation, soc_min, soc_max)
    prev = {duration: min(max(DEFAULT_START_SOC, soc_min), soc_max)}

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


@st.cache_data(show_spinner="Fetching live GB fleet data…")
def _fleet_range(date_isos: tuple) -> pd.DataFrame:
    """Per-site daily metrics for every real fleet battery over ``date_isos``.

    Independent of the sidebar levers (these are real assets, not the
    parameterised benchmark), so it is cached on the dates alone. Days whose
    Elexon data is unavailable are skipped; a day with prices/PN but no
    published BM cashflows yet still settles with BM = 0.
    """
    frames = []
    for iso in date_isos:
        date = dt.date.fromisoformat(iso)
        try:
            pn = fetch_fleet.fetch_fleet_pn(date)
            mid = fetch_fleet.fetch_day_mid_prices(date)
        except Exception:
            continue
        if not pn or mid.empty:
            continue
        try:
            cashflows = fetch_fleet.fetch_fleet_bm_cashflows(date)
        except Exception:
            cashflows = {"bid": [], "offer": []}
        day = fleet_perf.day_site_metrics(iso, pn, cashflows, mid)
        if not day.empty:
            frames.append(day)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


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


def _render_history(days, duration, soc_min, soc_max):
    rows = [_pnl_row(d["date"], d["result"].durations[duration]) for d in days]
    results_df = pd.DataFrame(rows)
    st.subheader(f"History — {len(days)} day(s)  ·  {duration} battery")

    cols = st.columns(3)
    cols[0].metric("Total net PnL", f"£{results_df['net_pnl'].sum():,.0f}")
    cols[1].metric("Mean / day", f"£{results_df['net_pnl'].mean():,.0f}")
    cols[2].metric("Positive days", f"{int((results_df['net_pnl'] > 0).sum())}/{len(results_df)}")

    st.plotly_chart(chart_daily_attribution(results_df), width="stretch")

    # Price-capture profile aggregated over the whole range: charge/discharge by
    # hour of day against the average DA price.
    dispatch = _range_dispatch(days, duration)
    st.plotly_chart(chart_price_capture(dispatch, duration_h=RESOLUTION_H), width="stretch")

    # Dispatch explorer over a user-chosen window. Rendering the full history at
    # once made the tab sluggish (why the 60-day explorer was dropped), so only
    # the selected slice — defaulting to the last 7 days — is drawn.
    st.markdown("#### Dispatch explorer")
    dates = [d["date"] for d in days]
    if len(dates) > 1:
        start_iso, end_iso = st.select_slider(
            "Explorer window (days)",
            options=dates,
            value=(dates[max(0, len(dates) - 7)], dates[-1]),
        )
    else:
        start_iso = end_iso = dates[0]
    window = [d for d in days if start_iso <= d["date"] <= end_iso]
    win_dispatch = _range_dispatch(window, duration)
    st.plotly_chart(
        chart_operation_explorer(
            _prices_hourly(win_dispatch),
            win_dispatch,
            _da_sched_frame(win_dispatch),
            min_soc_pct=soc_min,
            max_soc_pct=soc_max,
        ),
        width="stretch",
    )


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


FLEET_METHODOLOGY = """
Estimated performance of real GB grid-scale batteries, built entirely from free
public Elexon per-unit data.

- **Revenue = wholesale proxy + Balancing Mechanism.** The wholesale proxy
  values each unit's Physical Notification at the half-hourly MID price
  (actual traded prices are private). BM revenue is Elexon's indicative
  per-unit bid/offer cashflows (`EBOCF`), summed as published.
- **Excluded** — ancillary services (Dynamic Containment etc.), capacity
  market and private PPAs, so ancillary-heavy sites read low here.
- **Metadata** — optimiser, region and approximate MWh are a hand-curated
  snapshot and can go stale; cycle counts are indicative.
"""


# Quick-pick period presets for the global filter bar, in display order.
_PERIOD_PRESETS: dict[str, int] = {"7D": 7, "14D": 14, "30D": 30, "60D": 60}


def _global_filters(date_isos: tuple) -> tuple[str, str, list[str]]:
    """The shared filter bar above the tabs: period + day type.

    Both products cover the same market days, so these two filters apply to
    everything below. They slice what is *displayed*; the benchmark engine
    always settles the full window so its SOC chain stays intact.

    The period offers quick presets (last 7/14/30/60 days) plus a calendar
    range picker under "Custom". Day types are multi-select pills; nothing
    selected means every day. Rendered borderless so it can sit in the page
    header, to the right of the title.
    """
    first = dt.date.fromisoformat(date_isos[0])
    last = dt.date.fromisoformat(date_isos[-1])

    cols = st.columns([2.2, 2.2, 3.6], vertical_alignment="bottom")
    preset = cols[0].segmented_control(
        "Period",
        list(_PERIOD_PRESETS) + ["Custom"],
        default="60D",
        help="Quick windows count back from the most recent settled day.",
    )
    # A segmented control can be deselected entirely; treat that as "all".
    preset = preset or "60D"

    if preset == "Custom":
        picked = cols[1].date_input(
            "Custom range",
            value=(first, last),
            min_value=first,
            max_value=last,
        )
        # While the user is mid-selection the widget returns a single date.
        if isinstance(picked, tuple):
            if len(picked) == 2:
                start, end = picked[0].isoformat(), picked[1].isoformat()
            else:
                start = end = (picked[0] if picked else first).isoformat()
        else:
            start = end = picked.isoformat()
    else:
        n = _PERIOD_PRESETS[preset]
        start, end = date_isos[max(0, len(date_isos) - n)], date_isos[-1]

    day_types = cols[2].pills(
        "Day types",
        sorted(classify_mod.TAGS) + ["untagged"],
        selection_mode="multi",
        help=(
            "Day character from the classifier — none selected means all "
            "days. 'untagged' covers days with no clear character or no "
            "classification data."
        ),
    )

    n_days = sum(1 for d in date_isos if start <= d <= end)
    tags = ", ".join(day_types) if day_types else "all day types"
    st.caption(f"Showing **{start} → {end}** · {n_days} day(s) · {tags}")

    return start, end, list(day_types or [])


def _matches_day_types(labels: list[str] | None, day_types: list[str]) -> bool:
    """Shared day-type predicate: empty selection matches everything and
    ``untagged`` matches days with no tags."""
    if not day_types:
        return True
    if not labels:
        return "untagged" in day_types
    return bool(set(day_types).intersection(labels))


def _filter_days(days: list, start: str, end: str, day_types: list[str]) -> list:
    """Apply the global filters to the settled benchmark days (view only)."""
    return [
        d
        for d in days
        if start <= d["date"] <= end and _matches_day_types(d["labels"], day_types)
    ]


def _fleet_filters(fleet_df: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    """The fleet's own filter row: which assets, not which days."""
    cols = st.columns(3)
    sites = cols[0].multiselect(
        "Sites", sorted(fleet_df["site"].unique()), placeholder="All sites"
    )
    optimisers = cols[1].multiselect(
        "Optimisers", sorted(fleet_df["optimiser"].unique()), placeholder="All optimisers"
    )
    regions = cols[2].multiselect(
        "Regions", sorted(fleet_df["region"].unique()), placeholder="All regions"
    )
    return sites, optimisers, regions


def _render_fleet(
    fleet_df: pd.DataFrame,
    day_labels: dict[str, list[str]],
    start: str,
    end: str,
    day_types: list[str],
):
    with st.container(border=True):
        sites, optimisers, regions = _fleet_filters(fleet_df)
    fleet_df = fleet_perf.filter_daily(
        fleet_df,
        start=start,
        end=end,
        sites=sites,
        optimisers=optimisers,
        regions=regions,
        day_types=day_types,
        day_labels=day_labels,
    )
    if fleet_df.empty:
        st.info("No fleet days match the current filters — widen the period or clear a filter.")
        return

    n_days = fleet_df["date"].nunique()
    site_df = fleet_perf.summarise_by_site(fleet_df)
    st.subheader(f"{len(site_df)} site(s)  ·  {n_days} day(s)")
    st.caption(
        "Estimates from public per-unit Elexon data (Physical Notifications × MID "
        "+ indicative BM cashflows); ancillary revenue excluded — see Methodology."
    )

    tracked_mw = float(site_df["power_mw"].sum())
    fleet_gbp = float(site_df["total_gbp"].sum())
    # Not every site settles every day in a filtered window, so the fleet
    # average is weighted by each site's actual MW-days, not MW × window days.
    mw_days = float((site_df["power_mw"] * site_df["days"]).sum())
    cols = st.columns(4)
    cols[0].metric("Fleet tracked", f"{tracked_mw:,.0f} MW")
    cols[1].metric("Est. fleet revenue", f"£{fleet_gbp:,.0f}")
    cols[2].metric("Fleet avg", f"£{fleet_gbp / mw_days:,.0f}/MW/day")
    best = site_df.iloc[0]
    cols[3].metric(
        "Top site", best["site"], f"£{best['gbp_per_mw_day']:,.0f}/MW/day", delta_color="off"
    )

    st.plotly_chart(chart_fleet_leaderboard(site_df), width="stretch")
    left, right = st.columns(2)
    left.plotly_chart(chart_fleet_by_optimiser(fleet_perf.summarise_by_optimiser(fleet_df)), width="stretch")
    right.plotly_chart(chart_fleet_by_region(fleet_perf.summarise_by_region(fleet_df)), width="stretch")
    st.plotly_chart(chart_fleet_daily(fleet_perf.fleet_daily(fleet_df)), width="stretch")

    st.markdown("#### Site detail")
    table = site_df[
        [
            "site", "optimiser", "region", "power_mw", "capacity_mwh", "days",
            "gbp_per_mw_day", "total_gbp", "wholesale_gbp", "bm_gbp", "cycles_per_day",
        ]
    ].rename(
        columns={
            "site": "Site",
            "optimiser": "Optimiser",
            "region": "Region",
            "power_mw": "MW",
            "capacity_mwh": "MWh (approx)",
            "days": "Days",
            "gbp_per_mw_day": "£/MW/day",
            "total_gbp": "Total £",
            "wholesale_gbp": "Wholesale £",
            "bm_gbp": "BM £",
            "cycles_per_day": "Cycles/day",
        }
    )
    st.dataframe(
        table.style.format(
            {
                "MW": "{:,.0f}",
                "MWh (approx)": "{:,.0f}",
                "£/MW/day": "£{:,.0f}",
                "Total £": "£{:,.0f}",
                "Wholesale £": "£{:,.0f}",
                "BM £": "£{:,.0f}",
                "Cycles/day": "{:.2f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def _benchmark_parameters() -> tuple:
    """The benchmark's parameter panel — lives inside the benchmark tab (like
    the fleet's filter panel) so nothing looks global that isn't."""
    cfg = bess_config()
    cols = st.columns([1, 1, 1, 1])
    duration = cols[0].radio(
        "Duration",
        list(REFERENCE_DURATIONS),
        index=list(REFERENCE_DURATIONS).index(REFERENCE_DURATION),
        horizontal=True,
    )
    cycle_target = cols[1].slider(
        "Cycle target (cycles/day)", 0.5, 3.0, float(cfg.get("target_daily_cycles") or 1.5), 0.5
    )
    degradation = cols[2].slider(
        "Degradation cost (£/MWh)", 0.0, 20.0, float(cfg["degradation_cost_per_mwh"]), 0.5
    )
    soc_min, soc_max = cols[3].slider(
        "SOC band (%)", 0, 100, (int(cfg["min_soc_pct"] * 100), int(cfg["max_soc_pct"] * 100)), 5
    )
    st.caption(
        "Changing a lever re-settles the whole simulation. Fixed assumptions: "
        f"slippage £{cfg.get('execution', {}).get('slippage', 0):.2f}/MWh · "
        f"round-trip {cfg['charge_efficiency'] * cfg['discharge_efficiency']:.0%} · "
        f"{REFERENCE_POWER_MW:.0f} MW power · last {_MAX_HISTORY_DAYS} days "
        "(the full free Nord Pool window)."
    )
    return duration, cycle_target, degradation, soc_min / 100.0, soc_max / 100.0


def _render_methodology():
    st.subheader("Simulated benchmark")
    st.markdown(METHODOLOGY)
    st.divider()
    st.subheader("Live GB fleet")
    st.markdown(FLEET_METHODOLOGY)


def main():
    st.set_page_config(page_title="Live GB BESS", layout="wide")

    yesterday = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    date_isos = tuple(
        (yesterday - dt.timedelta(days=i)).isoformat()
        for i in range(_MAX_HISTORY_DAYS - 1, -1, -1)
    )

    # Page header: title on the left, the global filters on the right.
    title_col, filters_col = st.columns([1.3, 3.7], vertical_alignment="bottom")
    with title_col:
        st.title("Live GB BESS")
    with filters_col:
        start, end, day_types = _global_filters(date_isos)

    bench_tab, fleet_tab, method_tab = st.tabs(
        ["Simulated benchmark", "Live GB fleet", "Methodology"]
    )

    with bench_tab:
        with st.container(border=True):
            duration, cycle_target, degradation, soc_min, soc_max = _benchmark_parameters()
        days = _settle_range(date_isos, duration, cycle_target, degradation, soc_min, soc_max)
        shown_days = _filter_days(days, start, end, day_types)
        if not days:
            st.warning("No days could be settled — live data may be temporarily unavailable.")
        elif not shown_days:
            st.info("No settled days match the current filters — widen the period or day types.")
        else:
            _render_latest(shown_days, duration, soc_min, soc_max)
            st.divider()
            _render_history(shown_days, duration, soc_min, soc_max)
            st.divider()
            _render_day_types(shown_days, duration)

    with fleet_tab:
        fleet_df = _fleet_range(date_isos)
        if fleet_df.empty:
            st.warning(
                "No fleet data could be fetched — Elexon per-unit data may be "
                "temporarily unavailable."
            )
        else:
            day_labels = {d["date"]: d["labels"] for d in days}
            _render_fleet(fleet_df, day_labels, start, end, day_types)

    with method_tab:
        _render_methodology()


if __name__ == "__main__":
    main()
