"""Does the acceptance correction change sign under operator scarcity?

Section 4's response figures are built from physical notifications. Section 3's
window showed acceptances cutting delivery 26% in top-decile *load* hours, with
the operator instructing batteries down. Scarcity is a different condition: the
operator is short, so the expectation is the opposite sign. This measures it
rather than assuming it.

Only the 385 days carrying a LoLP >= 1e-4 half-hour are fetched; the response
metric needs no continuous history. State of charge does, and is not recomputed
here.

"""

import datetime as dt
import sys
import warnings
from pathlib import Path

import pandas as pd

# Located from this file, not the working directory, so the script runs the
# same from anywhere.
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
sys.path.insert(0, str(REPO_ROOT))
warnings.filterwarnings("ignore")

from fleet.research import census  # noqa: E402
from fleet import fetch_fleet  # noqa: E402
from fleet import performance as fleet_perf  # noqa: E402
from fleet.population import census_population  # noqa: E402

from scripts import build_stress_store as bss  # noqa: E402

census.SNAPSHOT = dt.date(2026, 8, 24)
SKIP_END = pd.Timestamp("2023-10-01", tz="UTC")
MODERN_START = pd.Timestamp("2024-04-01", tz="UTC")
LOLP_RULE = 1e-4

POP = census_population()
SITE_MW = {s.site: s.power_mw for s in POP.sites}
S = bss.load_store(bss.store_for(POP))

prints = S["lolpdrm_prints"]
final = (
    prints.sort_values(["horizon", "publish_time"], ascending=[True, False])
    .drop_duplicates("time")
    .set_index("time")[["lolp", "drm_mw"]]
    .sort_index()
)
tight_idx = final.index[final["lolp"] >= LOLP_RULE]
days = sorted({t.date() for t in tight_idx})


def _publish(**kv):
    """Merge these keys into the shared BOALF metric file.

    A scratch file the three acceptance scripts write in common, so a figure
    computed by one is visible to the others. Nothing downstream reads it: the
    acceptance-corrected numbers reached the board through notebook 10's own
    export, and this file stayed behind. It is kept because the scripts still
    cross-check against each other through it, and it is gitignored with the
    rest of the robustness outputs.
    """
    import json

    p = REPO_ROOT / "research/notebooks/robustness/_outputs/boalf_metrics.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur.update({k: str(v) for k, v in kv.items()})
    p.write_text(json.dumps(dict(sorted(cur.items())), indent=2) + "\n")
    print(f"published {len(kv)} keys -> {p}")


print(f"Scarcity half-hours : {len(tight_idx):,} across {len(days)} days")

# Online nameplate per day, from the store's PN — the same basis section 4 uses.
pn_store = S["fleet_pn"].copy()
pn_store["time"] = pd.to_datetime(pn_store["time"], utc=True)
pn_store = pn_store[pn_store["site"].isin(SITE_MW)]
ERA_START = fleet_perf.battery_era_start(pn_store, SITE_MW)
if ERA_START:
    keep = pd.Series(True, index=pn_store.index)
    for site, valid_from in ERA_START.items():
        keep &= ~((pn_store["site"] == site) & (pn_store["time"] < valid_from))
    pn_store = pn_store[keep]
pn_store["date"] = pn_store["time"].dt.date
span = pn_store.groupby("site")["date"].agg(["min", "max"])
all_days = pd.DatetimeIndex(sorted(pn_store["date"].unique()), tz="UTC")
online_mw = pd.Series(0.0, index=all_days)
for site, row in span.iterrows():
    live = (all_days.date >= row["min"]) & (all_days.date <= row["max"])
    online_mw[live] += SITE_MW.get(site, 0.0)

tight_set = set(tight_idx)
recs = []
failed = 0
for i, day in enumerate(days, 1):
    try:
        pn_rec = fetch_fleet.fetch_fleet_pn(day, POP)
        bo_rec = fetch_fleet.fetch_fleet_boalf(day, POP)
    except Exception:  # noqa: BLE001
        failed += 1
        continue
    if not pn_rec:
        continue
    valid = ERA_START
    for basis, prof in (
        ("pn", fleet_perf.site_profile(pn_rec, POP)),
        ("boa", fleet_perf.site_physical_profile(pn_rec, bo_rec, POP)),
    ):
        if prof.empty:
            continue
        p = prof.copy()
        p["time"] = pd.to_datetime(p["time"], utc=True)
        # Drop pre-battery history at reused connection points.
        if valid:
            for site, vf in valid.items():
                p = p[~((p["site"] == site) & (p["time"] < vf))]
        p = p[p["time"].isin(tight_set)]
        if p.empty:
            continue
        net = p.groupby("time")["mw"].sum()
        recs.append(pd.DataFrame({"time": net.index, "net": net.to_numpy(), "basis": basis}))
    if i % 50 == 0:
        print(f"  ... {i}/{len(days)} days")

if failed:
    print(f"  ({failed} days failed to fetch)")

allr = pd.concat(recs, ignore_index=True)
allr["online"] = online_mw.reindex(pd.DatetimeIndex(allr["time"]).normalize()).to_numpy()
allr = allr[allr["online"] > 0]
allr["norm"] = allr["net"] / allr["online"]

wide = allr.pivot_table(index="time", columns="basis", values="norm")
wide = wide.dropna()
print(f"\nScarcity half-hours with both bases: {len(wide):,}")

print("\n" + "=" * 72)
print("Response under scarcity: notifications vs acceptances")
print("=" * 72)


def report(label, sub):
    if sub.empty:
        return
    print(
        f"{label:<34} n={len(sub):>5}  "
        f"PN {sub['pn'].mean():+.4f}  BOA {sub['boa'].mean():+.4f}  "
        f"({(sub['boa'].mean() - sub['pn'].mean()):+.4f})"
    )


report("Full window 2018-2026", wide)
report("Pre-break (< 2023-10-01)", wide[wide.index < SKIP_END])
report("Modern (>= 2024-04-01)", wide[wide.index >= MODERN_START])

full = wide
print(
    f"\nShare of scarcity half-hours instructed UP  : " f"{(full['boa'] > full['pn']).mean():.0%}"
)
print(f"Share instructed DOWN                       : " f"{(full['boa'] < full['pn']).mean():.0%}")
pre = wide[wide.index < SKIP_END]
mod = wide[wide.index >= MODERN_START]
if len(pre) and len(mod):
    print(f"\nEra ratio on notifications : " f"{mod['pn'].mean() / pre['pn'].mean():.2f}x")
    print(f"Era ratio on acceptances   : " f"{mod['boa'].mean() / pre['boa'].mean():.2f}x")
wide.to_csv(REPO_ROOT / "research/notebooks/robustness/_outputs/boalf_scarcity.csv")
print("\nsaved -> research/notebooks/robustness/_outputs/boalf_scarcity.csv")

_pre, _mod = wide[wide.index < SKIP_END], wide[wide.index >= MODERN_START]
_publish(
    d1b_response_pn=f"{wide['pn'].mean():+.3f}",
    d1b_response_boa=f"{wide['boa'].mean():+.3f}",
    d1b_modern_pn=f"{_mod['pn'].mean():+.3f}",
    d1b_modern_boa=f"{_mod['boa'].mean():+.3f}",
    d1b_ratio_pn=f"{_mod['pn'].mean() / _pre['pn'].mean():.1f}x",
    d1b_ratio_boa=f"{_mod['boa'].mean() / _pre['boa'].mean():.1f}x",
    d1b_up_share=f"{(wide['boa'] > wide['pn']).mean() * 100:.0f}%",
    d1b_down_share=f"{(wide['boa'] < wide['pn']).mean() * 100:.0f}%",
    d1b_n=f"{len(wide):,}",
)
