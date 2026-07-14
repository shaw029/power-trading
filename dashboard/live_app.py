"""Live GB BESS benchmark — interactive Streamlit dashboard.

Fetches recent GB market data live (Nord Pool N2EX day-ahead prices + Elexon
MID / generation / demand — both public, no API key), settles the reference
battery with user-chosen parameters, and renders a sidebar-navigated app:
benchmark pages (Latest day / History / Day types), a real-fleet page and the
methodology. Because the engine re-runs on each parameter change, the
dashboard is interactive rather than precomputed; it is meant to run on
Streamlit Cloud.

Global filters (period + day types) and the benchmark's four levers — duration,
cycle target, degradation cost and the SOC band — live in the sidebar; every
other modelling choice (MID basis, slippage, efficiency, power rating) is a
fixed, stated assumption.

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
    chart_daytype_capture,
    chart_daytype_frequency,
    chart_daytype_matrix,
    chart_daytype_profiles,
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
  generation and demand for day-type context; Sheffield Solar PV_Live for GB
  embedded solar (Elexon's transmission-metered mix carries no solar at all).
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


def _dates() -> tuple:
    """Every settlement date the app covers, oldest first."""
    yesterday = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    return tuple(
        (yesterday - dt.timedelta(days=i)).isoformat()
        for i in range(_MAX_HISTORY_DAYS - 1, -1, -1)
    )


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


def _warm_fetch(date_isos: tuple) -> None:
    """Pre-fetch every day once with a visible progress bar, so the first load
    is not a single opaque spinner. Later runs skip straight through: the
    session flag avoids re-rendering the bar and every per-day fetch is a
    cache hit anyway."""
    if st.session_state.get("_prices_warmed"):
        return
    n = len(date_isos)
    bar = st.progress(0.0, text=f"First load — fetching {n} days of GB market data…")
    for i, iso in enumerate(date_isos):
        try:
            _fetch_day(iso)
        except Exception:
            pass  # _settle_range skips unfetchable days
        bar.progress((i + 1) / n, text=f"Fetching GB market data · {iso} ({i + 1}/{n})")
    bar.empty()
    st.session_state["_prices_warmed"] = True


@st.cache_data(show_spinner="Settling the benchmark battery…")
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


@st.cache_data(show_spinner=False)
def _fleet_day(date_iso: str) -> pd.DataFrame:
    """Per-site metrics for every real fleet battery on one day.

    Independent of the benchmark levers (these are real assets), so it is
    cached on the date alone. A day whose Elexon data is unavailable returns
    an empty frame; a day with prices/PN but no published BM cashflows yet
    still settles with BM = 0.
    """
    date = dt.date.fromisoformat(date_iso)
    try:
        pn = fetch_fleet.fetch_fleet_pn(date)
        mid = fetch_fleet.fetch_day_mid_prices(date)
    except Exception:
        return pd.DataFrame()
    if not pn or mid.empty:
        return pd.DataFrame()
    try:
        cashflows = fetch_fleet.fetch_fleet_bm_cashflows(date)
    except Exception:
        cashflows = {"bid": [], "offer": []}
    return fleet_perf.day_site_metrics(date_iso, pn, cashflows, mid)


def _fleet_range(date_isos: tuple) -> pd.DataFrame:
    """All per-site fleet metrics over ``date_isos``, with a first-load
    progress bar (per-day results are cached, so later runs are cheap)."""
    show_bar = not st.session_state.get("_fleet_warmed")
    n = len(date_isos)
    bar = st.progress(0.0, text=f"First load — fetching per-unit Elexon data for {n} days…") if show_bar else None
    frames = []
    for i, iso in enumerate(date_isos):
        day = _fleet_day(iso)
        if not day.empty:
            frames.append(day)
        if bar is not None:
            bar.progress((i + 1) / n, text=f"Fetching fleet data · {iso} ({i + 1}/{n})")
    if bar is not None:
        bar.empty()
    st.session_state["_fleet_warmed"] = True
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


# --------------------------------------------------------------------------- #
# Page chrome & shared benchmark view
# --------------------------------------------------------------------------- #
def _page_header(title: str, subtitle: str) -> None:
    """Every page opens the same way: a heading and one quiet status line."""
    st.markdown(f"### {title}")
    st.caption(subtitle)


def _benchmark_view():
    """Sidebar controls + settled days shared by the three benchmark pages.

    Returns ``(params, shown_days, window_caption)`` — or ``None`` after
    rendering the appropriate empty-state message, so each page can simply
    bail out.
    """
    date_isos = _dates()
    start, end, day_types = _global_filters(date_isos)
    duration, cycle_target, degradation, soc_min, soc_max = _benchmark_parameters()

    _warm_fetch(date_isos)
    days = _settle_range(date_isos, duration, cycle_target, degradation, soc_min, soc_max)
    shown = _filter_days(days, start, end, day_types)

    if not days:
        st.warning("No days could be settled — live data may be temporarily unavailable.")
        return None
    if not shown:
        st.info("No settled days match the current filters — widen the period or day types.")
        return None

    tags = ", ".join(day_types) if day_types else "all day types"
    caption = (
        f"{shown[0]['date']} → {shown[-1]['date']} · {len(shown)} day(s) · {tags} · "
        f"{duration} × {REFERENCE_POWER_MW:.0f} MW simulated battery"
    )
    params = {
        "duration": duration,
        "cycle_target": cycle_target,
        "degradation": degradation,
        "soc_min": soc_min,
        "soc_max": soc_max,
    }
    return params, shown, caption


def _range_dispatch(days, duration) -> pd.DataFrame:
    """One continuous dispatch frame spanning every settled day in order."""
    frames = [_dispatch_frame(d["date"], d["result"].durations[duration]) for d in days]
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Benchmark pages
# --------------------------------------------------------------------------- #
def _page_latest():
    view = _benchmark_view()
    if view is None:
        return
    params, shown, caption = view
    duration = params["duration"]

    _page_header("Latest settled day", caption)

    # Defaults to the most recent settled day, but any day in the filtered
    # window can be inspected without leaving the page.
    dates = [d["date"] for d in shown]
    picked = st.selectbox(
        "Day",
        options=dates,
        index=len(dates) - 1,
        help="Defaults to the latest settled day — pick any other day to inspect it.",
    )
    record = next(d for d in shown if d["date"] == picked)
    dur_result = record["result"].durations[duration]
    if record["labels"]:
        st.write(" ".join(f"`{label}`" for label in record["labels"]))

    window_mean = sum(
        d["result"].durations[duration].net_pnl for d in shown
    ) / len(shown)
    cols = st.columns(4)
    cols[0].metric(
        "Net PnL",
        f"£{dur_result.net_pnl:,.0f}",
        delta=f"{dur_result.net_pnl - window_mean:+,.0f} vs window avg",
        help="Day-ahead revenue + intraday improvement − execution and degradation costs.",
    )
    cols[1].metric(
        "DA benchmark",
        f"£{dur_result.benchmark_da_revenue:,.0f}",
        help="What the frozen day-ahead schedule alone would have earned, before any intraday re-optimisation.",
    )
    cols[2].metric(
        "Cycles",
        f"{dur_result.cycles:.2f}",
        help=f"Equivalent full charge/discharge cycles used this day (target ≤ {params['cycle_target']:.1f}).",
    )
    cols[3].metric(
        "Capture",
        f"{dur_result.capture:.2f}",
        help=(
            "Net PnL as a share of the perfect-foresight day-ahead optimum — "
            "1.00 means every pound available was captured; 0.00 means the "
            "day had no meaningful spread."
        ),
    )

    dispatch = _dispatch_frame(record["date"], dur_result)
    prices_hourly = _prices_hourly(dispatch)
    da_sched = _da_sched_frame(dispatch)

    # A single settled day is already zoomed in, so no scrollable explorer here —
    # just the by-hour dispatch shape, the SOC path and the PnL bridge.
    st.plotly_chart(chart_realized_shape(dispatch, prices_hourly, da_sched), width="stretch")
    left, right = st.columns(2)
    left.plotly_chart(
        chart_soc_tracker(
            dispatch,
            min_soc_pct=params["soc_min"],
            max_soc_pct=params["soc_max"],
            initial_soc_pct=DEFAULT_START_SOC,
        ),
        width="stretch",
    )
    right.plotly_chart(
        chart_pnl_waterfall(pd.DataFrame([_pnl_row(record["date"], dur_result)])),
        width="stretch",
    )


def _page_history():
    view = _benchmark_view()
    if view is None:
        return
    params, shown, caption = view
    duration = params["duration"]

    rows = [_pnl_row(d["date"], d["result"].durations[duration]) for d in shown]
    results_df = pd.DataFrame(rows)
    _page_header("History", caption)

    net = results_df["net_pnl"]
    best_i = int(net.idxmax())
    cols = st.columns(4)
    cols[0].metric(
        "Total net PnL",
        f"£{net.sum():,.0f}",
        help="Sum of daily net PnL over the shown window.",
    )
    cols[1].metric(
        "Mean / day",
        f"£{net.mean():,.0f}",
        help="Average daily net PnL over the shown window.",
    )
    cols[2].metric(
        "Positive days",
        f"{int((net > 0).sum())}/{len(net)}",
        help="Days that closed with a positive net PnL.",
    )
    cols[3].metric(
        "Best day",
        f"£{net.max():,.0f}",
        delta=results_df.loc[best_i, "date"],
        delta_color="off",
        help="Highest single-day net PnL in the shown window.",
    )

    st.plotly_chart(chart_daily_attribution(results_df), width="stretch")

    # Price-capture profile aggregated over the whole range: charge/discharge by
    # hour of day against the average DA price.
    dispatch = _range_dispatch(shown, duration)
    st.plotly_chart(chart_price_capture(dispatch, duration_h=RESOLUTION_H), width="stretch")

    # Dispatch explorer over a user-chosen window. Rendering the full history
    # at once made the page sluggish, so only the selected slice — defaulting
    # to the last 7 days — is drawn.
    st.markdown("#### Dispatch explorer")
    st.caption("Hour-by-hour prices, trades and state of charge over the selected days.")
    dates = [d["date"] for d in shown]
    if len(dates) > 1:
        start_iso, end_iso = st.select_slider(
            "Explorer window (days)",
            options=dates,
            value=(dates[max(0, len(dates) - 7)], dates[-1]),
        )
    else:
        start_iso = end_iso = dates[0]
    window = [d for d in shown if start_iso <= d["date"] <= end_iso]
    win_dispatch = _range_dispatch(window, duration)
    st.plotly_chart(
        chart_operation_explorer(
            _prices_hourly(win_dispatch),
            win_dispatch,
            _da_sched_frame(win_dispatch),
            min_soc_pct=params["soc_min"],
            max_soc_pct=params["soc_max"],
        ),
        width="stretch",
    )


def _page_day_types():
    view = _benchmark_view()
    if view is None:
        return
    params, shown, caption = view
    duration = params["duration"]

    _page_header("Day types", caption)
    st.caption(
        "Each settled day is tagged on two independent axes: what **drove** it "
        "(wind, sun, demand, weekend) and how **prices behaved** (volatility, "
        "negative hours, peak shape). A day can hold several tags and counts "
        "under each — so read these as regime views, not disjoint buckets."
    )

    membership_rows, matrix_counts, profile_rows, table_rows = [], {}, [], []
    for record in shown:
        dur_result = record["result"].durations[duration]
        labels = record["labels"]
        drivers = [t for t in labels if t in classify_mod.DRIVER_TAGS]
        price_tags = [t for t in labels if t in classify_mod.PRICE_TAGS]

        for tag in labels:
            membership_rows.append(
                {
                    "date": record["date"],
                    "tag": tag,
                    "family": "driver" if tag in classify_mod.DRIVER_TAGS else "price",
                    "capture": dur_result.capture,
                }
            )
        for d in drivers or ["(none)"]:
            for p in price_tags or ["(none)"]:
                matrix_counts[(d, p)] = matrix_counts.get((d, p), 0) + 1
        # SOC shape is grouped by price character only — that's what dispatch
        # actually responds to; a windy-tag average would blur distinct shapes.
        for tag in price_tags or ["untagged"]:
            for i, entry in enumerate(dur_result.dispatch_log):
                profile_rows.append({"hour": i % 24, "soc": entry["soc_after"], "day_type": tag})
        table_rows.append(
            {
                "date": record["date"],
                "tags": ", ".join(labels) or "untagged",
                "gbp_per_mw": dur_result.net_pnl / REFERENCE_POWER_MW,
                "capture": dur_result.capture,
                "cycles": dur_result.cycles,
            }
        )

    if not membership_rows:
        st.info("No tagged days in the current window — widen the period filter.")
        return

    st.plotly_chart(chart_daytype_capture(pd.DataFrame(membership_rows)), width="stretch")

    drivers_idx = sorted({d for d, _ in matrix_counts}) if matrix_counts else []
    price_cols = sorted({p for _, p in matrix_counts}) if matrix_counts else []
    matrix = pd.DataFrame(
        [[matrix_counts.get((d, p), 0) for p in price_cols] for d in drivers_idx],
        index=drivers_idx,
        columns=price_cols,
    )
    left, right = st.columns(2)
    left.plotly_chart(chart_daytype_matrix(matrix), width="stretch")
    right.plotly_chart(chart_daytype_frequency(pd.DataFrame(membership_rows)), width="stretch")

    st.plotly_chart(chart_daytype_profiles(pd.DataFrame(profile_rows)), width="stretch")

    st.markdown("#### Days behind the tags")
    table = pd.DataFrame(table_rows).sort_values("date", ascending=False).rename(
        columns={
            "date": "Date",
            "tags": "Tags",
            "gbp_per_mw": "£/MW",
            "capture": "Capture",
            "cycles": "Cycles",
        }
    )
    st.dataframe(
        table.style.format({"£/MW": "£{:,.0f}", "Capture": "{:.0%}", "Cycles": "{:.2f}"}),
        width="stretch",
        hide_index=True,
    )


FLEET_METHODOLOGY = """
Estimated performance of real GB grid-scale batteries, built entirely from free
public Elexon per-unit data.

- **Revenue = wholesale proxy + Balancing Mechanism.** The wholesale proxy
  values each unit's Physical Notification at the half-hourly MID price
  (actual traded prices are private). BM revenue is Elexon's indicative
  per-unit bid/offer cashflows (`EBOCF`), summed as published.
- **Excluded (by design)** — ancillary services (Dynamic Containment etc.),
  capacity market and private PPAs. Per-unit revenue in those markets isn't in
  Elexon's free feeds — ancillary contracts sit in NESO's EAC data, and traded
  PPA prices are private — so this dashboard deliberately scopes to the two
  streams it can estimate from one source.
- **Ancillary-tilted sites can read *negative*, not just low** — energy bought
  to hold state of charge for an ancillary contract is costed at MID here,
  while the availability payment that motivated it is invisible. Sites cycling
  below ~0.3 cycles/day are flagged ⚠ in the site table: their revenue likely
  comes from markets this model cannot see, so don't read their £ figures as
  trading performance.
- **Site selection** — sites qualify by having their own registered BM Units
  (the per-unit data only exists for those), being grid-scale (~35 MW+), and
  being operational as of the July 2026 snapshot. The list is a curated
  cross-section of optimisers and regions, not a census of GB batteries;
  assets traded behind aggregator/VLP units can't be tracked at site level.
- **Metadata** — optimiser, region and approximate MWh are a hand-curated
  snapshot and can go stale; cycle counts are indicative.
"""


# Quick-pick period presets for the global filter bar, in display order.
_PERIOD_PRESETS: dict[str, int] = {"7D": 7, "14D": 14, "30D": 30, "60D": 60}


def _global_filters(date_isos: tuple) -> tuple[str, str, list[str]]:
    """The shared sidebar filters: period + day type.

    Both products cover the same market days, so these two filters apply to
    every page. They slice what is *displayed*; the benchmark engine always
    settles the full window so its SOC chain stays intact.

    The period offers quick presets (last 7/14/30/60 days) plus a calendar
    range picker under "Custom". Day types are multi-select pills; nothing
    selected means every day.
    """
    first = dt.date.fromisoformat(date_isos[0])
    last = dt.date.fromisoformat(date_isos[-1])

    with st.sidebar:
        st.markdown("**Filters**")
        preset = st.segmented_control(
            "Period",
            list(_PERIOD_PRESETS) + ["Custom"],
            default="60D",
            key="flt_period",
            help="Quick windows count back from the most recent settled day.",
        )
        # A segmented control can be deselected entirely; treat that as "all".
        preset = preset or "60D"

        if preset == "Custom":
            picked = st.date_input(
                "Custom range",
                value=(first, last),
                min_value=first,
                max_value=last,
                key="flt_custom",
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

        day_types = st.pills(
            "Day types",
            sorted(classify_mod.TAGS) + ["untagged"],
            selection_mode="multi",
            key="flt_day_types",
            help=(
                "Day character from the classifier — none selected means all "
                "days. 'untagged' covers days with no clear character or no "
                "classification data."
            ),
        )

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


def _fleet_filters(
    fleet_df: pd.DataFrame,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """The fleet's own filter row: which assets, not which days."""
    cols = st.columns(4)
    sites = cols[0].multiselect(
        "Sites", sorted(fleet_df["site"].unique()), placeholder="All sites"
    )
    optimisers = cols[1].multiselect(
        "Optimisers", sorted(fleet_df["optimiser"].unique()), placeholder="All optimisers"
    )
    regions = cols[2].multiselect(
        "Regions", sorted(fleet_df["region"].unique()), placeholder="All regions"
    )
    durations = cols[3].multiselect(
        "Battery hours",
        sorted(fleet_df["duration"].unique()),
        placeholder="All durations",
        help="Nameplate MWh over MW, rounded — e.g. 2h means the battery stores "
        "two hours of full-power output.",
    )
    return sites, optimisers, regions, durations


def _render_fleet(
    fleet_df: pd.DataFrame,
    day_labels: dict[str, list[str]],
    start: str,
    end: str,
    day_types: list[str],
):
    # Cached day frames can predate the duration column; derive it on the fly
    # so a running server survives the upgrade without a cache clear.
    if "duration" not in fleet_df.columns:
        fleet_df = fleet_df.assign(
            duration=[
                fleet_perf.duration_label(mw, mwh)
                for mw, mwh in zip(fleet_df["power_mw"], fleet_df["capacity_mwh"])
            ]
        )
    with st.container(border=True):
        sites, optimisers, regions, durations = _fleet_filters(fleet_df)
    fleet_df = fleet_perf.filter_daily(
        fleet_df,
        start=start,
        end=end,
        sites=sites,
        optimisers=optimisers,
        regions=regions,
        durations=durations,
        day_types=day_types,
        day_labels=day_labels,
    )
    if fleet_df.empty:
        st.info("No fleet days match the current filters — widen the period or clear a filter.")
        return

    n_days = fleet_df["date"].nunique()
    site_df = fleet_perf.summarise_by_site(fleet_df)
    st.caption(
        f"{len(site_df)} site(s) · {n_days} day(s) — estimates from public per-unit "
        "Elexon data (Physical Notifications × MID + indicative BM cashflows); "
        "ancillary revenue excluded, so ancillary-heavy sites read low. See Methodology."
    )

    tracked_mw = float(site_df["power_mw"].sum())
    fleet_gbp = float(site_df["total_gbp"].sum())
    # Not every site settles every day in a filtered window, so the fleet
    # average is weighted by each site's actual MW-days, not MW × window days.
    mw_days = float((site_df["power_mw"] * site_df["days"]).sum())
    cols = st.columns(4)
    cols[0].metric(
        "Fleet tracked",
        f"{tracked_mw:,.0f} MW",
        help="Total nameplate power of the sites currently shown.",
    )
    median_gbp = float(site_df["gbp_per_mw_day"].median())
    cols[1].metric(
        "Top vs median spread",
        f"£{site_df['gbp_per_mw_day'].iloc[0] - median_gbp:,.0f}/MW/day",
        f"median £{median_gbp:,.0f}",
        delta_color="off",
        help="Gap between the best site and the median site — how much optimiser "
        "skill and location were worth in this window.",
    )
    cols[2].metric(
        "Fleet avg",
        f"£{fleet_gbp / mw_days:,.0f}/MW/day",
        help="Weighted by each site's actual MW-days in the window, so sites with missing days don't drag the average.",
    )
    best = site_df.iloc[0]
    cols[3].metric(
        "Top site",
        best["site"],
        f"£{best['gbp_per_mw_day']:,.0f}/MW/day",
        delta_color="off",
        help="Best estimated £/MW/day in the shown window.",
    )

    picked = st.segmented_control(
        "Metric",
        ["Revenue", "Volume", "Cycles", "Capacity"],
        default="Revenue",
        key="fleet_metric",
        help="Re-plots every chart below: estimated £/MW/day, charged/discharged "
        "energy, cycles per day, or nameplate MW (the daily view doubles as "
        "data coverage).",
    )
    metric = (picked or "Revenue").lower()

    st.plotly_chart(chart_fleet_leaderboard(site_df, metric), width="stretch")
    left, right = st.columns(2)
    left.plotly_chart(
        chart_fleet_by_optimiser(fleet_perf.summarise_by_optimiser(fleet_df), metric),
        width="stretch",
    )
    right.plotly_chart(
        chart_fleet_by_region(fleet_perf.summarise_by_region(fleet_df), metric),
        width="stretch",
    )
    st.plotly_chart(chart_fleet_daily(fleet_perf.fleet_daily(fleet_df), metric), width="stretch")

    st.markdown("#### Site detail")
    flagged = int(site_df["likely_ancillary"].sum())
    if flagged:
        st.caption(
            f"⚠ {flagged} site(s) cycle below {fleet_perf.ANCILLARY_CYCLES_THRESHOLD} "
            "cycles/day — they are likely earning in ancillary markets this model "
            "cannot see, so their £ figures are unreliable and biased low."
        )
    table = site_df.assign(flag=site_df["likely_ancillary"].map({True: "⚠", False: ""}))[
        [
            "site", "optimiser", "region", "power_mw", "duration", "days",
            "gbp_per_mw_day", "total_gbp", "wholesale_gbp", "bm_gbp", "cycles_per_day",
            "flag",
        ]
    ].rename(
        columns={
            "flag": "Flag",
            "site": "Site",
            "optimiser": "Optimiser",
            "region": "Region",
            "power_mw": "MW",
            "duration": "Duration",
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
# Fleet & methodology pages
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _day_labels(date_isos: tuple) -> dict:
    """Day-type labels straight from the fetched prices/context, so the fleet
    page never depends on the benchmark's parameter levers."""
    out = {}
    for iso in date_isos:
        try:
            prices, context = _fetch_day(iso)
        except Exception:
            continue
        out[iso] = classify_mod.classify(prices, context)
    return out


def _page_fleet():
    date_isos = _dates()
    start, end, day_types = _global_filters(date_isos)
    tags = ", ".join(day_types) if day_types else "all day types"
    _page_header(
        "Real GB fleet",
        f"{start} → {end} · {tags} · estimated performance of real grid-scale batteries",
    )
    fleet_df = _fleet_range(date_isos)
    if fleet_df.empty:
        st.warning(
            "No fleet data could be fetched — Elexon per-unit data may be "
            "temporarily unavailable."
        )
        return
    _warm_fetch(date_isos)
    _render_fleet(fleet_df, _day_labels(date_isos), start, end, day_types)


def _page_methodology():
    _page_header("Methodology", "What these numbers are — and what they are not")
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Simulated benchmark")
        st.markdown(METHODOLOGY)
    with right:
        st.subheader("Live GB fleet")
        st.markdown(FLEET_METHODOLOGY)


# --------------------------------------------------------------------------- #
# Sidebar parameter panel & main
# --------------------------------------------------------------------------- #
def _benchmark_parameters() -> tuple:
    """The benchmark's four levers, as a sidebar form.

    A form means dragging a slider costs nothing until **Apply** — the 60-day
    re-settle only runs on an explicit submit. The chosen values are kept in
    ``st.session_state`` so they survive switching to pages that don't render
    the panel (fleet, methodology).
    """
    cfg = bess_config()
    durations = list(REFERENCE_DURATIONS)
    saved = st.session_state.setdefault(
        "bench_params",
        {
            "duration": REFERENCE_DURATION,
            "cycles": float(cfg.get("target_daily_cycles") or 1.5),
            "degradation": float(cfg["degradation_cost_per_mwh"]),
            "soc": (int(cfg["min_soc_pct"] * 100), int(cfg["max_soc_pct"] * 100)),
        },
    )

    with st.sidebar:
        st.markdown("**Benchmark battery**")
        with st.form("bench_params_form"):
            duration = st.radio(
                "Duration",
                durations,
                index=durations.index(saved["duration"]),
                horizontal=True,
                help=(
                    f"Hours of storage at {REFERENCE_POWER_MW:.0f} MW — e.g. 2h "
                    f"means a {REFERENCE_POWER_MW * 2:.0f} MWh battery."
                ),
            )
            cycles = st.slider(
                "Cycle target (cycles/day)",
                0.5,
                3.0,
                saved["cycles"],
                0.5,
                help=(
                    "Cap on average daily throughput. More cycles chase more "
                    "spread but wear the battery harder."
                ),
            )
            degradation = st.slider(
                "Degradation cost (£/MWh)",
                0.0,
                20.0,
                saved["degradation"],
                0.5,
                help=(
                    "Wear-and-tear charged per MWh cycled; higher values make "
                    "the optimiser pickier about which spreads to trade."
                ),
            )
            soc = st.slider(
                "SOC band (%)",
                0,
                100,
                saved["soc"],
                5,
                help=(
                    "Allowed state-of-charge range. A narrow band protects the "
                    "cells but shrinks the tradable energy."
                ),
            )
            if st.form_submit_button("Apply", type="primary", width="stretch"):
                st.session_state["bench_params"] = {
                    "duration": duration,
                    "cycles": cycles,
                    "degradation": degradation,
                    "soc": soc,
                }
        with st.expander("Fixed assumptions"):
            st.caption(
                f"Slippage £{cfg.get('execution', {}).get('slippage', 0):.2f}/MWh · "
                f"round-trip {cfg['charge_efficiency'] * cfg['discharge_efficiency']:.0%} · "
                f"{REFERENCE_POWER_MW:.0f} MW power · last {_MAX_HISTORY_DAYS} days "
                "(the full free Nord Pool window). Applying a lever re-settles "
                "the whole simulation."
            )

    p = st.session_state["bench_params"]
    return p["duration"], p["cycles"], p["degradation"], p["soc"][0] / 100.0, p["soc"][1] / 100.0


def main():
    st.set_page_config(
        page_title="Live GB BESS",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    pages = {
        "Simulated benchmark": [
            st.Page(
                _page_latest,
                title="Latest day",
                icon=":material/bolt:",
                url_path="latest",
                default=True,
            ),
            st.Page(
                _page_history,
                title="History",
                icon=":material/monitoring:",
                url_path="history",
            ),
            st.Page(
                _page_day_types,
                title="Day types",
                icon=":material/partly_cloudy_day:",
                url_path="day-types",
            ),
        ],
        "Real GB fleet": [
            st.Page(
                _page_fleet,
                title="Fleet performance",
                icon=":material/battery_charging_full:",
                url_path="fleet",
            ),
        ],
        "About": [
            st.Page(
                _page_methodology,
                title="Methodology",
                icon=":material/menu_book:",
                url_path="methodology",
            ),
        ],
    }
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
