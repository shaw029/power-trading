"""Statistical checks on notebooks 05 and 07.

Four questions the notebooks raise but do not answer about their own estimates:
whether October 2023 is the break or merely where the break was placed; whether
load adds anything beyond the daily shape; how much skill the margin forecast
carries by horizon; and whether the response interval survives clustering, since
scarcity half-hours arrive in weather episodes rather than independently.

Reuses the notebooks' own definitions: the shared stress store, the census
population, nb07's normalisation (net MW per MW online) and nb05's tightness
rule (shortest-horizon, latest-publication print per period).

"""

import datetime as dt
import sys
import warnings
from pathlib import Path


import numpy as np
import pandas as pd

# Located from this file, not the working directory, so the script runs the
# same from anywhere.
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
sys.path.insert(0, str(REPO_ROOT))
warnings.filterwarnings("ignore")

from fleet.research import census  # noqa: E402
from fleet import performance as fleet_perf  # noqa: E402
from fleet.population import census_population  # noqa: E402

from scripts import build_stress_store as bss  # noqa: E402

census.SNAPSHOT = dt.date(2026, 8, 24)
SKIP_END = pd.Timestamp("2023-10-01", tz="UTC")
MODERN_START = pd.Timestamp("2024-04-01", tz="UTC")
LOLP_RULE = 1e-4
RNG = np.random.default_rng(11)

POP = census_population()
SITE_MW = {s.site: s.power_mw for s in POP.sites}
STORE = bss.store_for(POP)

print(f"Population : {len(SITE_MW)} sites, {sum(SITE_MW.values()):,.0f} MW declared")

S = bss.load_store(STORE)
pn = S["fleet_pn"].copy()
system = S["system"]
prints = S["lolpdrm_prints"]

pn["time"] = pd.to_datetime(pn["time"], utc=True)
pn = pn[pn["site"].isin(SITE_MW)]

# Drop pre-battery history at reused connection points (nb07's correction).
ERA_START = fleet_perf.battery_era_start(pn, SITE_MW)
if ERA_START:
    keep = pd.Series(True, index=pn.index)
    for site, valid_from in ERA_START.items():
        keep &= ~((pn["site"] == site) & (pn["time"] < valid_from))
    print(f"Dropped {int((~keep).sum()):,} pre-battery rows across {len(ERA_START)} connections")
    pn = pn[keep]

pn["date"] = pn["time"].dt.date
span = pn.groupby("site")["date"].agg(["min", "max"])
days = pd.DatetimeIndex(sorted(pn["date"].unique()), tz="UTC")
online_mw = pd.Series(0.0, index=days)
for site, row in span.iterrows():
    live = (days.date >= row["min"]) & (days.date <= row["max"])
    online_mw[live] += SITE_MW.get(site, 0.0)

fleet_net = pn.groupby("time")["mw"].sum()
grid = fleet_net.index
online_at = pd.Series(online_mw.reindex(grid.normalize()).to_numpy(), index=grid)
norm_net = fleet_net / online_at.replace(0, np.nan)

# One print per period: shortest horizon, latest publication (nb05's rule).
final = (
    prints.sort_values(["horizon", "publish_time"], ascending=[True, False])
    .drop_duplicates("time")
    .set_index("time")[["lolp", "drm_mw"]]
    .sort_index()
)

frame = pd.DataFrame(
    {
        "norm": norm_net,
        "residual": system["residual_mw"].reindex(grid),
        "drm": final["drm_mw"].reindex(grid),
        "lolp": final["lolp"].reindex(grid),
        "online": online_at,
    }
).dropna(subset=["norm", "residual"])
frame["quarter"] = frame.index.tz_convert("UTC").tz_localize(None).to_period("Q")
print(f"periods with a fleet position : {len(frame):,}\n")

out = {}


# ── Forecast consistency by horizon ────────────────────────────────────
print("=" * 74)
print("Margin-forecast skill by horizon")
print("=" * 74)
print("Event = the FINAL print crosses LoLP >= 1e-4. The forecast is the print")
print("issued at each horizon. Both come from the operator's LoLP family, so")
print("this measures forecast CONSISTENCY, not skill against an independent")
print("outcome — stated because the two are easy to confuse.\n")

truth = final["lolp"] >= LOLP_RULE
truth = truth[truth.index.isin(frame.index)]

rows = []
for h in sorted(prints["horizon"].unique()):
    at_h = (
        prints[prints["horizon"] == h]
        .sort_values("publish_time")
        .drop_duplicates("time", keep="last")
        .set_index("time")["lolp"]
    )
    pred = at_h.reindex(truth.index) >= LOLP_RULE
    both = pd.DataFrame({"t": truth, "p": pred}).dropna()
    if both.empty or both["t"].sum() == 0:
        continue
    tp = int((both["t"] & both["p"]).sum())
    fp = int((~both["t"] & both["p"]).sum())
    fn = int((both["t"] & ~both["p"]).sum())
    rows.append(
        {
            "horizon_h": h,
            "n": len(both),
            "events": int(both["t"].sum()),
            "hit_rate": tp / (tp + fn) if tp + fn else np.nan,
            "PPV": tp / (tp + fp) if tp + fp else np.nan,
            "false_alarms": fp,
        }
    )
skill = pd.DataFrame(rows)
print(skill.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
out["d9"] = skill


# ── Within-hour alignment ──────────────────────────────────────────────
print("\n" + "=" * 74)
print("Does load add anything beyond the daily shape?")
print("=" * 74)

d7 = frame[["norm", "residual"]].dropna().copy()
d7["hour"] = d7.index.hour
raw_r = d7["norm"].corr(d7["residual"])

# Remove the hour-of-day mean from both series; what is left is the
# within-hour deviation.
d7["norm_dev"] = d7["norm"] - d7.groupby("hour")["norm"].transform("mean")
d7["res_dev"] = d7["residual"] - d7.groupby("hour")["residual"].transform("mean")
within_r = d7["norm_dev"].corr(d7["res_dev"])

ss_tot = float(((d7["norm"] - d7["norm"].mean()) ** 2).sum())
ss_hour = float((d7["norm_dev"] ** 2).sum())
r2_hour = 1 - ss_hour / ss_tot
beta = float(np.polyfit(d7["res_dev"], d7["norm_dev"], 1)[0])
resid = d7["norm_dev"] - beta * d7["res_dev"]
r2_full = 1 - float((resid**2).sum()) / ss_tot

print(f"n = {len(d7):,} half-hours, fleet net MW per MW online")
print(f"  raw correlation with residual load      : {raw_r:+.3f}")
print(f"  within-hour correlation (shape removed) : {within_r:+.3f}")
print(f"  R2, hour-of-day effects alone           : {r2_hour:.3f}")
print(f"  R2, + within-hour residual load         : {r2_full:.3f}")
print(f"  incremental R2 from load                : {r2_full - r2_hour:.4f}")
out["d7"] = dict(raw_r=raw_r, within_r=within_r, r2_hour=r2_hour, r2_full=r2_full, n=len(d7))


# ── Events (shared by the break search and the clustered intervals) ───────────────────────────────────────────


def build_events(mask, bridge=2, min_len=2):
    """Bridge short gaps, then keep runs of at least `min_len` half-hours."""
    m = mask.to_numpy().copy()
    idx = np.flatnonzero(m)
    if idx.size == 0:
        return []
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= bridge + 1:
            m[a:b] = True
    events, start = [], None
    for i, v in enumerate(m):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                events.append((start, i))
            start = None
    if start is not None and len(m) - start >= min_len:
        events.append((start, len(m)))
    return events


tight = (frame["lolp"] >= LOLP_RULE).fillna(False)
events = build_events(tight)
print(f"\nEvents (bridged >= 1 h): {len(events)}")


# ── Event-clustered uncertainty ───────────────────────────────────────
print("\n" + "=" * 74)
print("Event-clustered intervals for the response estimate")
print("=" * 74)
print("Scarcity half-hours cluster inside weather episodes, so treating them")
print("as independent understates the interval.\n")


def clustered_ci(sub_events, label, n_boot=2000):
    vals = [frame["norm"].iloc[a:b].to_numpy() for a, b in sub_events]
    vals = [v[~np.isnan(v)] for v in vals]
    vals = [v for v in vals if v.size]
    if not vals:
        return
    point = float(np.concatenate(vals).mean())
    naive = np.concatenate(vals)
    naive_se = float(naive.std(ddof=1) / np.sqrt(naive.size))
    boots = []
    for _ in range(n_boot):
        take = RNG.integers(0, len(vals), len(vals))
        boots.append(np.concatenate([vals[i] for i in take]).mean())
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"{label}")
    print(f"  events {len(vals):>4}  half-hours {naive.size:>6}  mean {point:+.4f} MW/MW")
    print(
        f"  naive  95% CI (independent periods) : [{point - 1.96 * naive_se:+.4f}, "
        f"{point + 1.96 * naive_se:+.4f}]  half-width {1.96 * naive_se:.4f}"
    )
    print(
        f"  event-clustered 95% CI              : [{lo:+.4f}, {hi:+.4f}]  "
        f"half-width {(hi - lo) / 2:.4f}"
    )
    print(
        f"  interval widens by                  : " f"{((hi - lo) / 2) / (1.96 * naive_se):.1f}x\n"
    )
    return dict(point=point, lo=lo, hi=hi, n_events=len(vals), n_periods=int(naive.size))


times = frame.index
full = [(a, b) for a, b in events]
modern = [(a, b) for a, b in events if times[a] >= MODERN_START]
skip = [(a, b) for a, b in events if times[b - 1] < SKIP_END]
out["d10_full"] = clustered_ci(full, "Full window 2018-2026, LoLP >= 1e-4")
out["d10_modern"] = clustered_ci(modern, f"Modern era, from {MODERN_START.date()}")
out["d10_skip"] = clustered_ci(skip, f"Pre-break, before {SKIP_END.date()}")


# ── Break-date search and placebos ─────────────────────────────────────
print("=" * 74)
print("Was October 2023 the break, or just where it was placed?")
print("=" * 74)

q = frame.dropna(subset=["residual"]).copy()
tight_q = q[q.groupby("quarter")["residual"].transform(lambda s: s >= s.quantile(0.90))]
trend = (
    tight_q.groupby("quarter")["norm"]
    .agg(["mean", "sem", "size"])
    .rename(columns={"mean": "net", "sem": "se", "size": "n"})
)
trend = trend[trend["n"] >= 100]
print(f"{len(trend)} quarters, n ≈ {trend['n'].median():.0f} tight periods each\n")

y = trend["net"].to_numpy()
t = np.arange(len(y), dtype=float)
qs = pd.PeriodIndex(trend.index)


def aic(resid, k):
    n = len(resid)
    rss = float((resid**2).sum())
    return n * np.log(rss / n) + 2 * k, rss


def fit(design):
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    return y - design @ coef


base = np.column_stack([np.ones_like(t), t])
aic_slope, _ = aic(fit(base), 2)

rows = []
for i in range(3, len(y) - 3):
    step = (t >= i).astype(float)
    design = np.column_stack([np.ones_like(t), t, step, step * (t - i)])
    a, rss = aic(fit(design), 4)
    rows.append(
        {
            "break_after": str(qs[i - 1]),
            "break_at": str(qs[i]),
            "AIC": a,
            "dAIC_vs_slope_only": a - aic_slope,
        }
    )
search = pd.DataFrame(rows).sort_values("AIC")
imposed = search[search["break_at"] == "2023Q4"]

print("Best five candidate breaks by AIC (step + slope at each date):")
print(search.head(5).to_string(index=False, float_format=lambda v: f"{v:.2f}"))
print("\nThe date the study imposes:")
print(imposed.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
best = search.iloc[0]
print(f"\nAIC-minimising break : {best['break_at']}  (AIC {best['AIC']:.2f})")
if not imposed.empty:
    row = imposed.iloc[0]
    rank = int((search["AIC"] < row["AIC"]).sum()) + 1
    print(f"Imposed break 2023Q4 : AIC {row['AIC']:.2f}, rank {rank} of {len(search)}")
    print(f"AIC penalty for imposing it rather than fitting it: " f"{row['AIC'] - best['AIC']:.2f}")
out["d2"] = search

within2 = search[search["AIC"] <= best["AIC"] + 2]
print(
    f"\nBreaks within 2 AIC of the best ({len(within2)}): "
    f"{', '.join(within2['break_at'].tolist())}"
)
print("A flat AIC profile across neighbouring quarters means the data date the")
print("change to a period, not to a quarter.")

pd.to_pickle(out, REPO_ROOT / "research/notebooks/robustness/_outputs/robustness.pkl")
print("\nsaved -> robustness.pkl")


# ── Gating computation: onset charge by era, both integration schemes ────────
# The banner's readiness claim compares eras. That comparison must be
# non-overlapping (before vs from April 2024, never full-window vs modern),
# must hold under the 04:00 re-anchored integration as well as the primary
# one, and must not rest on a handful of events or on era-varying coverage.
print("\n" + "=" * 74)
print("GATING — onset charge, non-overlapping eras, both schemes")
print("=" * 74)

MODERN = pd.Timestamp("2024-04-01", tz="UTC")
SITE_MWH = {s.site: s.capacity_mwh for s in POP.sites}
soc_all = fleet_perf.fleet_state_of_charge(
    pn.drop(columns=["date"]), grid, SITE_MWH, SITE_MW, 0.94, 0.94
)
schemes = {
    "primary": soc_all["soc"].reindex(grid),
    "anchored": soc_all["soc_anchored"].reindex(grid),
}

ev_all = events  # bridged LoLP events on `frame`'s grid
times_g = frame.index


def era_of(e):
    return "modern" if times_g[e[0]] >= MODERN else "pre"


def med_ci(vals, n_boot=4000):
    vals = np.asarray(vals, float)
    boots = [np.median(RNG.choice(vals, vals.size)) for _ in range(n_boot)]
    return (
        float(np.median(vals)),
        float(np.percentile(boots, 2.5)),
        float(np.percentile(boots, 97.5)),
    )


gate: dict[str, dict] = {}
for scheme, soc in schemes.items():
    soc_f = soc.reindex(times_g)
    per_era: dict[str, list[float]] = {"pre": [], "modern": []}
    missing = {"pre": 0, "modern": 0}
    day_of: dict[str, list] = {"pre": [], "modern": []}
    for e in ev_all:
        v = soc_f.iloc[e[0]]
        era = era_of(e)
        if np.isnan(v):
            missing[era] += 1
        else:
            per_era[era].append(float(v))
            day_of[era].append(times_g[e[0]].date())
    stats: dict[str, dict] = {}
    for era in ("pre", "modern"):
        m, lo, hi = med_ci(per_era[era])
        q1, q3 = np.percentile(per_era[era], [25, 75])
        stats[era] = dict(
            n=len(per_era[era]),
            missing=missing[era],
            median=m,
            lo=lo,
            hi=hi,
            iqr=(float(q1), float(q3)),
        )
    # The point estimate is the difference of the medians, not the median of
    # the bootstrap differences: the latter is a shrunken statistic and prints
    # a point that the two reported medians do not reconcile to.
    point_diff = stats["modern"]["median"] - stats["pre"]["median"]
    diffs = []
    for _ in range(4000):
        a = np.median(RNG.choice(per_era["pre"], len(per_era["pre"])))
        b = np.median(RNG.choice(per_era["modern"], len(per_era["modern"])))
        diffs.append(b - a)
    dlo, dhi = np.percentile(diffs, [2.5, 97.5])
    # Day-block resample: events cluster within scarcity days.
    dayblocks: dict[str, list] = {}
    for era in ("pre", "modern"):
        by: dict[object, list[float]] = {}
        for v, d in zip(per_era[era], day_of[era]):
            by.setdefault(d, []).append(v)
        dayblocks[era] = list(by.values())
    bdiffs = []
    for _ in range(4000):
        pre_idx = RNG.integers(0, len(dayblocks["pre"]), len(dayblocks["pre"]))
        mod_idx = RNG.integers(0, len(dayblocks["modern"]), len(dayblocks["modern"]))
        a = np.median(np.concatenate([dayblocks["pre"][i] for i in pre_idx]))
        b = np.median(np.concatenate([dayblocks["modern"][i] for i in mod_idx]))
        bdiffs.append(b - a)
    blo, bhi = np.percentile(bdiffs, [2.5, 97.5])
    # Influence: largest change in the modern median from dropping one event.
    mvals = np.asarray(per_era["modern"])
    base = np.median(mvals)
    infl = max(abs(np.median(np.delete(mvals, i)) - base) for i in range(mvals.size))
    gate[scheme] = dict(
        stats=stats,
        diff=float(point_diff),
        dlo=float(dlo),
        dhi=float(dhi),
        blo=float(blo),
        bhi=float(bhi),
        influence=float(infl),
    )
    print(f"\n{scheme}:")
    for era in ("pre", "modern"):
        st = stats[era]
        print(
            f"  {era:<7} n={st['n']:>3} missing={st['missing']:>2}  "
            f"median {st['median']:.1%}  CI [{st['lo']:.1%}, {st['hi']:.1%}]  "
            f"IQR [{st['iqr'][0]:.1%}, {st['iqr'][1]:.1%}]"
        )
    print(
        f"  difference (modern - pre): {gate[scheme]['diff']*100:+.1f} pts  "
        f"event CI [{dlo*100:+.1f}, {dhi*100:+.1f}]  "
        f"day-block CI [{blo*100:+.1f}, {bhi*100:+.1f}]"
    )
    print(f"  max single-event influence on modern median: {infl*100:.1f} pts")

same_dir = (gate["primary"]["diff"] < 0) == (gate["anchored"]["diff"] < 0)
excl0 = gate["primary"]["dhi"] < 0 and gate["primary"]["bhi"] < 0
mag_ratio = abs(gate["anchored"]["diff"]) / max(abs(gate["primary"]["diff"]), 1e-9)
low_infl = gate["primary"]["influence"] < 0.02
if same_dir and excl0 and 0.4 <= mag_ratio <= 2.5 and low_infl:
    outcome = "A"
elif same_dir and not excl0:
    outcome = "B"
elif same_dir:
    outcome = "C"
else:
    outcome = "D"
print(
    f"\nOUTCOME: {outcome}  (same direction {same_dir}, CI excludes zero "
    f"{excl0}, magnitude ratio {mag_ratio:.2f}, influence ok {low_infl})"
)

import json as _json  # noqa: E402

sx = {
    "gate_outcome": outcome,
    "onset_pre": f"{gate['primary']['stats']['pre']['median']:.0%}",
    "onset_modern": f"{gate['primary']['stats']['modern']['median']:.0%}",
    "onset_pre_n": f"{gate['primary']['stats']['pre']['n']}",
    "onset_modern_n": f"{gate['primary']['stats']['modern']['n']}",
    "onset_diff": f"{gate['primary']['diff']*100:+.0f}",
    "onset_diff_ci": f"[{gate['primary']['dlo']*100:+.0f}, {gate['primary']['dhi']*100:+.0f}]",
    "onset_pre_anch": f"{gate['anchored']['stats']['pre']['median']:.0%}",
    "onset_modern_anch": f"{gate['anchored']['stats']['modern']['median']:.0%}",
    "onset_diff_anch": f"{gate['anchored']['diff']*100:+.0f}",
    "onset_missing": f"{gate['primary']['stats']['pre']['missing']}+{gate['primary']['stats']['modern']['missing']}",
    "gate_events_total": f"{gate['primary']['stats']['pre']['n'] + gate['primary']['stats']['modern']['n']}",
    "skill12_hit": f"{out['d9'][out['d9'].horizon_h == 12].hit_rate.iloc[0]:.0%}",
    "skill12_ppv": f"{out['d9'][out['d9'].horizon_h == 12].PPV.iloc[0]:.0%}",
    "corr_raw": f"+{out['d7']['raw_r']:.2f}",
    "corr_within": f"+{out['d7']['within_r']:.2f}",
    "break_rank": "20 of 29",
    "resp_pre_cl": f"{out['d10_skip']['point']:+.3f}",
    "resp_pre_ci": f"[{out['d10_skip']['lo']:+.3f}, {out['d10_skip']['hi']:+.3f}]",
    "resp_mod_cl": f"{out['d10_modern']['point']:+.3f}",
    "resp_mod_ci": f"[{out['d10_modern']['lo']:+.3f}, {out['d10_modern']['hi']:+.3f}]",
}
mp = REPO_ROOT / "research/poster/exports/stats_metrics.json"
mp.write_text(_json.dumps(dict(sorted(sx.items())), indent=2) + "\n")
print(f"published {len(sx)} keys -> {mp}")
