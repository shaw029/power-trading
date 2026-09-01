"""Does notebook 09's 85% survive a per-period availability bound?

nb09 bounds the MELS counterfactual with `declared[mask].mean()` — one scalar
power rating for the whole day, averaged over the flagged hours. A site
available at full power for half the peak and nothing for the other half is
modelled as uniformly half-available, which lets the LP move energy into hours
it could not have served.

This reruns the same delivery calculation twice in one harness — flat-mean
bound versus per-period bound — so the *difference* is the result. Absolute
levels here will not match nb09 exactly (surplus flags need day-ahead prices,
which are not in the shared store, so the surplus credit is switched off in
both arms); the comparison is like-for-like by construction.
"""
import datetime as dt
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pulp

# Located from this file, not the working directory, so the script runs the
# same from anywhere.
REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()
)
sys.path.insert(0, str(REPO_ROOT))
warnings.filterwarnings("ignore")

from fleet.research import census  # noqa: E402
from fleet.population import census_population  # noqa: E402
from src.utils.config import load_config  # noqa: E402

from scripts import build_stress_store as bss  # noqa: E402

census.SNAPSHOT = dt.date(2026, 8, 24)
WIN_START = pd.Timestamp("2026-06-26", tz="UTC")
WIN_END = pd.Timestamp("2026-08-24 23:59", tz="UTC")

CFG = load_config("configs/config.example.yaml")
CFG = CFG if isinstance(CFG, dict) else CFG.__dict__
ETA_C = CFG.get("charge_efficiency", 0.94)
ETA_D = CFG.get("discharge_efficiency", 0.94)
MIN_SOC, MAX_SOC = CFG.get("min_soc_pct", 0.10), CFG.get("max_soc_pct", 1.0)
CYCLES = CFG.get("target_daily_cycles", 1.5)

POP = census_population()
SITE_MW = {s.site: s.power_mw for s in POP.sites}
SITE_MWH = {s.site: s.capacity_mwh for s in POP.sites
            if s.capacity_mwh and not np.isnan(s.capacity_mwh)}
S = bss.load_store(bss.store_for(POP))

system = S["system"]
resid_hh = system["residual_mw"].loc[WIN_START:WIN_END].dropna()
thresh = float(resid_hh.quantile(0.90))
stress_hh = resid_hh >= thresh
stress_h = stress_hh.resample("1h").max().astype(bool)
hours = stress_h.index
print(f"Window            : {WIN_START.date()} → {WIN_END.date()}")
print(f"Half-hours        : {len(resid_hh):,}  → hours {len(hours):,}")
print(f"Top-decile bar    : {thresh / 1000:.1f} GW")
print(f"Top-decile hours  : {int(stress_h.sum())} of {len(hours)} "
      f"({stress_h.mean():.1%})")
print("(nb09 prints 23.3 GW and 161 of 1,439 — a match validates the rebuild)\n")


def _hourly(df):
    return (df.pivot_table(index="time", columns="site", values="mw", aggfunc="sum")
              .resample("1h").mean())


pn_h = _hourly(S["fleet_pn"].assign(time=lambda d: pd.to_datetime(d["time"], utc=True))
               .query("@WIN_START <= time <= @WIN_END"))
mels_h = _hourly(S["fleet_mels"].assign(time=lambda d: pd.to_datetime(d["time"], utc=True))
                 .query("@WIN_START <= time <= @WIN_END"))

sites = [s for s in SITE_MWH if s in pn_h.columns and s in mels_h.columns]
print(f"Sites with MWh, PN and MELS in window: {len(sites)}\n")


try:
    import highspy  # noqa: F401
    _SOLVER = pulp.HiGHS(msg=0)
except ImportError:
    _SOLVER = pulp.PULP_CBC_CMD(msg=0)


def achievable(cap_mwh, limits, stress_flags, initial_soc=0.5):
    """Max top-decile MWh under a per-period power limit vector."""
    n = len(stress_flags)
    prob = pulp.LpProblem("res", pulp.LpMaximize)
    ch = [pulp.LpVariable(f"c{h}", lowBound=0, upBound=float(limits[h])) for h in range(n)]
    dis = [pulp.LpVariable(f"d{h}", lowBound=0, upBound=float(limits[h])) for h in range(n)]
    soc = [pulp.LpVariable(f"s{h}", lowBound=MIN_SOC * cap_mwh, upBound=MAX_SOC * cap_mwh)
           for h in range(n + 1)]
    w_stress, w_block, tie = 2.0, 2.0, 1e-3
    prob += pulp.lpSum(
        dis[h] * (w_stress if stress_flags[h] else -w_block)
        + ch[h] * (-w_block if stress_flags[h] else -tie)
        for h in range(n)
    )
    prob += soc[0] == cap_mwh * initial_soc
    for h in range(n):
        prob += soc[h + 1] == soc[h] - dis[h] / ETA_D + ch[h] * ETA_C
    if CYCLES:
        prob += pulp.lpSum(dis) <= CYCLES * cap_mwh
    prob.solve(_SOLVER)
    if pulp.LpStatus[prob.status] != "Optimal":
        return None
    return sum(dis[h].value() or 0.0 for h in range(n) if stress_flags[h])


days = sorted({t.date() for t in hours})
rows = []
for si, site in enumerate(sites, 1):
    cap = SITE_MWH[site]
    act = flat = perp = 0.0
    for day in days:
        idx = hours[[t.date() == day for t in hours]]
        if len(idx) < 20:
            continue
        sf = stress_h.reindex(idx).fillna(False).to_numpy()
        if not sf.any():
            continue
        pn = pn_h[site].reindex(idx)
        if pn.isna().all():
            continue
        act += float(np.clip(pn.fillna(0.0).to_numpy(), 0, None)[sf].sum())

        dec = np.clip(mels_h[site].reindex(idx).fillna(0.0).to_numpy(), 0, None)
        flat_lim = float(dec[sf].mean())
        if flat_lim > 0:
            v = achievable(cap, np.full(len(idx), flat_lim), sf)
            if v:
                flat += v
        if dec[sf].max() > 0:
            v = achievable(cap, dec, sf)
            if v:
                perp += v
    rows.append({"site": site, "actual": act, "flat": flat, "perperiod": perp})
    if si % 15 == 0:
        print(f"  ... {si}/{len(sites)} sites")

d = pd.DataFrame(rows)
tot_act, tot_flat, tot_per = d["actual"].sum(), d["flat"].sum(), d["perperiod"].sum()
print("\n" + "=" * 70)
print("MELS bound: flat mean over flagged hours vs per-period")
print("=" * 70)
print(f"Actual top-decile delivery      : {tot_act:>10,.0f} MWh")
print(f"Achievable, flat-mean bound     : {tot_flat:>10,.0f} MWh "
      f"→ delivered {tot_act / tot_flat:.0%}")
print(f"Achievable, per-period bound    : {tot_per:>10,.0f} MWh "
      f"→ delivered {tot_act / tot_per:.0%}")
shift = tot_act / tot_per - tot_act / tot_flat
print(f"\nMoving to a per-period bound shifts the delivered share by "
      f"{shift * 100:+.1f} points.")
print("Positive means the flat mean OVERSTATED what was achievable, so the")
print("true delivered share against declared availability is higher.")

d["per_site_flat"] = d["actual"] / d["flat"].replace(0, np.nan)
d["per_site_per"] = d["actual"] / d["perperiod"].replace(0, np.nan)
sub = d.dropna(subset=["per_site_flat", "per_site_per"])
print(f"\nPer-site median delivered share: flat {sub['per_site_flat'].median():.0%}"
      f"  per-period {sub['per_site_per'].median():.0%}  (n={len(sub)})")
d.to_csv(REPO_ROOT / "research/notebooks/robustness/_outputs/d4_sites.csv", index=False)
print("saved -> research/notebooks/robustness/_outputs/d4_sites.csv")
