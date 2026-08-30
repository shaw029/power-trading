"""Live GB BESS benchmark — interactive Streamlit dashboard.

Fetches recent GB market data live (Nord Pool N2EX day-ahead prices + Elexon
MID / generation / demand — both public, no API key), settles the reference
battery with user-chosen parameters, and renders a sidebar-navigated app
grouped by epistemic status: the Benchmark (Day briefing / History), the
observed GB power system (System overview / Fleet performance), the Research
analyses (Market regimes / Execution gap / Alignment gap) and the
methodology. Because the engine re-runs on each parameter change, the
dashboard is interactive rather than precomputed; it is meant to run on
Streamlit Cloud.

Global filters (period + day types) and the benchmark's five levers — duration,
cycle target, degradation cost, the SOC band and the DA commitment — live in
the sidebar; every other modelling choice (MID basis, slippage, efficiency,
power rating) is a fixed, stated assumption.

Run with ``streamlit run dashboard/live_app.py``.
"""

import datetime as dt
from concurrent import futures
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.charts import (  # noqa: E402
    chart_cycles_vs_revenue,
    chart_capture_spread_daily,
    chart_daily_attribution,
    chart_daytype_capture,
    chart_daytype_frequency,
    chart_daytype_matrix,
    chart_daytype_market_reliance,
    chart_daytype_yield_wear,
    chart_daytype_profiles,
    chart_daytype_ratio,
    chart_fleet_by_optimiser,
    chart_fleet_by_region,
    chart_fleet_daily,
    chart_fleet_dispersion,
    chart_fleet_leaderboard,
    chart_fleet_spread,
    chart_generation_daily,
    chart_renewable_daily,
    chart_generation_mix,
    chart_operation_explorer,
    chart_pnl_waterfall,
    chart_price_capture,
    chart_price_volatility,
    chart_stress_frequency,
    chart_stress_vs_demand,
    chart_realized_shape,
    chart_alignment_day,
    chart_alignment_scatter,
    chart_gap_by_daytype,
    chart_margin_response,
    chart_system_tightness,
    chart_shape_overlay,
    chart_sim_vs_fleet_daily,
    chart_sim_vs_fleet_sites,
)
from fleet import fetch_fleet  # noqa: E402
from fleet.registry import REGISTRY as FLEET_POPULATION  # noqa: E402
from fleet import performance as fleet_perf  # noqa: E402
from live import classify as classify_mod  # noqa: E402
from live import fetch_live  # noqa: E402
from live import resilience  # noqa: E402
from live.assets import (  # noqa: E402
    DEFAULT_START_SOC,
    REFERENCE_DURATION,
    REFERENCE_DURATIONS,
    REFERENCE_POWER_MW,
    bess_config,
)
from live.settle import settle_day  # noqa: E402
from src.bess.bess_asset import BESSAsset  # noqa: E402

SCOPE = """
This dashboard is the **presentation tier** of a two-tier project. It is built to be
read at a glance and to stay responsive on free hosting, which sets what it can show.

| | **This dashboard** | **Research notebooks** |
|---|---|---|
| Purpose | Present and communicate | Detailed research |
| Battery fleet | 51 sites, 4,091 MW — 66% of GB BM-registered battery MW | Full census — 87 sites, 6,234 MW |
| Window | Rolling 60 days | 2023-10-01 onward (~1,050 days) |
| Revenue streams | Wholesale proxy + Balancing Mechanism | Adds per-unit ancillary (response and reserve) |
| Data | Fetched live, cached per day | Complete day-file archive, backfilled to 100% |

**Neither tier is a cut-down of the other — they answer different questions.** The
dashboard shows what the GB market is doing now. The notebooks establish what is true of
the fleet as a whole, which needs a multi-year window no interactive app can carry.

**What that means when reading these numbers.** The 51 sites here are **66% of GB
BM-registered battery MW**. Two filters produce that list — a published energy
capacity, and enough cycling to be priceable from wholesale and BM alone:

| Site size | MW covered |
|---|---|
| 200 MW and above | 64% |
| 100–200 MW | 75% |
| 50–100 MW | 79% |
| 20–50 MW | 42% |
| Under 20 MW | 15% |

So fleet figures here describe GB grid-scale storage closely, and describe the sub-50 MW
tail poorly. What is missing is not a random sample: it is small sites, plus every
battery traded behind an aggregator or supplier unit, which has no per-unit feed at all
and sits outside even the denominator. The census behind these numbers is in
`notebooks/06_fleet_coverage_census.ipynb`; the tier split is in `DATA_ARCHITECTURE.md`.

*Coverage figures are a July 2026 snapshot computed in the notebook. This page states
them rather than recomputing them — keeping the census out of the dashboard's process is
what keeps this tier light.*
"""

METHODOLOGY = """
A **transparent simulation** — no real money, broker or orders. Every figure is
the settlement engine run over published market data.

- **Asset** — one 50 MW battery; the parameter panel picks its duration
  (1h / 2h / 4h).
- **Data (live, free)** — Nord Pool N2EX day-ahead price; Elexon MID price plus
  generation and demand for day-type context; Sheffield Solar PV_Live for GB
  embedded solar (Elexon's transmission-metered mix carries no solar at all);
  Elexon LoLP / de-rated margin and the NESO Capacity Market Notice register
  for system tightness.
- **Trading** — the day-ahead schedule optimises against the actual cleared DA
  price (published the day before, so legitimate information). The intraday
  layer then re-optimises against the realised MID curve with **perfect
  foresight** — an idealised best case, not a live-replicable strategy.
- **Levers** — duration, cycle target, degradation cost, SOC band, and the
  **DA commitment** (the market-allocation lever: how much of the battery the
  day-ahead auction may commit; the rest is held back for intraday). Fixed:
  slippage, round-trip efficiency, 50 MW power.
- **Out of scope** — real execution, imbalance settlement, and any fees beyond
  the slippage and degradation modelled. Illustrative, not a guarantee of
  replicable returns.
"""

RESOLUTION_H = 1.0
# Nord Pool serves recent GB day-ahead prices without a subscription back to
# roughly 65 days; 60 leaves a safety margin. Older days simply 401 → their DA
# frame comes back empty and the day is skipped, so the window self-trims.
_MAX_HISTORY_DAYS = 60
# Parallel day downloads for the per-unit feeds. Six is enough to hide the
# cashflow endpoint's latency (the measured 5.8x) while staying a modest
# neighbour to Elexon — the window is at most 60 days, not thousands.
_FLEET_FETCH_WORKERS = 6
# Below this many half-hours the margin quantiles are noise, not bands.
_MARGIN_BAND_MIN_PERIODS = 96


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


def _make_cfg(cycle_target, degradation, soc_min, soc_max, commit) -> dict:
    cfg = dict(bess_config())
    cfg.update(
        target_daily_cycles=cycle_target,
        degradation_cost_per_mwh=degradation,
        min_soc_pct=soc_min,
        max_soc_pct=soc_max,
        resolution_h=RESOLUTION_H,
        da_commit_fraction=commit,
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


def _warm_fetch(date_isos: tuple, system_isos: tuple | None = None) -> None:
    """Pre-fetch the days we need, with a progress bar over what is missing.

    ``date_isos`` are the days needing *prices*; ``system_isos`` the days
    needing the generation/demand snapshot, which is display-only and so is
    usually just the days on screen.

    Warmed days are tracked individually rather than behind a single
    "warmed once" flag. That flag meant only the first page visited in a
    session ever drew a bar — every later page fetched in silence, and
    widening the filter refetched in silence too. Tracking the days makes the
    rule simple and the same everywhere: work you have not done yet shows a
    bar, work already cached does not.
    """
    system_isos = date_isos if system_isos is None else system_isos
    warmed_prices: set[str] = st.session_state.setdefault("_warmed_prices", set())
    warmed_system: set[str] = st.session_state.setdefault("_warmed_system", set())

    todo_prices = {iso for iso in date_isos if iso not in warmed_prices}
    todo_system = {iso for iso in system_isos if iso not in warmed_system}
    todo = sorted(todo_prices | todo_system)
    if not todo:
        return

    n = len(todo)
    bar = st.progress(0.0, text=f"Fetching {n} day(s) of GB market data…")
    for i, iso in enumerate(todo):
        if iso in todo_prices:
            try:
                _fetch_day(iso)
            except Exception:
                pass  # _settle_range skips unfetchable days
        if iso in todo_system:
            try:
                _system_day(iso)
            except Exception:
                pass
        bar.progress((i + 1) / n, text=f"Fetching GB market data · {iso} ({i + 1}/{n})")
    bar.empty()
    warmed_prices |= todo_prices
    warmed_system |= todo_system


@st.cache_data(show_spinner="Settling the benchmark battery…")
def _settle_range(date_isos: tuple, duration, cycle_target, degradation, soc_min, soc_max, commit):
    """Settle every day in ``date_isos`` (oldest first) carrying SOC forward, for
    the single selected ``duration``.

    Cached on the dates, the duration and the five parameter levers, so the engine
    only re-runs when one of those actually changes. Returns one record per
    settled day with its result, context and labels.
    """
    cfg = _make_cfg(cycle_target, degradation, soc_min, soc_max, commit)
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
        pn = fetch_fleet.fetch_fleet_pn(date, FLEET_POPULATION)
        mid = fetch_fleet.fetch_day_mid_prices(date)
    except Exception:
        return pd.DataFrame()
    if not pn or mid.empty:
        return pd.DataFrame()
    try:
        cashflows = fetch_fleet.fetch_fleet_bm_cashflows(date, FLEET_POPULATION)
    except Exception:
        cashflows = {"bid": [], "offer": []}
    # Acceptances correct the notified position into actual delivery. A day
    # whose acceptances have not published yet falls back to PN alone rather
    # than dropping the day.
    try:
        boalf = fetch_fleet.fetch_fleet_boalf(date, FLEET_POPULATION)
    except Exception:
        boalf = []
    return fleet_perf.day_site_metrics(
        date_iso, pn, cashflows, mid, boalf, population=FLEET_POPULATION
    )


def _prefetch_fleet_days(date_isos: list[str], bar) -> None:
    """Download the per-unit Elexon day files for ``date_isos`` in parallel.

    The per-unit feeds are the dashboard's whole download cost — roughly 2.9 MB
    a day against a few hundred KB for everything else — and most of that time
    is the cashflow endpoint's per-request latency rather than bandwidth. Days
    are independent, so overlapping them turns a cold window from a queue into
    one round trip: measured 19.4s -> 3.3s over six cold days.

    Deliberately narrow, for safety:

    * Workers call only the raw fetchers, which are plain functions writing one
      JSON file per feed per day. No Streamlit API is touched off the main
      thread — the bar below is advanced by the main thread as futures land.
    * Each day's files are written by exactly one worker and are not read until
      the pool has drained, so no reader can see a half-written file. Prices go
      through a fetcher that reads across its whole directory, which is why
      they are left sequential rather than parallelised here.
    * A day that fails is swallowed exactly as the sequential path swallows it:
      ``_fleet_day`` already treats an unavailable day as an empty frame.
    """
    if not date_isos:
        return
    n = len(date_isos)

    def one_day(iso: str) -> str:
        date = dt.date.fromisoformat(iso)
        for fetch in (
            fetch_fleet.fetch_fleet_pn,
            fetch_fleet.fetch_fleet_boalf,
            fetch_fleet.fetch_fleet_bm_cashflows,
        ):
            try:
                fetch(date, FLEET_POPULATION)
            except Exception:
                pass
        try:
            fetch_fleet.fetch_day_mid_prices(date)   # market-wide, no population
        except Exception:
            pass
        return iso

    with futures.ThreadPoolExecutor(max_workers=_FLEET_FETCH_WORKERS) as pool:
        pending = [pool.submit(one_day, iso) for iso in date_isos]
        for done, future in enumerate(futures.as_completed(pending), start=1):
            if bar is not None:
                bar.progress(
                    done / n * 0.8,
                    text=f"Fetching per-unit Elexon data · {done}/{n} days",
                )


def _fleet_range(date_isos: tuple) -> pd.DataFrame:
    """All per-site fleet metrics over ``date_isos``, with a first-load
    progress bar (per-day results are cached, so later runs are cheap).

    Two phases: download every missing day at once, then reconstruct delivery
    day by day. The split exists because only the first phase is I/O — the
    second is CPU on files already local, and cached per day.
    """
    show_bar = not st.session_state.get("_fleet_warmed")
    n = len(date_isos)
    bar = st.progress(0.0, text=f"First load — fetching per-unit Elexon data for {n} days…") if show_bar else None

    fetched: set[str] = st.session_state.setdefault("_fleet_fetched", set())
    todo = [iso for iso in date_isos if iso not in fetched]
    _prefetch_fleet_days(todo, bar)
    fetched.update(todo)

    frames = []
    for i, iso in enumerate(date_isos):
        day = _fleet_day(iso)
        if not day.empty:
            frames.append(day)
        if bar is not None:
            bar.progress(
                0.8 + (i + 1) / n * 0.2,
                text=f"Reconstructing delivery · {iso} ({i + 1}/{n})",
            )
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
    # Throughput comes from the dispatch log rather than the result summary,
    # so the benchmark can report the same capture spread the fleet page does.
    discharge_mwh = sum(
        max(entry["final_mw"], 0.0) for entry in dur_result.dispatch_log
    ) * RESOLUTION_H
    return {
        "date": date_iso,
        "benchmark_da_revenue": dur_result.benchmark_da_revenue,
        "intraday_da_improvement": dur_result.intraday_da_improvement,
        "execution_costs_paid": dur_result.execution_costs_paid,
        "degradation_cost": dur_result.degradation_cost,
        "net_pnl": dur_result.net_pnl,
        "discharge_mwh": discharge_mwh,
        # Gross of wear and slippage, matching the fleet page — its estimate is
        # revenue before costs too, so a net-of-cost figure here would not be
        # the same measure. It also keeps the degradation line on the chart
        # meaningful: subtracting wear from the margin and then comparing that
        # margin to wear counts it twice.
        "capture_spread": (
            (dur_result.benchmark_da_revenue + dur_result.intraday_da_improvement)
            / discharge_mwh
            if discharge_mwh > 0
            else float("nan")
        ),
    }


# --------------------------------------------------------------------------- #
# Page chrome & shared benchmark view
# --------------------------------------------------------------------------- #
def _page_header(title: str, subtitle: str) -> None:
    """Every page opens the same way: a heading and one quiet status line."""
    st.markdown(f"### {title}")
    st.caption(subtitle)


# Days settled ahead of the selected window so state of charge is carried in
# rather than assumed. One day would do most of it; three is cheap insurance.
_SETTLE_WARMUP_DAYS = 3


def _settle_window(date_isos: tuple, start: str, end: str) -> tuple:
    """The selected days, preceded by a short state-of-charge run-up."""
    selected = [d for d in date_isos if start <= d <= end]
    if not selected:
        return tuple(selected)
    first = date_isos.index(selected[0])
    return tuple(date_isos[max(0, first - _SETTLE_WARMUP_DAYS):date_isos.index(selected[-1]) + 1])


def _benchmark_view():
    """Sidebar controls + settled days shared by the three benchmark pages.

    Returns ``(params, shown_days, window_caption)`` — or ``None`` after
    rendering the appropriate empty-state message, so each page can simply
    bail out.
    """
    date_isos = _dates()
    start, end, day_types = _global_filters(date_isos)
    duration, cycle_target, degradation, soc_min, soc_max, commit = _benchmark_parameters()

    # Settle the selected window plus a few days in front of it, not the whole
    # history. The engine carries state of charge from one day into the next,
    # so starting cold at the window edge would misstate its first day; a short
    # run-up establishes that state and is then filtered back out. Picking 7
    # days should cost seven days of work, not sixty.
    settle_isos = _settle_window(date_isos, start, end)
    _warm_fetch(settle_isos, system_isos=tuple(d for d in date_isos if start <= d <= end))
    days = _settle_range(settle_isos, duration, cycle_target, degradation, soc_min, soc_max, commit)
    shown = _filter_days(days, start, end, day_types)

    if not days:
        st.warning("No days could be settled — live data may be temporarily unavailable.")
        return None
    if not shown:
        st.info("No settled days match the current filters — widen the period or day types.")
        return None

    tags = ", ".join(day_types) if day_types else "all regimes"
    caption = (
        f"{shown[0]['date']} → {shown[-1]['date']} · {len(shown)} day(s) · {tags} · "
        f"{duration} × {REFERENCE_POWER_MW:.0f} MW simulated battery"
    )
    if commit < 1.0:
        caption += f" · {commit:.0%} committed day-ahead"
    params = {
        "duration": duration,
        "cycle_target": cycle_target,
        "degradation": degradation,
        "soc_min": soc_min,
        "soc_max": soc_max,
        "commit": commit,
    }
    return params, shown, caption


def _range_dispatch(days, duration) -> pd.DataFrame:
    """One continuous dispatch frame spanning every settled day in order."""
    frames = [_dispatch_frame(d["date"], d["result"].durations[duration]) for d in days]
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Benchmark pages
# --------------------------------------------------------------------------- #
def _page_day():
    """The daily briefing: one day, holistically — market context, dispatch,
    earnings and system alignment. The page owns the app's only day picker;
    sidebar filters define the window it picks from."""
    view = _benchmark_view()
    if view is None:
        return
    params, shown, caption = view
    duration = params["duration"]

    _page_header("Daily summary", caption)

    dates = [d["date"] for d in shown]
    # The picker persists across pages/filters; a filter change that strands
    # the chosen day snaps back to the latest day in the window.
    if st.session_state.get("briefing_day") not in dates:
        st.session_state.pop("briefing_day", None)
    picked = st.selectbox(
        "Day",
        options=dates,
        index=len(dates) - 1,
        key="briefing_day",
        help="Defaults to the latest settled day — pick any other day for its "
        "full briefing.",
    )
    record = next(d for d in shown if d["date"] == picked)
    dur_result = record["result"].durations[duration]
    if record["labels"]:
        st.write(" ".join(f"`{label}`" for label in record["labels"]))

    window_mean = sum(
        d["result"].durations[duration].net_pnl for d in shown
    ) / len(shown)
    row = _pnl_row(record["date"], dur_result)
    _da_prices_day = [e["da_price_actual"] for e in dur_result.dispatch_log]
    # P90−P10 rather than high−low: one freak print sets the peak-to-trough, and
    # a battery cannot trade a single half-hour anyway. The deciles describe the
    # spread a full charge/discharge block could actually reach. The outright
    # extremes stay visible in the peak & floor tile beside it.
    _da_px = pd.Series(_da_prices_day, dtype=float)
    _da_spread = (
        float(_da_px.quantile(0.90) - _da_px.quantile(0.10)) if len(_da_px) else 0.0
    )

    # Grid context for this day. Stress comes from the window-wide classifier,
    # so "stressed" means stressed relative to the period on screen.
    flags = _window_flags(tuple(dates))
    day_date = dt.date.fromisoformat(picked)
    day_flags = flags[flags.index.date == day_date] if not flags.empty else flags
    day_system = _system_day(picked)

    # Three groups: the model, the grid, the real fleet.
    st.markdown("**Baseline optimiser**")
    opt = st.columns(4)
    opt[0].metric(
        _unit_label("Net PnL", "£/MW"),
        f"{dur_result.net_pnl / REFERENCE_POWER_MW:,.0f}",
        f"{(dur_result.net_pnl - window_mean) / REFERENCE_POWER_MW:+,.0f} vs window avg",
        help="Day-ahead revenue + intraday improvement − execution and degradation "
        f"costs, per MW of the {REFERENCE_POWER_MW:.0f} MW asset "
        f"(£{dur_result.net_pnl:,.0f} absolute).",
    )
    opt[1].metric(
        _unit_label("Intraday improvement", "£/MW"),
        f"{dur_result.intraday_da_improvement / REFERENCE_POWER_MW:,.0f}",
        f"{dur_result.intraday_da_improvement / dur_result.net_pnl:.0%} of net PnL"
        if dur_result.net_pnl else None,
        delta_color="off",
        help="What re-optimising against the realised intraday price added on top "
        "of the frozen day-ahead schedule. The engine has perfect foresight of "
        "that price, so read it as an upper bound, not a target.",
    )
    _da_committed = sum(mw for mw in dur_result.da_schedule if mw > 0)
    _da_budget = (
        params["cycle_target"] * REFERENCE_POWER_MW * _duration_hours(duration)
        * params["commit"]
    )
    opt[2].metric(
        "Cycles",
        f"{dur_result.cycles:.2f}",
        f"target ≤ {params['cycle_target']:.1f}",
        delta_color="off",
        help=(
            "Physical cycles this day: discharged MWh ÷ nameplate MWh. The "
            f"locked day-ahead leg separately committed {_da_committed:,.0f} MWh "
            f"of its {_da_budget:,.0f} MWh allocation "
            f"({params['commit']:.0%} of the cycle budget)."
        ),
    )
    opt[3].metric(
        _unit_label("Capture spread", "£/MWh"),
        f"{row['capture_spread']:,.1f}" if pd.notna(row["capture_spread"]) else "—",
        help="Gross trading margin on every MWh physically discharged today, "
        "before wear and slippage. Shares units with the degradation lever "
        f"(£{params['degradation']:,.1f}/MWh), so a day below that earned less "
        "per MWh than cycling cost it.",
    )

    st.markdown("**GB system**")
    sysc = st.columns(4)
    sysc[0].metric(
        _unit_label("DA P90−P10 spread", "£/MWh"),
        f"{_da_spread:,.0f}",
        help="The day's dearest decile of day-ahead prices minus its cheapest — "
        "the arbitrage opportunity a battery could actually work, with single "
        "freak half-hours excluded.",
    )
    sysc[1].metric(
        _unit_label("Peak & floor price", "£/MWh"),
        f"{max(_da_prices_day):,.0f} / {min(_da_prices_day):,.0f}"
        if _da_prices_day else "—",
        help="The dearest and cheapest hours the day-ahead auction cleared today. "
        "A negative floor means generators paid to keep running.",
    )
    if not day_flags.empty:
        _stress_hh = int(day_flags["stress"].sum())
        sysc[2].metric(
            _unit_label("Peak residual load", "GW"),
            f"{float(day_flags['residual_mw'].max()) / 1000.0:,.1f}",
            f"{_stress_hh} stress half-hour(s)" if _stress_hh else "no stress periods",
            delta_color="off",
            help="The tightest the grid got today: demand minus wind and solar, "
            "the most the rest of the fleet had to carry. Stress is the top "
            "decile of residual load across the window shown.",
        )
    else:
        sysc[2].metric(_unit_label("Peak residual load", "GW"), "—")
    if not day_system.empty:
        _groups = fetch_live.group_generation(day_system)
        _gen = [g for g in _groups.columns if g != "Interconnectors"]
        _total = float(_groups[_gen].to_numpy().sum())
        _renew = float(
            _groups[[g for g in _gen if g in fetch_live.RENEWABLE_GROUPS]].to_numpy().sum()
        )
        sysc[3].metric(
            "Renewable share",
            f"{_renew / _total:.0%}" if _total > 0 else "—",
            help="Wind, solar, hydro and biomass as a share of GB generation "
            "today. Grounds the price volatility beside it — the cheap hours "
            "are usually the windy ones.",
        )
    else:
        sysc[3].metric("Renewable share", "—")

    st.markdown("**Real GB fleet**")
    fleet_day = _fleet_day(picked)
    flt = st.columns(4)
    if fleet_day.empty:
        flt[0].metric(_unit_label("Fleet median PnL", "£/MW"), "—")
        flt[1].metric(_unit_label("Operator dispersion", "£/MW"), "—")
        flt[2].metric("Fleet median cycles", "—")
        flt[3].metric("Top real site", "—")
    else:
        fleet_day = fleet_day.assign(
            cycles=fleet_day["discharge_mwh"] / fleet_day["capacity_mwh"]
        )
        median_gbp = float(fleet_day["gbp_per_mw"].median())
        best = fleet_day.loc[fleet_day["gbp_per_mw"].idxmax()]
        flt[0].metric(
            _unit_label("Fleet median PnL", "£/MW"),
            f"{median_gbp:,.0f}",
            f"{len(fleet_day)} sites reporting",
            delta_color="off",
            help="What the typical real GB battery earned today, from public data "
            "(delivered output × MID + balancing cashflows). Ancillary income "
            "is invisible here, so sites trading it read low.",
        )
        _spread = fleet_day["gbp_per_mw"]
        _iqr = (
            float(_spread.quantile(0.75) - _spread.quantile(0.25))
            if len(_spread) >= 4 else None
        )
        flt[1].metric(
            _unit_label("Operator dispersion", "£/MW"),
            f"{_iqr:,.0f}" if _iqr is not None else "—",
            help="Interquartile spread (P75 − P25) across the real batteries "
            "today — what operator skill and siting were worth on this day, "
            "measured where one exceptional site cannot move it. The same "
            "measure the fleet page reports. Needs at least four sites.",
        )
        flt[2].metric(
            "Fleet median cycles",
            f"{float(fleet_day['cycles'].median()):.2f}",
            f"sim {dur_result.cycles:.2f}",
            delta_color="off",
            help="How hard the typical real battery worked today, with the "
            "simulation's own cycles beside it.",
        )
        flt[3].metric(
            "Top real site",
            best["site"],
            f"{best['optimiser']} · £{best['gbp_per_mw']:,.0f}/MW",
            delta_color="off",
            help="The best-earning real battery today and the party trading it.",
        )

    dispatch = _dispatch_frame(record["date"], dur_result)
    prices_hourly = _prices_hourly(dispatch)
    da_sched = _da_sched_frame(dispatch)

    left, right = st.columns(2)
    left.plotly_chart(
        chart_realized_shape(dispatch, prices_hourly, da_sched), width="stretch"
    )
    right.plotly_chart(
        chart_pnl_waterfall(pd.DataFrame([_pnl_row(record["date"], dur_result)])),
        width="stretch",
    )

    system = _system_day(picked)
    if system.empty:
        st.info("No system data available for this day.")
    else:
        groups = fetch_live.group_generation(system)
        demand = system["demand_actual"] if "demand_actual" in system.columns else None
        st.plotly_chart(chart_generation_mix(groups, demand), width="stretch")

    # Fleet dispersion. fleet_day is loaded for the fleet KPIs above and already
    # carries `cycles` on the non-empty branch, so this costs only the chart.
    if not fleet_day.empty:
        st.plotly_chart(
            chart_fleet_dispersion(
                fleet_day,
                dur_result.cycles,
                dur_result.net_pnl / REFERENCE_POWER_MW,
            ),
            width="stretch",
        )

    with st.expander("Fleet this day"):
        if fleet_day.empty:
            st.info("No fleet data available for this day.")
        else:
            top = fleet_day.nlargest(5, "gbp_per_mw")[
                ["site", "optimiser", "gbp_per_mw"]
            ].rename(
                columns={"site": "Site", "optimiser": "Optimiser",
                         "gbp_per_mw": "£/MW"}
            )
            st.caption("Top real sites by estimated £/MW on this day "
                       "(wholesale + BM; see Fleet performance for scope).")
            st.dataframe(
                top.style.format({"£/MW": "£{:,.0f}"}),
                width="stretch",
                hide_index=True,
            )


def _page_history():
    view = _benchmark_view()
    if view is None:
        return
    params, shown, caption = view
    duration = params["duration"]

    rows = [_pnl_row(d["date"], d["result"].durations[duration]) for d in shown]
    results_df = pd.DataFrame(rows)
    _page_header("Baseline optimiser performance", caption)

    net = results_df["net_pnl"]
    best_i = int(net.idxmax())
    spread = pd.to_numeric(results_df["capture_spread"], errors="coerce").dropna()
    uplift = results_df["intraday_da_improvement"]
    cols = st.columns(4)
    cols[0].metric(
        _unit_label("Avg net PnL", "£/MW/day"),
        f"{net.mean() / REFERENCE_POWER_MW:,.0f}",
        help="Average daily net PnL per MW over the shown window — the unit every "
        "page (and the fleet estimates) reports revenue in.",
    )
    cols[1].metric(
        _unit_label("Avg intraday improvement", "£/MW/day"),
        f"{uplift.mean() / REFERENCE_POWER_MW:,.0f}",
        f"{uplift.sum() / net.sum():.0%} of net PnL" if net.sum() else None,
        delta_color="off",
        help="What re-optimising against the realised intraday price added on top "
        "of the frozen day-ahead schedule, per MW per day. The delta is its "
        "share of net PnL. Read it as an upper bound: the intraday engine has "
        "perfect foresight of the MID curve, which no live trader has.",
    )
    cols[2].metric(
        _unit_label("Avg capture spread", "£/MWh"),
        f"{spread.mean():,.1f}" if len(spread) else "—",
        help="Gross trading margin on every MWh physically discharged, averaged "
        "over the shown days — revenue before wear and slippage, matching the "
        "fleet estimate so the simulated battery and the real ones compare on "
        "the same footing. Energy that was traded and reversed without moving "
        "(a day-ahead position closed intraday) earns no MWh here.",
    )
    worst_i = int(net.idxmin())
    cols[3].metric(
        _unit_label("Best / worst day", "£/MW"),
        f"{net.max() / REFERENCE_POWER_MW:,.0f} / {net.min() / REFERENCE_POWER_MW:,.0f}",
        f"{results_df.loc[best_i, 'date']} · {results_df.loc[worst_i, 'date']}",
        delta_color="off",
        help="Best and worst single-day net PnL per MW in the shown window, with "
        "their dates in the same order. The spread between them is how much "
        "of the average depends on a handful of days.",
    )

    st.plotly_chart(chart_daily_attribution(results_df), width="stretch")
    st.plotly_chart(
        chart_capture_spread_daily(results_df, params["degradation"]), width="stretch"
    )

    # Price-capture profile over the whole range, as a per-day average: totals
    # here would say more about how many days were selected than about the
    # battery.
    dispatch = _range_dispatch(shown, duration)
    st.plotly_chart(
        chart_price_capture(dispatch, duration_h=RESOLUTION_H, days=len(shown)),
        width="stretch",
    )

    # Dispatch explorer over exactly the days the sidebar selected — the same
    # window every other chart on this page uses.
    st.markdown("#### Dispatch explorer")
    st.caption("Hour-by-hour prices, trades and state of charge over the selected days.")
    win_dispatch = _range_dispatch(shown, duration)
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

    _page_header("Market regimes", caption)
    st.caption(
        "Every settled day carries a flat set of tags from two independent "
        "families: **fundamentals** — the physics of what the weather and demand "
        "did (`wind-led`, `wind-drought`, `solar-led`, `high-demand`, "
        "`low-demand`, `weekend`) — and **price traits**, how the market reacted "
        "(`volatile`, `flat`, `negative-price`, `two-peak`, `single-peak`). A day "
        "holds as many as fit and counts under each, so read these as regime "
        "views, not disjoint buckets. Composite regimes need no label of their "
        "own: a scarcity day is where `wind-drought` and `volatile` overlap, "
        "which the crossing chart below shows directly."
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
                    # Carried per membership so the yield/wear and reliance
                    # views aggregate over exactly the days a tag covers.
                    "gbp_per_mw": dur_result.net_pnl / REFERENCE_POWER_MW,
                    "cycles": dur_result.cycles,
                    "da_gbp": dur_result.benchmark_da_revenue,
                    "intraday_gbp": dur_result.intraday_da_improvement,
                }
            )
        for d in drivers or ["(none)"]:
            for p in price_tags or ["(none)"]:
                key = (d, p)
                matrix_counts[key] = matrix_counts.get(key, 0) + 1
        # Every regime, both families — the same coverage the reliance chart
        # has, so the two read as one pair. A fundamental's average does mix
        # price characters, but that mixing is the question: whether a
        # wind-drought day has a shape of its own is not answerable if only
        # price traits are ever drawn.
        for tag in labels or ["untagged"]:
            for i, entry in enumerate(dur_result.dispatch_log):
                profile_rows.append(
                    {
                        "hour": i % 24,
                        "soc": entry["soc_after"],
                        # What the re-optimiser moved away from the locked
                        # day-ahead schedule in this hour. Same loop, because
                        # the dispatch log already carries both legs.
                        "deviation": entry["final_mw"] - entry["da_mw"],
                        "day_type": tag,
                    }
                )
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

    memberships = pd.DataFrame(membership_rows)
    # Capture judges strategy fit with the opportunity normalised away; yield
    # and wear put the money and the cycles back. They answer the same question
    # from opposite ends, so they belong side by side. Both aggregate the same
    # membership rows, so a day counts under every tag it carries.
    per_tag = memberships.groupby(["tag", "family"], as_index=False).agg(
        gbp_per_mw=("gbp_per_mw", "mean"),
        cycles=("cycles", "mean"),
        days=("date", "nunique"),
        da_gbp=("da_gbp", "sum"),
        intraday_gbp=("intraday_gbp", "sum"),
    )
    left, right = st.columns(2)
    left.plotly_chart(chart_daytype_capture(memberships), width="stretch")
    right.plotly_chart(chart_daytype_yield_wear(per_tag), width="stretch")

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

    # Shape beside source: when the battery held charge, and which market it
    # earned in. Reliance is a share of the gross legs, so a tag whose two legs
    # cancel to nothing has no meaningful split and is dropped rather than
    # drawn at 50/50.
    reliance = per_tag.assign(gross=per_tag["da_gbp"] + per_tag["intraday_gbp"])
    reliance = reliance[reliance["gross"] > 0]
    shape_col, market_col = st.columns(2)
    families = dict(zip(memberships["tag"], memberships["family"]))
    profiles_df = pd.DataFrame(profile_rows)
    shape_col.plotly_chart(
        chart_daytype_profiles(profiles_df, families=families), width="stretch"
    )
    if reliance.empty:
        market_col.info("No regime earned enough to split day-ahead from intraday.")
    else:
        market_col.plotly_chart(
            chart_daytype_market_reliance(
                reliance.assign(
                    da_share=reliance["da_gbp"] / reliance["gross"],
                    intraday_share=reliance["intraday_gbp"] / reliance["gross"],
                )
            ),
            width="stretch",
        )

    # Reliance says how much of the money came from intraday; this says when
    # the re-optimiser went looking for it. Same rows, a different column.
    st.plotly_chart(
        chart_daytype_profiles(
            profiles_df,
            value_col="deviation",
            value_label="Mean deviation from the DA schedule (MW)",
            value_tickformat=None,
            families=families,
            title="Intraday re-optimisation by hour — when the plan was rewritten",
        ),
        width="stretch",
    )

    st.markdown("#### Days behind the tags")
    table = pd.DataFrame(table_rows).sort_values("date", ascending=False).rename(
        columns={
            "date": "Date",
            "tags": "Tags",
            "gbp_per_mw": "£/MW/day",
            "capture": "Capture",
            "cycles": "Cycles",
        }
    )
    st.dataframe(
        table.style.format({"£/MW/day": "£{:,.0f}", "Capture": "{:.0%}", "Cycles": "{:.2f}"}),
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
- **Excluded here (by design)** — ancillary services, capacity market and
  private PPAs. Ancillary revenue *is* obtainable per unit from NESO's auction
  results, and the research notebooks price it, but its history is fragmented
  across three publishing eras with real gaps — folding that into a live
  rolling view would mislead more than it informs. This tier scopes to the two
  streams it can estimate consistently from one source every day; the full
  stack is in the notebooks. Traded PPA prices are private and out of reach of
  either tier.
- **Ancillary-tilted sites can read *negative*, not just low** — energy bought
  to hold state of charge for an ancillary contract is costed at MID here,
  while the availability payment that motivated it is invisible. Sites cycling
  below ~0.3 cycles/day are flagged ⚠ in the site table: their revenue likely
  comes from markets this model cannot see, so don't read their £ figures as
  trading performance.
- **Which batteries are on this dashboard** — every BM-registered GB battery
  the census can identify **whose energy capacity is known and which cycles
  enough to price**: 51 sites, 77 BM Units, 4,091 MW, or 66% of BM-registered
  battery MW.

  Two filters produce that list, and they do different jobs. *BM registration*
  is a hard data requirement — the free per-unit feeds this dashboard runs on
  (Physical Notifications, acceptances, cashflows) exist only for registered
  BM Units, so a battery traded behind an aggregator or supplier unit is
  invisible at site level and cannot appear whatever we do. *Known energy
  capacity* is a presentation choice: cycles per day and the duration bucket
  both divide by MWh, so a site without a published duration would render
  blank cells rather than a smaller number.

  *Enough cycling* is the second, and it is a judgement about behaviour rather
  than a fact about an asset. A site turning over less than 0.3 cycles a day is
  almost certainly earning in ancillary markets this model cannot see — and the
  model *can* see the energy it buys to hold state of charge for those
  contracts, with no availability payment against it. Its £ figures are
  therefore not merely uncertain but systematically negative, so showing them as
  performance would mislead more than leaving the site out does. Because that
  criterion moves with market conditions, the window it was measured over is
  recorded in `fleet/registry.py` beside the sites it excluded.

  Together the two filters leave out 36 sites — 2,144 MW, 34% of the fleet.

  The list is built offline by `scripts/build_registry.py`, which reads
  the census and writes a static `fleet/registry.py`. The dashboard imports
  that file and never builds a census itself: doing so would pull whole
  registers into a process sized for free hosting. It is a generated snapshot,
  so it goes stale as units commission — regenerate it when the fleet moves.

  Metadata quality is not uniform across the list, and the difference shows up in
  one place. For the sites `fleet/curated.py` covers, optimiser and region
  are hand-researched — cross-checked against operator disclosure rather than
  derived, though hand-researched is not the same as authoritative.
  For the rest, `power_mw` and `capacity_mwh` are published figures
  (Elexon's declared capability; a matched Capacity Market agreement), but the
  *optimiser* falls back to the BM Unit's lead party — the trading party rather
  than the optimiser proper. Read the **By optimiser** cut on Fleet performance
  with that caveat; every MW- and MWh-based number is unaffected.
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
    range picker under "Custom". Regimes are multi-select pills; nothing
    selected means every day.
    """
    first = dt.date.fromisoformat(date_isos[0])
    last = dt.date.fromisoformat(date_isos[-1])

    with st.sidebar:
        st.markdown("**Filters**")
        preset = st.segmented_control(
            "Period",
            list(_PERIOD_PRESETS) + ["Custom"],
            default="30D",
            key="flt_period",
            help="Quick windows count back from the most recent settled day.",
        )
        # A segmented control can be deselected entirely; treat that as "all".
        preset = preset or "30D"

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

        # One compact control for all twelve tags, ordered drivers → price
        # character → untagged so the taxonomy reads top to bottom.
        tag_options = (
            sorted(classify_mod.DRIVER_TAGS)
            + sorted(classify_mod.PRICE_TAGS)
            + ["untagged"]
        )
        day_types = st.multiselect(
            "Market regimes",
            tag_options,
            key="flt_day_types",
            placeholder="All regimes",
            help=(
                "Regime tags from the classifier (fundamentals first, then "
                "price traits) — none selected means all days. 'untagged' "
                "covers days with no clear character or no classification data."
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


def _with_duration(fleet_df: pd.DataFrame) -> pd.DataFrame:
    """Cached day frames can predate the duration column; derive it on the fly
    so a running server survives the upgrade without a cache clear."""
    if "duration" in fleet_df.columns:
        return fleet_df
    return fleet_df.assign(
        duration=[
            fleet_perf.duration_label(mw, mwh)
            for mw, mwh in zip(fleet_df["power_mw"], fleet_df["capacity_mwh"])
        ]
    )


# The metric switch drives the numbers as well as the charts, so the label the
# user picks, the unit it is measured in and how it is formatted all live in one
# place. Keys are the chart modules' metric names.
_FLEET_METRICS: dict[str, tuple[str, str, str]] = {
    "Revenue": ("revenue", "£/MW/day", "{:,.0f}"),
    "Capture spread": ("capture", "£/MWh", "{:,.1f}"),
    "Cycles": ("cycles", "cycles/day", "{:,.2f}"),
    "Volume": ("volume", "MWh/day", "{:,.0f}"),
    "Capacity": ("capacity", "MW", "{:,.0f}"),
}
# Where each metric lives on the per-site summary frame.
_FLEET_METRIC_COLUMNS = {
    "revenue": "gbp_per_mw_day",
    "capture": "capture_spread",
    "cycles": "cycles_per_day",
    "volume": "discharge_mwh_per_day",
    "capacity": "power_mw",
}


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
    fleet_df = _with_duration(fleet_df)
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

    picked = st.segmented_control(
        "Metric",
        list(_FLEET_METRICS),
        default="Revenue",
        key="fleet_metric",
        help="Re-computes the numbers above and every chart below: estimated "
        "£/MW/day, gross margin per MWh discharged, cycles per day, "
        "charged/discharged energy, or nameplate MW (the daily view doubles "
        "as data coverage).",
    )
    label = picked or "Revenue"
    metric, unit, fmt = _FLEET_METRICS[label]
    column = _FLEET_METRIC_COLUMNS[metric]

    # The numbers describe whatever the switch is set to; anything else and the
    # headline figures quietly contradict the charts underneath them.
    values = pd.to_numeric(site_df[column], errors="coerce").dropna()
    total_mw = float(site_df["power_mw"].sum())
    total_mwh = float(site_df["capacity_mwh"].sum())

    cols = st.columns(4)
    cols[0].metric(
        _unit_label("Active capacity", "MW"),
        f"{total_mw:,.0f}",
        f"{total_mwh:,.0f} MWh · {len(site_df)} sites",
        delta_color="off",
        help="Nameplate power, energy and site count currently passing the filters.",
    )
    _iqr = (values.quantile(0.75) - values.quantile(0.25)) if len(values) >= 4 else None
    cols[1].metric(
        _unit_label("Operator dispersion", unit),
        fmt.format(_iqr) if _iqr is not None else "—",
        help="Interquartile spread (P75 − P25) across the visible sites for the "
        "selected metric — what skill and siting were worth, measured where "
        "one outlier cannot move it. Needs at least four sites.",
    )
    cols[2].metric(
        _unit_label("Fleet baseline", unit),
        fmt.format(values.median()) if len(values) else "—",
        help="The median visible site for the selected metric — the typical "
        "real battery, not the average dragged around by an exceptional one.",
    )
    if len(values):
        best = site_df.loc[values.idxmax()]
        cols[3].metric(
            "Top performer",
            best["site"],
            f"{best['optimiser']} · {fmt.format(values.max())} {unit}",
            delta_color="off",
            help="The best visible site for the selected metric, and the party "
            "trading it.",
        )
    else:
        cols[3].metric("Top performer", "—")

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
    spread = fleet_perf.fleet_daily_distribution(fleet_df, metric)
    if not spread.empty:
        st.plotly_chart(chart_fleet_spread(spread, metric), width="stretch")

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
            "site", "optimiser", "region", "duration", "power_mw", "capacity_mwh",
            "days", "gbp_per_mw_day", "total_gbp", "total_cycles", "capture_spread",
            "flag",
        ]
    ].rename(
        columns={
            "flag": "Flag",
            "site": "Site",
            "optimiser": "Optimiser",
            "region": "Region",
            "duration": "Duration",
            "power_mw": "MW",
            "capacity_mwh": "MWh",
            "days": "Days",
            "gbp_per_mw_day": "£/MW/day",
            "total_gbp": "Total £",
            "total_cycles": "Total cycles",
            "capture_spread": "Capture £/MWh",
        }
    )
    st.dataframe(
        table.style.format(
            {
                "MW": "{:,.0f}",
                "MWh": "{:,.0f}",
                "£/MW/day": "£{:,.0f}",
                "Total £": "£{:,.0f}",
                "Total cycles": "{:,.1f}",
                "Capture £/MWh": "£{:,.1f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )


# --------------------------------------------------------------------------- #
# Sim vs fleet comparison page
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _fleet_profile_day(date_iso: str) -> pd.DataFrame:
    """Per-site half-hourly net MW for one day, from the cached PN records."""
    date = dt.date.fromisoformat(date_iso)
    try:
        pn = fetch_fleet.fetch_fleet_pn(date, FLEET_POPULATION)
    except Exception:
        return pd.DataFrame(columns=["site", "time", "mw"])
    return fleet_perf.site_profile(pn, FLEET_POPULATION)


def _fleet_hourly_shape(dates: list[str], sites: pd.DataFrame) -> pd.DataFrame | None:
    """Mean net output by hour across ``dates`` for the comparison sites,
    as a share of their combined nameplate MW. Hours with no PN activity are
    genuine zeros, so the (date, hour) grid is filled before averaging."""
    frames = [_fleet_profile_day(d) for d in dates]
    profile = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if profile.empty:
        return None
    profile = profile[profile["site"].isin(sites["site"])]
    if profile.empty:
        return None
    nameplate = float(sites["power_mw"].sum())
    profile = profile.assign(
        date=profile["time"].dt.strftime("%Y-%m-%d"), hour=profile["time"].dt.hour
    )
    by_slot = profile.groupby(["date", "hour"])["mw"].sum()
    grid = pd.MultiIndex.from_product([dates, range(24)], names=["date", "hour"])
    hourly = by_slot.reindex(grid, fill_value=0.0).groupby("hour").mean()
    return pd.DataFrame({"hour": hourly.index, "fleet": hourly.values / nameplate})


def _page_sim_vs_fleet():
    view = _benchmark_view()
    if view is None:
        return
    params, shown, caption = view
    duration = params["duration"]

    _page_header("Execution gap", caption)
    st.caption(
        "The simulation is a **perfect-foresight DA+MID ceiling** for one idealised "
        "battery; fleet numbers are free-data estimates spanning several markets. "
        "Only like legs are compared: each site's **wholesale leg (PN × MID)** "
        "against the sim of the **same duration** over the **same days**. BM revenue "
        "is shown alongside but never enters a ratio, and ancillary revenue is "
        "invisible on both sides."
    )

    # Only the days on screen: this fetch is per-BMU and the heaviest in the app.
    date_isos = tuple(d["date"] for d in shown)
    fleet_df = _with_duration(_fleet_range(date_isos))
    if fleet_df.empty:
        st.warning("No fleet data could be fetched — Elexon per-unit data may be unavailable.")
        return
    fleet_df = fleet_df[fleet_df["duration"] == duration]
    if fleet_df.empty:
        st.info(
            f"No {duration} sites in the tracked fleet — pick another duration "
            "in the sidebar to compare."
        )
        return

    sim_by_date = {r["date"]: r["result"].durations[duration] for r in shown}
    common = sorted(set(sim_by_date) & set(fleet_df["date"].unique()))
    if not common:
        st.info("No overlapping settled days between the sim and the fleet window.")
        return
    fleet_df = fleet_df[fleet_df["date"].isin(common)]

    include_flagged = st.toggle(
        "Include ⚠ ancillary-tilted sites",
        value=False,
        help="Low-cycling sites likely earn in markets neither side can see; "
        "including them fakes a bigger sim-vs-fleet gap.",
    )
    site_df = fleet_perf.summarise_by_site(fleet_df)
    excluded = set() if include_flagged else set(site_df.loc[site_df["likely_ancillary"], "site"])
    comp_sites = site_df[~site_df["site"].isin(excluded)]
    if comp_sites.empty:
        st.info("Every matched site is ⚠ flagged — toggle them on to compare anyway.")
        return
    comp_daily = fleet_df[~fleet_df["site"].isin(excluded)]

    sim_gbp_by_day = {d: r.net_pnl / REFERENCE_POWER_MW for d, r in sim_by_date.items()}
    sim_gbp = float(pd.Series({d: sim_gbp_by_day[d] for d in common}).mean())
    sim_cycles = float(pd.Series([sim_by_date[d].cycles for d in common]).mean())

    mw_days = float((comp_sites["power_mw"] * comp_sites["days"]).sum())
    fleet_wholesale = float(comp_sites["wholesale_gbp"].sum()) / mw_days

    # Cycles per site-day, weighted the same way the money is, so the physical
    # gap and the earnings gap are computed over the same population.
    fleet_cycles = float(
        (comp_sites["cycles_per_day"] * comp_sites["days"]).sum()
        / comp_sites["days"].sum()
    )

    st.markdown("**The headline gap**")
    cols = st.columns(5)
    cols[0].metric(
        _unit_label("Sim ceiling", "£/MW/day"),
        f"{sim_gbp:,.0f}",
        help=f"Perfect-foresight {duration} benchmark on the DA/MID spread, over "
        f"the {len(common)} common days.",
    )
    cols[1].metric(
        _unit_label("Fleet wholesale avg", "£/MW/day"),
        f"{fleet_wholesale:,.0f}",
        help="PN × MID leg only, MW-weighted over the comparison sites — the leg "
        "the sim actually plays. Balancing revenue is deliberately outside it.",
    )
    cols[2].metric(
        "Realisation",
        f"{fleet_wholesale / sim_gbp:.0%}" if sim_gbp > 1e-9 else "—",
        help="Fleet wholesale average as a share of the sim ceiling — the grading "
        "of real execution against a perfect-foresight trader.",
    )
    cols[3].metric(
        "Physical gap",
        f"{fleet_cycles:.2f} vs {sim_cycles:.2f}",
        f"{fleet_cycles - sim_cycles:+.2f} cycles/day",
        delta_color="off",
        help="Fleet cycles per day against the simulation's, on delivered "
        "throughput. It separates the two ways of falling short: trading the "
        "same energy worse, or simply moving less of it.",
    )
    cols[4].metric(
        "Sites compared",
        f"{len(comp_sites)} × {duration}",
        f"{len(excluded)} ⚠ excluded" if excluded else "none excluded",
        delta_color="off",
    )

    comp = comp_sites.assign(
        wholesale=comp_sites["wholesale_gbp"] / (comp_sites["power_mw"] * comp_sites["days"]),
        bm=comp_sites["bm_gbp"] / (comp_sites["power_mw"] * comp_sites["days"]),
    )
    comp = comp.assign(ratio=comp["wholesale"] / sim_gbp if sim_gbp > 1e-9 else 0.0)
    per_day = comp_daily.groupby("date").agg(
        wholesale_gbp=("wholesale_gbp", "sum"), mw=("power_mw", "sum")
    )
    daily = pd.DataFrame(
        {
            "date": common,
            "sim": [sim_gbp_by_day[d] for d in common],
            "fleet": [
                float(per_day.loc[d, "wholesale_gbp"] / per_day.loc[d, "mw"])
                if d in per_day.index
                else 0.0
                for d in common
            ],
        }
    )
    st.markdown("**Behaviour & timing**")
    st.plotly_chart(chart_sim_vs_fleet_daily(daily), width="stretch")

    shape = _fleet_hourly_shape(common, comp_sites)
    if shape is not None:
        sim_hours: dict[int, list[float]] = {}
        for d in common:
            for i, entry in enumerate(sim_by_date[d].dispatch_log):
                sim_hours.setdefault(i % 24, []).append(
                    entry["final_mw"] / REFERENCE_POWER_MW
                )
        shape["sim"] = shape["hour"].map(
            lambda h: float(pd.Series(sim_hours.get(h, [0.0])).mean())
        )

    labels = _day_labels(tuple(date_isos))
    fleet_by_day = dict(zip(daily["date"], daily["fleet"]))
    ratio_rows = []
    for tag in sorted(classify_mod.TAGS):
        tag_days = [d for d in common if tag in (labels.get(d) or [])]
        if not tag_days:
            continue
        sim_mean = float(pd.Series([sim_gbp_by_day[d] for d in tag_days]).mean())
        if sim_mean <= 1e-9:
            continue
        fleet_mean = float(pd.Series([fleet_by_day[d] for d in tag_days]).mean())
        ratio_rows.append(
            {
                "tag": tag,
                "family": "driver" if tag in classify_mod.DRIVER_TAGS else "price",
                "ratio": fleet_mean / sim_mean,
                "days": len(tag_days),
            }
        )
    # When the fleet moves, beside how much of the ceiling it caught on each
    # kind of day: timing on the left, outcome on the right. Either can be
    # absent, so each column carries its own empty state.
    when_col, ratio_col = st.columns(2)
    if shape is None:
        when_col.info("No usable per-hour fleet shape in this window.")
    else:
        when_col.plotly_chart(chart_shape_overlay(shape), width="stretch")
    if ratio_rows:
        ratio_col.plotly_chart(
            chart_daytype_ratio(pd.DataFrame(ratio_rows)), width="stretch"
        )
    else:
        ratio_col.info("No day in this window carries a regime tag.")

    # Site level last: the two headline questions are answered above, and this
    # is where you go to ask which operators closed the gap.
    st.markdown("**Site-level breakdown**")
    st.plotly_chart(
        chart_sim_vs_fleet_sites(comp, sim_gbp, f"sim {duration} ceiling"),
        width="stretch",
    )
    scatter = site_df.assign(excluded=site_df["site"].isin(excluded))
    st.plotly_chart(
        chart_cycles_vs_revenue(scatter, sim_cycles, sim_gbp), width="stretch"
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
    st.sidebar.caption("The benchmark levers do not affect this page.")
    tags = ", ".join(day_types) if day_types else "all regimes"
    _page_header(
        "Real GB fleet performance",
        f"{start} → {end} · {tags} · estimated performance of real grid-scale batteries",
    )
    # Stated on the page itself, not only under Methodology: this is the figure
    # a viewer needs in order to read the numbers below correctly, and it is the
    # first thing an informed reader will ask for.
    st.caption(
        "51 sites — **66% of GB BM-registered battery MW**. Sites with no published "
        "duration, or cycling too little to price, are left out; batteries behind "
        "aggregator units are absent entirely. See Methodology → Scope."
    )
    # Nothing on this page carries from one day to the next, so only the
    # filtered window is fetched — per-BMU streams are the heaviest feed in
    # the app and fetching 60 days to show 7 was most of the wait.
    window = tuple(d for d in date_isos if start <= d <= end)
    fleet_df = _fleet_range(window)
    if fleet_df.empty:
        st.warning(
            "No fleet data could be fetched — Elexon per-unit data may be "
            "temporarily unavailable."
        )
        return
    _warm_fetch(window)
    _render_fleet(fleet_df, _day_labels(window), start, end, day_types)


@st.cache_data(show_spinner=False)
def _system_day(date_iso: str) -> pd.DataFrame:
    """Whole-system half-hourly snapshot for one day (cached on the date)."""
    return fetch_live.get_day_system(dt.date.fromisoformat(date_iso))


@st.cache_data(show_spinner=False)
def _system_summary_day(date_iso: str) -> dict | None:
    """One compact daily row for the window views: energy (GWh) per generation
    group, demand and stress peaks, and the day's price distribution. ``None``
    if the day has no data, so the range self-trims. Small and cached, so
    building a 60-day window is cheap.

    Prices are day-ahead: it is the auction price the benchmark trades against,
    and the one where negative clearing actually means something. Day-ahead is
    hourly, so ``da_hours`` carries the count that makes a window-level mean
    hour-weighted rather than a mean of daily means (DST days are 23 or 25
    hours long, and would otherwise be over- or under-counted).
    """
    system = _system_day(date_iso)
    if system.empty:
        return None
    groups = fetch_live.group_generation(system)
    energy = groups.sum() * 0.5 / 1000.0  # GWh over the day per group
    row: dict = {"date": date_iso}
    for group in groups.columns:
        row[group] = float(energy[group])
    demand = system["demand_actual"] if "demand_actual" in system.columns else None
    row["peak_demand_gw"] = float(demand.max()) / 1000.0 if demand is not None else None
    # Peak residual load — the most the rest of the fleet had to carry that day.
    residual = resilience.residual_load(system).dropna()
    row["peak_residual_gw"] = float(residual.max()) / 1000.0 if not residual.empty else None
    try:
        prices, _ = _fetch_day(date_iso)
        da = prices["day_ahead_price"].dropna()
        row["avg_da"] = float(da.mean())
        row["avg_mid"] = float(prices["mid_price"].mean())
        row["da_hours"] = int(len(da))
        row["da_min"] = float(da.min())
        row["da_max"] = float(da.max())
        row["da_p10"] = float(da.quantile(0.10))
        row["da_p90"] = float(da.quantile(0.90))
        row["da_negative_hours"] = int((da < 0).sum())
    except Exception:
        row["avg_da"] = row["avg_mid"] = None
        row["da_hours"] = 0
        row["da_min"] = row["da_max"] = row["da_p10"] = row["da_p90"] = None
        row["da_negative_hours"] = 0
    return row


def _stress_frequency(date_isos: tuple, sdf: pd.DataFrame) -> pd.DataFrame:
    """Per-day counts of stress periods and negative-price hours.

    Stress is a window-relative decile of residual load, so it is classified
    once across the whole shown window — the same call the Day and Alignment
    pages make — and then counted per day.
    """
    flags = _window_flags(date_isos)
    if flags.empty:
        return pd.DataFrame()
    counts = flags["stress"].astype(int).groupby(flags.index.date).sum()
    counts.index = [d.isoformat() for d in counts.index]
    out = pd.DataFrame({"date": sdf["date"]}).set_index("date")
    out["stress"] = counts
    out["negative"] = sdf.set_index("date")["da_negative_hours"]
    return out.fillna(0).reset_index()


def _unit_label(name: str, unit: str) -> str:
    """Metric label with its unit on a second line.

    Streamlit renders metric labels in muted grey beneath the value, so a unit
    on its own line reads as a caption rather than competing with the name.
    Percentages are the deliberate exception and stay welded to the value
    ("68%"): a percent sign is universally read at a glance, and giving it a
    whole line would be noise.

    The break is a Markdown hard break (two trailing spaces). Metric labels
    take inline Markdown only, so if a Streamlit version ever stops honouring
    it the label degrades to one line rather than breaking.
    """
    return f"{name}  \n{unit}"


def _page_system():
    date_isos = _dates()
    start, end, day_types = _global_filters(date_isos)
    st.sidebar.caption("The benchmark levers do not affect this page.")
    # Every other page warms the day cache behind a progress bar before doing
    # anything slow. This page fetches just as much — day labels, then a daily
    # summary per day — so without it the first load is a blank screen.
    window = tuple(d for d in date_isos if start <= d <= end)
    _warm_fetch(window)
    labels = _day_labels(window)
    days = [
        d
        for d in date_isos
        if start <= d <= end and _matches_day_types(labels.get(d), day_types)
    ]
    tags = ", ".join(day_types) if day_types else "all regimes"
    _page_header(
        "GB system overview",
        f"{start} → {end} · {tags} · how expensive and how stretched the GB system "
        "was, from the same free feeds the benchmark runs on.",
    )
    if not days:
        st.info("No days match the current filters — widen the period or clear a day type.")
        return

    summaries = [s for s in (_system_summary_day(d) for d in days) if s is not None]
    if not summaries:
        st.warning("No system data could be fetched for the window — the Elexon or "
                   "PV_Live feeds may be temporarily unavailable.")
        return
    sdf = pd.DataFrame(summaries)
    group_cols = [g for g in fetch_live.GENERATION_GROUP_ORDER if g in sdf.columns]
    gen_cols = [g for g in group_cols if g != "Interconnectors"]

    # Days shown describes the *filter*, not the system, so it rides in the
    # header as a badge rather than competing with the grid's own numbers.
    st.badge(f"{len(sdf)} days shown", icon=":material/event:", color="grey")

    # Window KPIs are summed over the actual days shown, so the day-type filter
    # flows straight through (e.g. "low-carbon share on sunny days").
    total_gen = float(sdf[gen_cols].to_numpy().sum())
    renewable = float(
        sdf[[g for g in gen_cols if g in fetch_live.RENEWABLE_GROUPS]].to_numpy().sum()
    )
    da_hours = float(sdf["da_hours"].sum()) if "da_hours" in sdf else 0.0
    # Hour-weighted so DST days (23 or 25 hours) don't distort the mean.
    avg_da = (
        float((sdf["avg_da"] * sdf["da_hours"]).sum() / da_hours) if da_hours > 0 else None
    )
    spread = (sdf["da_p90"] - sdf["da_p10"]) if "da_p90" in sdf else pd.Series(dtype=float)

    # Units live on a second label line, not in the value, so the eye can run
    # down a row comparing magnitudes without stepping over a currency sign.
    # Percentages are the exception — see _unit_label.
    row1 = st.columns(4)
    row1[0].metric(
        "Renewable share",
        f"{renewable / total_gen:.0%}" if total_gen > 0 else "—",
        help="Wind, solar, hydro and biomass as a share of GB generation over the "
        "window (interconnector imports excluded). Nuclear is clean but not "
        "renewable, and runs as flat baseload, so leaving it out keeps the "
        "number moving with the weather. The hydro band also carries pumped "
        "storage, which is only as renewable as whatever charged it.",
    )
    row1[1].metric(
        _unit_label("Avg wholesale price", "£/MWh"),
        f"{avg_da:,.0f}" if avg_da is not None else "—",
        help="Mean day-ahead price across the window, weighted by hours so that "
        "clock-change days do not distort it.",
    )
    row1[2].metric(
        _unit_label("Highest wholesale price", "£/MWh"),
        f"{sdf['da_max'].max():,.0f}" if sdf["da_max"].notna().any() else "—",
        help="The peak day-ahead price reached in the window.",
    )
    row1[3].metric(
        _unit_label("Lowest wholesale price", "£/MWh"),
        f"{sdf['da_min'].min():,.0f}" if sdf["da_min"].notna().any() else "—",
        help="The floor day-ahead price in the window — below zero when generators "
        "paid to keep running.",
    )

    row2 = st.columns(4)
    row2[0].metric(
        _unit_label("Negative price count", "hours"),
        f"{int(sdf['da_negative_hours'].sum())}",
        help="Day-ahead hours that cleared below £0. Day-ahead is an hourly "
        "auction, so this counts hours rather than settlement periods.",
    )
    _max_spread_i = spread.idxmax() if spread.notna().any() else None
    row2[1].metric(
        _unit_label("Max daily P90–P10 spread", "£/MWh"),
        f"{spread.max():,.0f}" if _max_spread_i is not None else "—",
        sdf.loc[_max_spread_i, "date"] if _max_spread_i is not None else None,
        delta_color="off",
        help="The widest single day between its top and bottom price deciles — "
        "the most tradable day in the window. Deciles ignore the one-off "
        "spike that a simple high-minus-low would chase.",
    )
    row2[2].metric(
        _unit_label("Max daily peak demand", "GW"),
        f"{sdf['peak_demand_gw'].max():.1f}" if sdf["peak_demand_gw"].notna().any() else "—",
        help="The highest half-hourly demand reached in the window (Elexon ITSDO).",
    )
    row2[3].metric(
        _unit_label("Max system stress", "GW"),
        f"{sdf['peak_residual_gw'].max():.1f}"
        if "peak_residual_gw" in sdf and sdf["peak_residual_gw"].notna().any() else "—",
        help="The highest residual load (demand − wind − solar) — the biggest "
        "burden the dispatchable fleet had to carry.",
    )

    # Price volatility leads: the numbers above it are mostly prices, so the
    # chart that explains them belongs directly beneath them.
    st.plotly_chart(chart_price_volatility(sdf), width="stretch")
    st.plotly_chart(chart_generation_daily(sdf, group_cols), width="stretch")
    renewable_cols = [g for g in gen_cols if g in fetch_live.RENEWABLE_GROUPS]
    st.plotly_chart(chart_renewable_daily(sdf, renewable_cols), width="stretch")
    st.plotly_chart(chart_stress_vs_demand(sdf), width="stretch")

    # Stress is a window-relative decile, so it is classified once across the
    # shown days rather than per day — the same classifier the Day and
    # Alignment pages use, so one word cannot mean two things.
    freq = _stress_frequency(tuple(days), sdf)
    if freq.empty:
        st.info("Not enough system data in this window to classify system stress.")
    else:
        st.plotly_chart(chart_stress_frequency(freq), width="stretch")

    st.caption(
        "Sources — generation mix: Elexon FUELHH (transmission-metered); solar: "
        "Sheffield Solar PV_Live (embedded); demand: Elexon ITSDO; day-ahead: "
        "Nord Pool N2EX. All free, all public. Stress is the top decile of "
        "residual load across the window shown, so it moves when the date "
        "filter moves."
    )

    st.caption(
        "Single-day detail — generation stack, prices and the raw table — "
        "lives on the Day briefing page."
    )


@st.cache_data(show_spinner="Classifying system stress…")
def _window_flags(date_isos: tuple) -> pd.DataFrame:
    """Half-hourly residual load + stress/surplus flags over the shown window.

    Thresholds are quantiles over this window, so the classification is
    relative to the period on screen. Days whose system data is unavailable
    contribute nothing; negative-price periods (hourly DA, forward-filled to
    the half-hourly grid) join the surplus set.
    """
    residual_parts, price_parts = [], []
    for iso in date_isos:
        system = _system_day(iso)
        if system.empty:
            continue
        residual_parts.append(resilience.residual_load(system))
        try:
            prices, _ = _fetch_day(iso)
            price_parts.append(prices["day_ahead_price"])
        except Exception:
            pass
    if not residual_parts:
        return pd.DataFrame()
    residual = pd.concat(residual_parts).sort_index()
    prices = pd.concat(price_parts).sort_index() if price_parts else None
    return resilience.classify_periods(residual, prices)


@st.cache_data(show_spinner=False)
def _lolpdrm_window(date_isos: tuple) -> pd.DataFrame:
    """Half-hourly LoLP / de-rated margin over the shown window.

    Latest print per settlement period. Days whose feed is unavailable simply
    contribute no rows; empty frame when nothing is available.
    """
    parts = []
    for iso in date_isos:
        day = fetch_live.get_day_lolpdrm(dt.date.fromisoformat(iso))
        if not day.empty:
            parts.append(day)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts).sort_index()


@st.cache_data(show_spinner=False)
def _cmn_notices(fetch_date_iso: str) -> pd.DataFrame:
    """Capacity Market Notice register snapshot, keyed on today so it refreshes daily."""
    del fetch_date_iso  # cache key only
    return fetch_live.get_cmn_notices()


def _sim_series(shown: list, duration: str) -> tuple[pd.Series, pd.Series]:
    """Hourly benchmark dispatch (MW, +discharge) and SOC-before series."""
    dispatch, soc = {}, {}
    for record in shown:
        log = record["result"].durations[duration].dispatch_log
        idx = pd.date_range(record["date"], periods=len(log), freq="1h", tz="UTC")
        for ts, entry in zip(idx, log):
            dispatch[ts] = entry["final_mw"]
            soc[ts] = entry["soc_before"]
    return pd.Series(dispatch).sort_index(), pd.Series(soc).sort_index()


def _page_alignment():
    view = _benchmark_view()
    if view is None:
        return
    params, shown, caption = view
    duration = params["duration"]

    _page_header("Alignment gap", caption)
    st.caption(
        "Does profit-optimal dispatch serve the system? Stress = top-decile "
        "residual load (demand − wind − solar) in the shown window; surplus = "
        "bottom decile or negative prices. The gap compares this dispatch with a "
        "resilience-optimal counterfactual under identical physics. Definitions "
        "on the Methodology page."
    )

    dates_shown = [d["date"] for d in shown]
    flags = _window_flags(tuple(dates_shown))
    if flags.empty:
        st.warning("No system data available for the shown window — the Elexon or "
                   "PV_Live feeds may be temporarily unavailable.")
        return

    hourly_flags = pd.DataFrame(
        {
            "residual_mw": flags["residual_mw"].resample("1h").mean(),
            "stress": flags["stress"].resample("1h").max().astype(bool),
            "surplus": flags["surplus"].resample("1h").max().astype(bool),
        }
    ).dropna(subset=["residual_mw"])

    sim_dispatch, sim_soc = _sim_series(shown, duration)
    scores = resilience.alignment_scores(sim_dispatch, hourly_flags)
    readiness = resilience.readiness_at_stress(sim_soc, hourly_flags["stress"])

    # Per-day gap vs the resilience-optimal counterfactual (same asset, same
    # levers, same day-start SOC).
    gap_days = []
    for record in shown:
        dur_result = record["result"].durations[duration]
        log = dur_result.dispatch_log
        idx = pd.date_range(record["date"], periods=len(log), freq="1h", tz="UTC")
        stress = hourly_flags["stress"].reindex(idx).fillna(False).tolist()
        surplus = hourly_flags["surplus"].reindex(idx).fillna(False).tolist()
        asset = BESSAsset(
            capacity_mwh=REFERENCE_POWER_MW * _duration_hours(duration),
            power_mw=REFERENCE_POWER_MW,
            charge_efficiency=bess_config()["charge_efficiency"],
            discharge_efficiency=bess_config()["discharge_efficiency"],
            degradation_cost_per_mwh=params["degradation"],
            initial_soc_pct=log[0]["soc_before"] if log else 0.5,
            min_soc_pct=params["soc_min"],
            max_soc_pct=params["soc_max"],
        )
        gap = resilience.alignment_gap(
            arb_dispatch_mw=[e["final_mw"] for e in log],
            day_ahead_prices=[e["da_price_actual"] for e in log],
            stress=stress,
            surplus=surplus,
            asset=asset,
            target_daily_cycles=params["cycle_target"],
        )
        gap["date"] = record["date"]
        gap["labels"] = record["labels"]
        gap_days.append(gap)
    gap_df = pd.DataFrame(gap_days)
    mean_gap_mw_day = float(gap_df["profit_cost_of_alignment"].mean()) / REFERENCE_POWER_MW
    stress_forgone = float(gap_df["stress_mwh_forgone"].sum())

    cols = st.columns(4)
    cols[0].metric(
        "Stress coverage",
        f"{scores['stress_coverage']:.0%}" if scores["stress_coverage"] is not None else "—",
        help="Share of the benchmark's discharged energy delivered during "
        "stress periods (top-decile residual load).",
    )
    cols[1].metric(
        "Surplus absorption",
        f"{scores['surplus_absorption']:.0%}"
        if scores["surplus_absorption"] is not None else "—",
        help="Share of the benchmark's charged energy drawn during surplus "
        "periods (bottom-decile residual load or negative prices).",
    )
    cols[2].metric(
        "Readiness at stress",
        f"{readiness:.0%}" if readiness is not None else "—",
        help="Mean state of charge held when a stress block begins — the energy "
        "actually available when the system tightens.",
    )
    cols[3].metric(
        "Cost of full alignment",
        f"£{mean_gap_mw_day:,.0f}/MW/day",
        f"{stress_forgone:,.0f} MWh stress delivery forgone",
        delta_color="off",
        help="DA energy value the profit-optimal dispatch would give up by "
        "switching to the resilience-optimal schedule (same physics); the "
        "delta line is the stress-hour energy arbitrage left undelivered.",
    )

    # --- Exemplar day: dispatch against system state --------------------------
    # Auto-selects the window's highest-stress day (the day that tests the
    # thesis hardest); the picker allows overriding.
    _exemplar = str(flags["residual_mw"].idxmax().date())
    _default_i = dates_shown.index(_exemplar) if _exemplar in dates_shown else len(dates_shown) - 1
    picked = st.selectbox(
        "Exemplar day",
        options=dates_shown,
        index=_default_i,
        help="Auto-selected as the highest residual-load day in the window — "
        "the day that tests the thesis hardest. Override to inspect any other.",
    )
    day_date = dt.date.fromisoformat(picked)
    day_flags = flags[flags.index.date == day_date]
    day_dispatch = sim_dispatch[sim_dispatch.index.date == day_date]
    if not day_flags.empty and not day_dispatch.empty:
        st.plotly_chart(chart_alignment_day(day_flags, day_dispatch), width="stretch")
    else:
        st.info("No overlapping system data for this day.")

    # --- System tightness: operator-grade margin + declared notices -----------
    st.subheader("System tightness")
    st.caption(
        "The tier ladder checks the relative stress signal against the "
        "operator's own numbers. Tier 1 = top-decile residual load (above); "
        "tier 2 = Elexon LoLP > 0 or de-rated margin below "
        f"{resilience.DRM_TIGHT_MW:,.0f} MW; tier 3 = a declared Capacity "
        "Market Notice."
    )
    lolpdrm = _lolpdrm_window(tuple(dates_shown))
    cmn = _cmn_notices(dt.datetime.now(dt.timezone.utc).date().isoformat())
    window_start = pd.Timestamp(dates_shown[0], tz="UTC")
    window_end = pd.Timestamp(dates_shown[-1], tz="UTC") + pd.Timedelta(days=1)
    cmn_issued = (
        cmn[cmn["type_id"] == fetch_live.CMN_ISSUE_TYPE] if not cmn.empty else pd.DataFrame()
    )
    if not cmn_issued.empty:
        # Issued notices normally have no end yet (the end arrives on the
        # cancellation row), so an open notice counts as its target half-hour.
        _eff_end = cmn_issued["end_utc"].fillna(
            cmn_issued["start_utc"] + pd.Timedelta(minutes=30)
        )
        cmn_win = cmn_issued[
            (cmn_issued["start_utc"] < window_end) & (_eff_end > window_start)
        ]
    else:
        cmn_win = pd.DataFrame()
    tiers = resilience.classify_tiers(flags, lolpdrm, cmn_win)
    dispatch_hh = sim_dispatch.reindex(tiers.index, method="ffill", limit=1)
    tm = resilience.tier_metrics(tiers, dispatch_hh, sim_soc)

    tcols = st.columns(4)
    tcols[0].metric(
        "Min de-rated margin",
        f"{tm['min_drm_mw']:,.0f} MW" if tm["min_drm_mw"] is not None else "—",
        tm["min_drm_time"].strftime("%Y-%m-%d %H:%M") if tm["min_drm_time"] is not None else None,
        delta_color="off",
        help="Tightest de-rated margin in the window (Elexon LoLP/DRM, latest "
        "print per period). The system's spare de-rated capacity after "
        "outages and interconnectors — the operator's own tightness measure.",
    )
    tcols[1].metric(
        "Periods LoLP > 0",
        f"{tm['n_lolp_positive']}",
        help="Half-hours whose final loss-of-load probability print was "
        f"positive, out of {tm['n_tier2_known']} with data.",
    )
    tcols[2].metric(
        "Tier-2 stress coverage",
        f"{tm['tier2_coverage']:.0%}" if tm["tier2_coverage"] is not None else "—",
        help="Share of the benchmark's discharged energy delivered while the "
        "system was tight by the operator's measure (LoLP > 0 or DRM below "
        f"{resilience.DRM_TIGHT_MW:,.0f} MW). '—' when no tier-2 tight period "
        "or no discharge fell in periods with LoLP/DRM data.",
    )
    _last_cmn = (
        cmn_issued["posted_utc"].dropna().max() if not cmn_issued.empty else None
    )
    tcols[3].metric(
        "Capacity Market Notices",
        f"{len(cmn_win)} in window" if len(cmn_win) else "None in window",
        f"last: {_last_cmn.date().isoformat()}" if _last_cmn is not None else None,
        delta_color="off",
        help="Declared shortfall notices from the NESO CMN register — the "
        "strongest stress signal there is, and rare by design. The delta "
        "shows the register's most recent notice regardless of window.",
    )

    n_unknown = int(len(tiers) - tm["n_tier2_known"])
    if tm["tier2_confirm_rate"] is not None:
        st.caption(
            f"System confirmation: {tm['tier2_confirm_rate']:.0%} of tier-1 "
            "(top-decile residual load) stress periods were also "
            "system-confirmed tight (tier 2)."
            + (
                f" {n_unknown} period(s) lacked LoLP/DRM data and are excluded."
                if n_unknown
                else ""
            )
        )
    elif tm["n_tier2_known"]:
        st.caption(
            "System confirmation: no tier-1 stress period had LoLP/DRM data "
            "to check against."
        )

    if tm["n_tier2_known"]:
        st.plotly_chart(
            chart_system_tightness(tiers, dispatch_hh, resilience.DRM_TIGHT_MW),
            width="stretch",
        )
    else:
        st.info("LoLP/De-rated Margin feed unavailable for this window.")
    st.caption(
        "Sources — LoLP/de-rated margin: Elexon (latest print per period, "
        "shortest forecast horizon); Capacity Market Notices: NESO GB CMN "
        "register. Both free, public feeds."
    )

    # --- Fleet: profit vs alignment ------------------------------------------
    fleet_df = _with_duration(_fleet_range(_dates()))
    scatter_df = pd.DataFrame()
    profiles = pd.DataFrame()
    if not fleet_df.empty:
        fleet_df = fleet_df[fleet_df["date"].isin(dates_shown)]
    if not fleet_df.empty:
        site_df = fleet_perf.summarise_by_site(fleet_df)
        profiles = pd.concat(
            [_fleet_profile_day(iso) for iso in dates_shown], ignore_index=True
        )
        rows = []
        for _, site in site_df.iterrows():
            mine = profiles[profiles["site"] == site["site"]]
            if mine.empty:
                continue
            series = mine.set_index("time")["mw"].sort_index()
            s = resilience.alignment_scores(series, flags)
            if s["stress_coverage"] is None:
                continue
            rows.append(
                {
                    "site": site["site"],
                    "optimiser": site["optimiser"],
                    "stress_coverage": s["stress_coverage"],
                    "gbp_per_mw_day": site["gbp_per_mw_day"],
                    "excluded": bool(site["likely_ancillary"]),
                }
            )
        scatter_df = pd.DataFrame(rows)
    if not scatter_df.empty:
        sim_gbp = float(
            pd.Series(
                [d["result"].durations[duration].net_pnl for d in shown]
            ).mean()
        ) / REFERENCE_POWER_MW
        st.plotly_chart(
            chart_alignment_scatter(scatter_df, scores["stress_coverage"], sim_gbp),
            width="stretch",
        )
        st.caption(
            "Fleet revenue is the wholesale+BM estimate (£/MW/day); fleet stress "
            "coverage is computed from each site's Physical Notifications with "
            "the same classifier as the benchmark. ⚠ sites are ancillary-tilted; "
            "their revenue is understated."
        )

    # --- Does the fleet relieve tight margins, or compete with them? ----------
    # Both inputs are already on this page: the fleet's half-hourly profile,
    # built above for the scatter, and the margin feed fetched for the tier
    # ladder. So this costs a groupby, not a fetch.
    if not profiles.empty and not lolpdrm.empty and "drm_mw" in lolpdrm:
        net = profiles.groupby("time")["mw"].sum().rename("fleet_mw")
        joined = pd.concat([net, lolpdrm["drm_mw"]], axis=1).dropna()
        # Five bands, or fewer if the margin barely moved in this window.
        if len(joined) >= _MARGIN_BAND_MIN_PERIODS:
            joined = joined.assign(
                band=pd.qcut(joined["drm_mw"], 5, labels=False, duplicates="drop")
            )
            bands = [
                {
                    "band": f"{sub['drm_mw'].min() / 1000:.1f}–"
                            f"{sub['drm_mw'].max() / 1000:.1f} GW",
                    "mean_fleet_mw": float(sub["fleet_mw"].mean()),
                    "charging_share": float((sub["fleet_mw"] < 0).mean()),
                    "periods": int(len(sub)),
                }
                for _, sub in joined.groupby("band")
            ]
            band_df = pd.DataFrame(bands)
            tight, loose = band_df.iloc[0], band_df.iloc[-1]
            mcols = st.columns(2)
            mcols[0].metric(
                _unit_label("Fleet response when tightest", "MW"),
                f"{tight['mean_fleet_mw']:,.0f}",
                f"{tight['charging_share']:.0%} of those periods charging",
                delta_color="off",
                help="Mean fleet net output across the tightest fifth of the "
                "window's de-rated margins. Positive means the fleet was "
                "discharging into tightness rather than competing with it.",
            )
            mcols[1].metric(
                _unit_label("Swing from loosest to tightest", "MW"),
                f"{tight['mean_fleet_mw'] - loose['mean_fleet_mw']:+,.0f}",
                f"loosest fifth {loose['mean_fleet_mw']:,.0f} MW",
                delta_color="off",
                help="How far the fleet's net position moves between the "
                "loosest and tightest fifth of margins — the size of the "
                "response, as opposed to its direction.",
            )
            st.plotly_chart(chart_margin_response(band_df), width="stretch")
            st.caption(
                "Margin bands are quantiles of this window, not fixed thresholds: "
                "a rolling summer window never reaches a scarcity margin, so "
                "absolute bands would render empty. Read 'tightest' as tightest "
                "relative to the days on screen."
            )

    # --- Gap by day type + stress events --------------------------------------
    tag_rows: dict[str, dict] = {}
    for _, row in gap_df.iterrows():
        for tag in row["labels"] or []:
            slot = tag_rows.setdefault(
                tag,
                {
                    "tag": tag.replace("_", " "),
                    "family": "driver" if tag in classify_mod.DRIVER_TAGS else "price",
                    "gap_sum": 0.0,
                    "days": 0,
                },
            )
            slot["gap_sum"] += row["profit_cost_of_alignment"] / REFERENCE_POWER_MW
            slot["days"] += 1
    left, right = st.columns(2)
    if tag_rows:
        by_tag = pd.DataFrame(
            [
                {**v, "gap": v["gap_sum"] / v["days"]}
                for v in tag_rows.values()
            ]
        )
        left.plotly_chart(chart_gap_by_daytype(by_tag), width="stretch")

    stress_events = flags[flags["stress"]].nlargest(10, "residual_mw").copy()
    if not stress_events.empty:
        hourly_dispatch = sim_dispatch.reindex(
            stress_events.index.floor("1h")
        ).to_numpy()
        fleet_net = (
            profiles.groupby("time")["mw"].sum()
            if not profiles.empty
            else pd.Series(dtype=float)
        )
        table = pd.DataFrame(
            {
                "Time (UTC)": stress_events.index.strftime("%Y-%m-%d %H:%M"),
                "Residual (GW)": stress_events["residual_mw"] / 1000.0,
                "Benchmark (MW)": hourly_dispatch,
                "Fleet net (MW)": fleet_net.reindex(stress_events.index).to_numpy()
                if not fleet_net.empty
                else float("nan"),
            }
        )
        right.markdown("#### Top stress periods")
        right.dataframe(
            table.style.format(
                {"Residual (GW)": "{:,.1f}", "Benchmark (MW)": "{:,.0f}",
                 "Fleet net (MW)": "{:,.0f}"}
            ),
            width="stretch",
            hide_index=True,
        )


ALIGNMENT_METHODOLOGY = """
The Alignment page quantifies the relationship between profit-optimal dispatch
and system need, from the same public feeds as everything else.

- **Residual load** — transmission demand (ITSDO) minus wind (FUELHH) minus
  embedded solar (PV_Live), half-hourly. **Stress** = top decile of residual
  load over the shown window; **surplus** = bottom decile, or any
  negative-price period.
- **Stress coverage / surplus absorption** — the share of discharged energy
  delivered in stress periods and of charged energy drawn in surplus periods.
  The same scorer runs on the benchmark's dispatch and on each fleet site's
  Physical Notifications, so simulated and real behaviour are comparable.
- **Readiness** — mean state of charge at the onset of each stress block.
- **Tier ladder (System tightness)** — stress severity in three tiers. Tier 1
  is the relative signal above (top-decile residual load). Tier 2 is
  system-confirmed tightness from Elexon's LoLP / de-rated margin feed —
  latest print per settlement period (forecast horizon 1, else the shortest
  published) — tight when LoLP > 0 or the de-rated margin is below 2,000 MW
  (roughly one large CCGT plus operating reserve; an absolute threshold by
  design, unlike tier 1's window-relative decile). Tier 3 is a declared
  Capacity Market Notice: the half-hour overlaps an issued notice's target
  window (cancellations are not applied in this version — a cancelled CMN can
  over-shade, never hide stress). Periods without a LoLP/DRM print are
  *unknown* at tier 2 and excluded from tier-2 shares, never assumed calm.
- **Alignment gap** — the benchmark's dispatch versus a resilience-optimal
  counterfactual (identical SOC window, power, efficiency and cycle cap;
  objective = deliver in stress, absorb in surplus). Both schedules are valued
  at the cleared DA price with no intraday layer or fees, plus a symmetric
  terminal-inventory credit (the day's SOC change valued at the day-mean DA
  price), giving the profit cost of full alignment and the stress-hour energy
  pure arbitrage leaves undelivered.
- **Caveats** — demand is transmission-metered (embedded generation nets off);
  tier-1 stress is a residual-load proxy while tiers 2–3 are the operator's
  own margin and notice data; benchmark dispatch uses the perfect-foresight
  intraday engine.
"""

GLOSSARY = """
| Term | Definition |
|---|---|
| **Capture** | Benchmark net PnL ÷ its perfect-foresight DA arbitrage ceiling for the same day |
| **Realisation** | Fleet wholesale £/MW/day ÷ the matching-duration benchmark ceiling over the same days |
| **Cycle** | One full discharge equivalent: discharged MWh ÷ nameplate MWh |
| **Residual load** | Demand − wind − embedded solar (MW) |
| **Stress / surplus** | Top-decile residual load / bottom decile or negative prices, over the shown window |
| **Alignment gap** | DA value forgone by the resilience-optimal schedule vs the profit-optimal one |
| **LoLP** | Loss of load probability — Elexon's per-period chance that demand exceeds available supply |
| **De-rated margin** | Spare supply after de-rating for reliability (MW); the operator's tightness measure |
| **CMN** | Capacity Market Notice — NESO's declared warning of a possible capacity shortfall |
| **Tier 1 / 2 / 3** | Stress: relative (top-decile residual) / confirmed (LoLP > 0, DRM < 2,000 MW) / declared (CMN) |
"""


def _page_methodology():
    _page_header("Methodology", "What these numbers are — and what they are not")
    st.subheader("Scope — this dashboard and the research behind it")
    st.markdown(SCOPE)
    st.divider()
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Benchmark battery")
        st.markdown(METHODOLOGY)
    with right:
        st.subheader("Live GB fleet")
        st.markdown(FLEET_METHODOLOGY)
    st.subheader("Alignment")
    st.markdown(ALIGNMENT_METHODOLOGY)
    st.subheader("Design principles")
    st.markdown(
        """
- **Grouping is by epistemic status** — *Benchmark* is simulated, *GB power
  system* is observed public data, *Research* is analysis using both.
- **Sidebar filters define the window** (period, day types); the **Day
  briefing's picker chooses one day within it** and is the app's only day
  selector. Research pages auto-select their exemplar days and say so.
- **Benchmark levers appear only on pages they affect**; observed pages carry
  a note instead.
"""
    )
    st.subheader("Definitions")
    st.markdown(GLOSSARY)


# --------------------------------------------------------------------------- #
# Sidebar parameter panel & main
# --------------------------------------------------------------------------- #
def _benchmark_parameters() -> tuple:
    """The benchmark's five levers, as a sidebar form.

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
            "commit": 100,
        },
    )
    # Sessions saved before the allocation lever existed lack the key.
    saved.setdefault("commit", 100)

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
                    "Cap on daily discharged energy; one cycle is one full "
                    "discharge equivalent (discharged MWh ÷ nameplate MWh). "
                    "More cycles chase more spread but wear the battery harder."
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
            commit = st.slider(
                "DA commitment (%)",
                0,
                100,
                saved["commit"],
                5,
                help=(
                    "Market allocation: the share of the battery's power and "
                    "of its daily cycle budget the day-ahead auction may "
                    "commit. The rest is held back for the intraday stage — "
                    "free to chase MID without first unwinding a DA position "
                    "(and paying slippage on it)."
                ),
            )
            if st.form_submit_button("Apply", type="primary", width="stretch"):
                st.session_state["bench_params"] = {
                    "duration": duration,
                    "cycles": cycles,
                    "degradation": degradation,
                    "soc": soc,
                    "commit": commit,
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
    return (
        p["duration"],
        p["cycles"],
        p["degradation"],
        p["soc"][0] / 100.0,
        p["soc"][1] / 100.0,
        p.get("commit", 100) / 100.0,
    )


def main():
    st.set_page_config(
        page_title="Live GB BESS",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    # Grouped by epistemic status: the model, the observed world, and the
    # analysis that uses both. The Day briefing is the deliberate cross-cutting
    # lens and the landing page.
    pages = {
        "Benchmark": [
            st.Page(
                _page_day,
                title="Daily summary",
                icon=":material/bolt:",
                url_path="daily",
                default=True,
            ),
            st.Page(
                _page_history,
                title="Optimiser performance",
                icon=":material/monitoring:",
                url_path="optimiser",
            ),
        ],
        "GB power system": [
            st.Page(
                _page_system,
                title="System overview",
                icon=":material/electric_meter:",
                url_path="system",
            ),
            st.Page(
                _page_fleet,
                title="Fleet performance",
                icon=":material/battery_charging_full:",
                url_path="fleet",
            ),
        ],
        "Research": [
            st.Page(
                _page_day_types,
                title="Market regimes",
                icon=":material/partly_cloudy_day:",
                url_path="regimes",
            ),
            st.Page(
                _page_sim_vs_fleet,
                title="Execution gap",
                icon=":material/compare_arrows:",
                url_path="sim-vs-fleet",
            ),
            st.Page(
                _page_alignment,
                title="Alignment gap",
                icon=":material/balance:",
                url_path="alignment",
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
