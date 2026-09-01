"""The acceptance correction across the whole window, for state of charge.

Sections 4's readiness figures (charge at onset, energy still held at the
deepest point) integrate state of charge from physical notifications across the
whole 2018-2026 window. A notification is a plan; acceptances overwrite it. That
integration therefore needs the corrected series for every day, not just the
days carrying a scarcity half-hour.

Writes the corrected per-site half-hourly profile beside the shared store, then
recomputes fleet state of charge and the event decomposition on both bases.

Expect several minutes on a warm cache.
"""

import datetime as dt
import sys
import time
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
from fleet import fetch_fleet  # noqa: E402
from fleet import performance as fleet_perf  # noqa: E402
from fleet.population import census_population  # noqa: E402

from scripts import build_stress_store as bss  # noqa: E402

census.SNAPSHOT = dt.date(2026, 8, 24)
START, END = dt.date(2018, 1, 1), dt.date(2026, 8, 24)
ETA_C = ETA_D = 0.94
LOLP_RULE = 1e-4
SKIP_END = pd.Timestamp("2023-10-01", tz="UTC")
MODERN_START = pd.Timestamp("2024-04-01", tz="UTC")


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


OUT = Path("data/processed/fleet_boa_profile.parquet")

POP = census_population()
SITE_MW = {s.site: s.power_mw for s in POP.sites}
SITE_MWH = {s.site: s.capacity_mwh for s in POP.sites}
S = bss.load_store(bss.store_for(POP))

days = pd.date_range(START, END, freq="D").date

if OUT.exists():
    print(f"Reusing {OUT}")
    boa = pd.read_parquet(OUT)
    boa["time"] = pd.to_datetime(boa["time"], utc=True)
else:
    print(f"Painting {len(days):,} days of PN + acceptances ...")
    t0 = time.time()
    parts, failed = [], 0
    for i, day in enumerate(days, 1):
        try:
            pn_rec = fetch_fleet.fetch_fleet_pn(day, POP)
            bo_rec = fetch_fleet.fetch_fleet_boalf(day, POP)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        if not pn_rec:
            continue
        prof = fleet_perf.site_physical_profile(pn_rec, bo_rec, POP)
        if not prof.empty:
            parts.append(prof)
        if i % 250 == 0:
            el = time.time() - t0
            print(
                f"  {i}/{len(days)} days  ({el:,.0f}s elapsed, "
                f"~{el / i * (len(days) - i):,.0f}s left)"
            )
    print(f"  fetch/paint failures: {failed}")
    boa = pd.concat(parts, ignore_index=True)
    boa["time"] = pd.to_datetime(boa["time"], utc=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    boa.to_parquet(OUT, index=False)
    print(f"  saved {len(boa):,} rows -> {OUT}  ({time.time() - t0:,.0f}s)")

pn = S["fleet_pn"].copy()
pn["time"] = pd.to_datetime(pn["time"], utc=True)
pn = pn[pn["site"].isin(SITE_MW)]
boa = boa[boa["site"].isin(SITE_MW)]

# Same pre-battery correction on both bases.
ERA_START = fleet_perf.battery_era_start(pn, SITE_MW)
for name in ("pn", "boa"):
    frame = pn if name == "pn" else boa
    if ERA_START:
        keep = pd.Series(True, index=frame.index)
        for site, vf in ERA_START.items():
            keep &= ~((frame["site"] == site) & (frame["time"] < vf))
        if name == "pn":
            pn = frame[keep]
        else:
            boa = frame[keep]

grid = pd.DatetimeIndex(sorted(set(pn["time"]) | set(boa["time"]))).sort_values()
print(f"\nGrid: {len(grid):,} half-hours  |  PN rows {len(pn):,}  BOA rows {len(boa):,}")

prints = S["lolpdrm_prints"]
final = (
    prints.sort_values(["horizon", "publish_time"], ascending=[True, False])
    .drop_duplicates("time")
    .set_index("time")[["lolp"]]
    .sort_index()
)
tight = (final["lolp"] >= LOLP_RULE).reindex(grid).fillna(False)

results = {}
for name, frame in (("pn", pn), ("boa", boa)):
    out = fleet_perf.fleet_state_of_charge(frame, grid, SITE_MWH, SITE_MW, ETA_C, ETA_D)
    results[name] = out
    print(
        f"{name}: usable sites {len(out['usable'])}, "
        f"skipped (no MWh) {len(out['skipped_no_mwh'])}"
    )


def events(mask, bridge=2, min_len=2):
    m = mask.to_numpy().copy()
    idx = np.flatnonzero(m)
    if idx.size == 0:
        return []
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= bridge + 1:
            m[a:b] = True
    ev, start = [], None
    for i, v in enumerate(m):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                ev.append((start, i))
            start = None
    if start is not None and len(m) - start >= min_len:
        ev.append((start, len(m)))
    return ev


ev = events(tight)
print(f"\nEvents: {len(ev)}")

print("\n" + "=" * 74)
print("Readiness on notifications vs acceptances")
print("=" * 74)

rows = []
for name in ("pn", "boa"):
    soc = results[name]["soc"].reindex(grid)
    for label, sub in (
        ("full 2018-2026", ev),
        ("modern >= 2024-04", [e for e in ev if grid[e[0]] >= MODERN_START]),
    ):
        if not sub:
            continue
        onset = [soc.iloc[a] for a, _ in sub if not np.isnan(soc.iloc[a])]
        deepest = [
            np.nanmin(soc.iloc[a:b].to_numpy())
            for a, b in sub
            if not np.all(np.isnan(soc.iloc[a:b].to_numpy()))
        ]
        rows.append(
            {
                "basis": name,
                "window": label,
                "events": len(sub),
                "onset_soc_median": float(np.median(onset)) if onset else np.nan,
                "held_at_deepest": float(np.median(deepest)) if deepest else np.nan,
            }
        )
r = pd.DataFrame(rows)
print(r.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

print("\nCharge at onset (median across events):")
for w in r["window"].unique():
    a = r[(r["basis"] == "pn") & (r["window"] == w)]["onset_soc_median"].iloc[0]
    b = r[(r["basis"] == "boa") & (r["window"] == w)]["onset_soc_median"].iloc[0]
    print(f"  {w:<20} PN {a:.0%}  →  acceptances {b:.0%}   ({(b - a) * 100:+.1f} pts)")
print("\nEnergy still held at the deepest point (median):")
for w in r["window"].unique():
    a = r[(r["basis"] == "pn") & (r["window"] == w)]["held_at_deepest"].iloc[0]
    b = r[(r["basis"] == "boa") & (r["window"] == w)]["held_at_deepest"].iloc[0]
    print(f"  {w:<20} PN {a:.0%}  →  acceptances {b:.0%}   ({(b - a) * 100:+.1f} pts)")

r.to_csv(REPO_ROOT / "research/notebooks/robustness/_outputs/boalf_readiness.csv", index=False)
print("\nsaved -> research/notebooks/robustness/_outputs/boalf_readiness.csv")


def _pick(basis, window, col):
    m = r[(r["basis"] == basis) & (r["window"] == window)]
    return float(m[col].iloc[0]) if len(m) else float("nan")


_publish(
    d1c_onset_pn=f"{_pick('pn', 'full 2018-2026', 'onset_soc_median'):.0%}",
    d1c_onset_boa=f"{_pick('boa', 'full 2018-2026', 'onset_soc_median'):.0%}",
    d1c_onset_modern_pn=f"{_pick('pn', 'modern >= 2024-04', 'onset_soc_median'):.0%}",
    d1c_onset_modern_boa=f"{_pick('boa', 'modern >= 2024-04', 'onset_soc_median'):.0%}",
    d1c_held_pn=f"{_pick('pn', 'full 2018-2026', 'held_at_deepest'):.0%}",
    d1c_held_boa=f"{_pick('boa', 'full 2018-2026', 'held_at_deepest'):.0%}",
    d1c_events=f"{len(ev)}",
)
