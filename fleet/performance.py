"""Turn raw per-BMU Elexon records into fleet performance frames.

Pure pandas — no HTTP and no Streamlit — so everything here is unit-testable.
The revenue model is a transparent free-data estimate, not audited settlement:

* **Wholesale proxy** — each BMU's Physical Notification (its declared net
  export, MW) is valued at the half-hourly Market Index (MID) price, as if the
  whole contracted position traded at MID. Discharge earns, charging pays.
* **Balancing Mechanism** — Elexon's indicative ``EBOCF`` cashflows are summed
  as published (offers are usually paid to the unit, bids usually paid back),
  so no BM settlement arithmetic is re-derived here.

Ancillary-service revenue (Dynamic Containment etc.) is out of scope. Worse
than merely reading low: energy bought to hold state of charge for an
ancillary contract is costed at MID here while the availability payment that
motivated it is invisible, so ancillary-tilted sites can read negative.
:func:`summarise_by_site` flags the likely cases instead of pretending the
estimate is comparable.
"""

import pandas as pd

from fleet.registry import FLEET, bmu_to_site

# MID is published on a half-hourly grid; PN spans are floored onto it.
_MID_FREQ = "30min"

# Merchant GB batteries cycle roughly 0.8–1.5×/day; sites parked on an
# ancillary contract mostly hold SOC and cycle far less. Below this many
# cycles/day the wholesale+BM estimate is treated as unrepresentative.
ANCILLARY_CYCLES_THRESHOLD = 0.3


# Revenue is net of charging while throughput counts only discharge, so the
# ratio is only meaningful once the two roughly balance — which happens over a
# week, not within a day. Daily figures are pooled over this many days before
# dividing.
CAPTURE_WINDOW_DAYS = 7
# And below this much throughput there is no trading to take a margin on: the
# revenue is balancing-market money the discharge figure never counted.
CAPTURE_MIN_CYCLES = 0.05


def _capture_spread(total_gbp, discharge_mwh):
    """Gross margin per MWh discharged: revenue over throughput.

    Normalises for power and duration at once, so a 500 MW four-hour site and
    a 34 MW one-hour site compare honestly — unlike £/MW/day, which rewards
    duration, or £ per cycle, which rewards size. It shares units with the
    degradation-cost lever, so a site earning less per MWh than its wear costs
    is visibly losing money by trading.

    A site that never discharged has no spread to report, so zero throughput
    gives NaN rather than an infinity that would poison a median.
    """
    throughput = pd.to_numeric(discharge_mwh, errors="coerce")
    return pd.to_numeric(total_gbp, errors="coerce") / throughput.where(throughput > 0)


def duration_label(power_mw: float, capacity_mwh: float) -> str:
    """Battery hours bucket, e.g. ``"2h"``.

    Rounded to the nearest whole hour because ``capacity_mwh`` is approximate
    nameplate (Capenhurst's 107 MWh / 100 MW is a 1h battery, not a 1.07h one).
    """
    return f"{max(1, round(capacity_mwh / power_mw))}h"


def _pn_frame(pn_records: list[dict]) -> pd.DataFrame:
    """PN records → one row per (bmu, period) with signed energy in MWh."""
    df = pd.DataFrame(pn_records)
    if df.empty:
        return pd.DataFrame(columns=["bmUnit", "time", "energy_mwh"])
    time_from = pd.to_datetime(df["timeFrom"], utc=True)
    hours = (pd.to_datetime(df["timeTo"], utc=True) - time_from).dt.total_seconds() / 3600.0
    mean_mw = (df["levelFrom"] + df["levelTo"]) / 2.0
    return pd.DataFrame(
        {
            "bmUnit": df["bmUnit"],
            "time": time_from.dt.floor(_MID_FREQ),
            "energy_mwh": mean_mw * hours,
        }
    )


def _cashflow_totals(records: list[dict]) -> pd.Series:
    """EBOCF records → total £ per BMU (all bid-offer pairs, nulls ignored)."""
    totals: dict[str, float] = {}
    for record in records:
        pairs = record.get("bidOfferPairCashflows") or {}
        cash = sum(v for v in pairs.values() if v is not None)
        bmu = record.get("bmUnit")
        if bmu:
            totals[bmu] = totals.get(bmu, 0.0) + cash
    return pd.Series(totals, dtype=float)


def day_site_metrics(
    date_iso: str,
    pn_records: list[dict],
    cashflows: dict[str, list[dict]],
    mid_prices: pd.DataFrame,
) -> pd.DataFrame:
    """Per-site metrics for one settlement day.

    Returns one row per fleet site that shows any activity (PN or BM), with
    energy, the wholesale-proxy revenue, BM cashflows and £/MW. Sites silent
    on the day (not yet commissioned, data not published) are omitted rather
    than reported as zero.
    """
    site_of = bmu_to_site()

    pn = _pn_frame(pn_records)
    pn = pn[pn["bmUnit"].isin(site_of)]
    if not pn.empty:
        mid = mid_prices["mid_price"]
        # A period missing a MID print is valued at the day's mean rather than
        # dropped, so energy and revenue stay consistent.
        prices = pn["time"].map(mid).fillna(mid.mean())
        pn = pn.assign(
            site=pn["bmUnit"].map(lambda b: site_of[b].site),
            wholesale_gbp=pn["energy_mwh"] * prices,
        )

    bid = _cashflow_totals(cashflows.get("bid", []))
    offer = _cashflow_totals(cashflows.get("offer", []))

    rows = []
    for site in FLEET:
        ids = list(site.bmu_ids)
        site_pn = pn[pn["bmUnit"].isin(ids)] if not pn.empty else pn
        bm_bid = float(bid.reindex(ids).sum())
        bm_offer = float(offer.reindex(ids).sum())
        if site_pn.empty and bm_bid == 0.0 and bm_offer == 0.0:
            continue
        energy = site_pn["energy_mwh"] if not site_pn.empty else pd.Series(dtype=float)
        discharge = float(energy[energy > 0].sum())
        charge = float(-energy[energy < 0].sum())
        wholesale = float(site_pn["wholesale_gbp"].sum()) if not site_pn.empty else 0.0
        total = wholesale + bm_bid + bm_offer
        rows.append(
            {
                "date": date_iso,
                "site": site.site,
                "optimiser": site.optimiser,
                "region": site.region,
                "duration": duration_label(site.power_mw, site.capacity_mwh),
                "power_mw": site.power_mw,
                "capacity_mwh": site.capacity_mwh,
                "discharge_mwh": discharge,
                "charge_mwh": charge,
                "wholesale_gbp": wholesale,
                "bm_gbp": bm_bid + bm_offer,
                "total_gbp": total,
                "gbp_per_mw": total / site.power_mw,
            }
        )
    return pd.DataFrame(rows)


def site_profile(pn_records: list[dict]) -> pd.DataFrame:
    """Net output per fleet site per half-hour, in MW (positive = discharge).

    Each PN span's energy is assigned to the half-hour it starts in (the same
    flooring as the revenue maths), so a span straddling a boundary shifts a
    little energy one slot early — fine for shape comparison, do not use this
    for settlement. One row per (site, time) with any activity.
    """
    site_of = bmu_to_site()
    pn = _pn_frame(pn_records)
    pn = pn[pn["bmUnit"].isin(site_of)]
    if pn.empty:
        return pd.DataFrame(columns=["site", "time", "mw"])
    pn = pn.assign(site=pn["bmUnit"].map(lambda b: site_of[b].site))
    grouped = pn.groupby(["site", "time"], as_index=False)["energy_mwh"].sum()
    slot_hours = pd.Timedelta(_MID_FREQ).total_seconds() / 3600.0
    grouped["mw"] = grouped["energy_mwh"] / slot_hours
    return grouped[["site", "time", "mw"]]


def site_limit_profile(records: list[dict]) -> pd.DataFrame:
    """Effective declared limit per fleet site per half-hour, in MW.

    Works for MELS (export limits, levels ≥ 0) and MILS (import limits,
    levels ≤ 0). Unlike PN spans, limit records are irregular — redeclarations
    cut settlement periods into sub-spans and overlap earlier declarations —
    so each BMU is painted onto a 1-minute UTC grid in notification order
    (``notificationTime``, tie-broken by ``notificationSequence``), later
    notifications overwriting earlier ones, then averaged per half-hour.
    Time-weighting is deliberate: a unit derated for 24 of 30 minutes was 80%
    unavailable that period, which is exactly the availability signal — a
    last-effective rule would read it as 0% or 100%. Returns tidy
    ``['site', 'time', 'mw']`` like :func:`site_profile`.
    """
    site_of = bmu_to_site()
    df = pd.DataFrame(records)
    if df.empty or "bmUnit" not in df.columns:
        return pd.DataFrame(columns=["site", "time", "mw"])
    df = df[df["bmUnit"].isin(site_of)].copy()
    if df.empty:
        return pd.DataFrame(columns=["site", "time", "mw"])
    df["timeFrom"] = pd.to_datetime(df["timeFrom"], utc=True)
    df["timeTo"] = pd.to_datetime(df["timeTo"], utc=True)
    if "notificationTime" not in df.columns:
        df["notificationTime"] = pd.NaT
    if "notificationSequence" not in df.columns:
        df["notificationSequence"] = 0
    df["notificationTime"] = pd.to_datetime(df["notificationTime"], utc=True)
    df = df.sort_values(["notificationTime", "notificationSequence"], na_position="first")

    parts = []
    for bmu, spans in df.groupby("bmUnit"):
        start = spans["timeFrom"].min().floor(_MID_FREQ)
        end = spans["timeTo"].max().ceil(_MID_FREQ)
        minutes = pd.date_range(start, end, freq="1min", inclusive="left")
        level = pd.Series(float("nan"), index=minutes)
        for row in spans.itertuples():
            span_min = pd.date_range(row.timeFrom, row.timeTo, freq="1min", inclusive="left")
            if len(span_min) == 0:
                continue
            ramp = pd.Series(
                [
                    row.levelFrom
                    + (row.levelTo - row.levelFrom) * i / max(len(span_min) - 1, 1)
                    for i in range(len(span_min))
                ],
                index=span_min,
            )
            level.loc[ramp.index] = ramp
        half_hourly = level.resample(_MID_FREQ).mean().dropna()
        if half_hourly.empty:
            continue
        parts.append(
            pd.DataFrame(
                {
                    "site": site_of[bmu].site,
                    "time": half_hourly.index,
                    "mw": half_hourly.values,
                }
            )
        )
    if not parts:
        return pd.DataFrame(columns=["site", "time", "mw"])
    tidy = pd.concat(parts, ignore_index=True)
    return tidy.groupby(["site", "time"], as_index=False)["mw"].sum()


def filter_daily(
    daily: pd.DataFrame,
    start: str | None = None,
    end: str | None = None,
    sites: list[str] | None = None,
    optimisers: list[str] | None = None,
    regions: list[str] | None = None,
    durations: list[str] | None = None,
    day_types: list[str] | None = None,
    day_labels: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Slice the per-site daily frame by period, asset, location and day type.

    Every filter is optional; ``None`` or an empty list means "no filter", so
    the dashboard's empty multiselects fall through untouched. ``start``/``end``
    are inclusive ISO dates. ``day_types`` selects dates whose tag list (from
    ``day_labels``, keyed by ISO date) intersects the selection; the pseudo-tag
    ``"untagged"`` selects dates with no tags or no entry at all.
    """
    df = daily
    if start is not None:
        df = df[df["date"] >= start]
    if end is not None:
        df = df[df["date"] <= end]
    if sites:
        df = df[df["site"].isin(sites)]
    if optimisers:
        df = df[df["optimiser"].isin(optimisers)]
    if regions:
        df = df[df["region"].isin(regions)]
    if durations:
        df = df[df["duration"].isin(durations)]
    if day_types:
        labels = day_labels or {}
        wanted = set(day_types)

        def _matches(date_iso: str) -> bool:
            tags = labels.get(date_iso) or []
            if not tags:
                return "untagged" in wanted
            return bool(wanted.intersection(tags))

        df = df[df["date"].map(_matches)]
    return df.reset_index(drop=True)


def summarise_by_site(daily: pd.DataFrame) -> pd.DataFrame:
    """Per-site averages over the window, sorted by £/MW/day descending.

    ``cycles_per_day`` divides discharge throughput by the (approximate)
    nameplate energy, so treat it as indicative. ``likely_ancillary`` marks
    sites cycling below :data:`ANCILLARY_CYCLES_THRESHOLD` — their revenue
    probably comes from markets this model cannot see, so the estimate is
    unreliable (and biased low) for them.
    """
    grouped = daily.groupby(["site", "optimiser", "region", "duration"], as_index=False).agg(
        power_mw=("power_mw", "first"),
        capacity_mwh=("capacity_mwh", "first"),
        days=("date", "nunique"),
        total_gbp=("total_gbp", "sum"),
        wholesale_gbp=("wholesale_gbp", "sum"),
        bm_gbp=("bm_gbp", "sum"),
        discharge_mwh=("discharge_mwh", "sum"),
        charge_mwh=("charge_mwh", "sum"),
    )
    grouped["gbp_per_mw_day"] = grouped["total_gbp"] / (grouped["power_mw"] * grouped["days"])
    grouped["cycles_per_day"] = grouped["discharge_mwh"] / (
        grouped["capacity_mwh"] * grouped["days"]
    )
    grouped["total_cycles"] = grouped["discharge_mwh"] / grouped["capacity_mwh"]
    # Throughput is a total, so it grows with the window. The per-day rate is
    # what compares across windows — and what the leaderboard already plots.
    grouped["discharge_mwh_per_day"] = grouped["discharge_mwh"] / grouped["days"]
    grouped["capture_spread"] = _capture_spread(grouped["total_gbp"], grouped["discharge_mwh"])
    grouped["likely_ancillary"] = grouped["cycles_per_day"] < ANCILLARY_CYCLES_THRESHOLD
    return grouped.sort_values("gbp_per_mw_day", ascending=False).reset_index(drop=True)


def _summarise_by(daily: pd.DataFrame, key: str) -> pd.DataFrame:
    """MW-weighted £/MW/day per ``key`` (each site-day weighted by its MW).

    Also carries the group's volume story: average MWh discharged/charged per
    day and cycles/day (throughput over nameplate MWh-days), so the dashboard
    can re-plot the same grouping by any metric.
    """
    grouped = daily.groupby(key, as_index=False).agg(
        sites=("site", "nunique"),
        days=("date", "nunique"),
        total_gbp=("total_gbp", "sum"),
        mw_days=("power_mw", "sum"),
        mwh_days=("capacity_mwh", "sum"),
        discharge_mwh=("discharge_mwh", "sum"),
        charge_mwh=("charge_mwh", "sum"),
    )
    grouped["capture_spread"] = _capture_spread(
        grouped["total_gbp"], grouped["discharge_mwh"]
    )
    site_mw = daily.drop_duplicates("site").groupby(key)["power_mw"].sum()
    grouped["power_mw"] = grouped[key].map(site_mw)
    grouped["gbp_per_mw_day"] = grouped["total_gbp"] / grouped["mw_days"]
    grouped["discharge_mwh_day"] = grouped["discharge_mwh"] / grouped["days"]
    grouped["charge_mwh_day"] = grouped["charge_mwh"] / grouped["days"]
    grouped["cycles_per_day"] = grouped["discharge_mwh"] / grouped["mwh_days"]
    return grouped.sort_values("gbp_per_mw_day", ascending=False).reset_index(drop=True)


def summarise_by_optimiser(daily: pd.DataFrame) -> pd.DataFrame:
    return _summarise_by(daily, "optimiser")


def summarise_by_region(daily: pd.DataFrame) -> pd.DataFrame:
    return _summarise_by(daily, "region")


def fleet_daily(daily: pd.DataFrame) -> pd.DataFrame:
    """Whole-fleet totals per day: revenue split, volumes and £/MW.

    ``mw``/``mwh`` are the nameplate totals of the sites *reporting* that day,
    so ``cycles`` (fleet discharge over fleet nameplate) stays honest when a
    site's data is missing.
    """
    grouped = daily.groupby("date", as_index=False).agg(
        wholesale_gbp=("wholesale_gbp", "sum"),
        bm_gbp=("bm_gbp", "sum"),
        total_gbp=("total_gbp", "sum"),
        discharge_mwh=("discharge_mwh", "sum"),
        charge_mwh=("charge_mwh", "sum"),
        mw=("power_mw", "sum"),
        mwh=("capacity_mwh", "sum"),
    )
    grouped["gbp_per_mw"] = grouped["total_gbp"] / grouped["mw"]
    grouped["cycles"] = grouped["discharge_mwh"] / grouped["mwh"]
    grouped["capture_spread"] = _capture_spread(
        grouped["total_gbp"], grouped["discharge_mwh"]
    )
    return grouped


def site_day_metric(daily: pd.DataFrame, metric: str) -> pd.Series:
    """One site-day's value of ``metric``, for distributions across sites.

    The per-site-day frame carries totals, so the ratio metrics are derived
    here rather than stored five times over.
    """
    if metric == "capture":
        return _capture_spread(daily["total_gbp"], daily["discharge_mwh"])
    if metric == "cycles":
        return daily["discharge_mwh"] / daily["capacity_mwh"]
    column = {
        "revenue": "gbp_per_mw",
        "volume": "discharge_mwh",
        "capacity": "power_mw",
    }[metric]
    return pd.to_numeric(daily[column], errors="coerce")


def _rolling_capture(daily: pd.DataFrame) -> pd.DataFrame:
    """Per-site capture spread pooled over a trailing week.

    A single day divides revenue that is net of charging by discharge alone,
    so a battery filling up for tomorrow shows a wildly negative margin and one
    emptying out shows a wild positive. Pooling a week of both sides before
    dividing lets them balance. Sites whose weekly throughput is still
    negligible are dropped rather than reported as enormous ratios.
    """
    rows = []
    for site, group in daily.sort_values("date").groupby("site"):
        window = min(CAPTURE_WINDOW_DAYS, len(group))
        revenue = group["total_gbp"].rolling(window, min_periods=window).sum()
        throughput = group["discharge_mwh"].rolling(window, min_periods=window).sum()
        floor = group["capacity_mwh"] * CAPTURE_MIN_CYCLES * window
        rows.append(
            pd.DataFrame(
                {
                    "date": group["date"],
                    "value": revenue / throughput.where(throughput >= floor),
                }
            )
        )
    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    return pd.concat(rows).dropna()


def fleet_daily_distribution(daily: pd.DataFrame, metric: str = "revenue") -> pd.DataFrame:
    """Median, interquartile range and full range *across sites*, per day.

    The fleet total says what the fleet did; this says what a typical site did
    and how far apart the sites were, which is the difference between one big
    battery carrying a day and every battery having a good one.
    """
    if metric == "capture":
        frame = _rolling_capture(daily)
    else:
        values = site_day_metric(daily, metric)
        frame = pd.DataFrame({"date": daily["date"], "value": values}).dropna()
    if frame.empty:
        return pd.DataFrame(columns=["date", "median", "p25", "p75", "min", "max"])
    grouped = frame.groupby("date")["value"]
    return pd.DataFrame(
        {
            "date": sorted(frame["date"].unique()),
            "median": grouped.median().to_numpy(),
            "p25": grouped.quantile(0.25).to_numpy(),
            "p75": grouped.quantile(0.75).to_numpy(),
            "min": grouped.min().to_numpy(),
            "max": grouped.max().to_numpy(),
        }
    )
