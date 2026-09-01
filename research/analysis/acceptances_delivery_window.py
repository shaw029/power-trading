"""D1 — what Balancing Mechanism acceptances do to the fleet's measured delivery.

Every fleet quantity on the poster is built from Final Physical Notifications.
A PN is a plan submitted at gate closure; after it, NESO accepts bids and
offers that instruct the unit away from that plan. Actual output is PN
overwritten by those acceptances, which is what `fleet.performance.
site_physical_profile` reconstructs on a minute grid.

This recomputes section 3's top-decile delivery both ways over the pinned
summer window — PN alone, and PN corrected by acceptances — so the difference
is the answer. The achievable denominators are untouched, so the whole change
is attributable to the correction.

"""
import datetime as dt
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# Located from this file, not the working directory, so the script runs the
# same from anywhere.
REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()
)
sys.path.insert(0, str(REPO_ROOT))
warnings.filterwarnings("ignore")

from fleet.research import census  # noqa: E402
from fleet import fetch_fleet  # noqa: E402
from fleet import performance as fleet_perf  # noqa: E402
from fleet.population import census_population  # noqa: E402

from scripts import build_stress_store as bss  # noqa: E402

census.SNAPSHOT = dt.date(2026, 8, 24)
WIN_START, WIN_END = dt.date(2026, 6, 26), dt.date(2026, 8, 24)

POP = census_population()
SITE_MW = {s.site: s.power_mw for s in POP.sites}
S = bss.load_store(bss.store_for(POP))

resid = S["system"]["residual_mw"].loc[
    pd.Timestamp(WIN_START, tz="UTC"):pd.Timestamp(WIN_END, tz="UTC") + pd.Timedelta(days=1)
].dropna()
thresh = float(resid.quantile(0.90))
stress_hh = resid >= thresh


def _publish(**kv):
    """Merge these keys into the shared BOALF metric file.

    A scratch file the three acceptance scripts write in common, so a figure
    computed by one is visible to the others. Nothing downstream reads it: the
    acceptance-corrected numbers reached the board through notebook 10's own
    export, and this file stayed behind. It is kept because the scripts still
    cross-check against each other through it, and it is gitignored with the
    rest of research/outputs.
    """
    import json
    p = REPO_ROOT / "research/outputs/boalf_metrics.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur.update({k: str(v) for k, v in kv.items()})
    p.write_text(json.dumps(dict(sorted(cur.items())), indent=2) + "\n")
    print(f"published {len(kv)} keys -> {p}")


print(f"Window          : {WIN_START} → {WIN_END}")
print(f"Top-decile bar  : {thresh / 1000:.1f} GW   ({int(stress_hh.sum())} half-hours)")
print("Fetching PN and BOALF per day (cached after the first run)...\n")

days = pd.date_range(WIN_START, WIN_END, freq="D").date
rows = []
for i, day in enumerate(days, 1):
    try:
        pn_rec = fetch_fleet.fetch_fleet_pn(day, POP)
        bo_rec = fetch_fleet.fetch_fleet_boalf(day, POP)
    except Exception as exc:                      # noqa: BLE001
        print(f"  {day}: fetch failed ({exc})")
        continue
    if not pn_rec:
        continue
    pn_prof = fleet_perf.site_profile(pn_rec, POP)
    boa_prof = fleet_perf.site_physical_profile(pn_rec, bo_rec, POP)
    for name, prof in (("pn", pn_prof), ("boa", boa_prof)):
        if prof.empty:
            continue
        p = prof.copy()
        p["time"] = pd.to_datetime(p["time"], utc=True)
        p = p[p["time"].isin(stress_hh[stress_hh].index)]
        if p.empty:
            continue
        disc = p.assign(mw=p["mw"].clip(lower=0))
        rows.append(disc.assign(basis=name))
    if i % 10 == 0:
        print(f"  ... {i}/{len(days)} days")

if not rows:
    raise SystemExit("no data fetched")

allp = pd.concat(rows, ignore_index=True)
# Half-hourly MW → MWh
by_basis = allp.groupby("basis")["mw"].sum() * 0.5
by_site = (allp.groupby(["basis", "site"])["mw"].sum() * 0.5).unstack(0)

print("\n" + "=" * 72)
print("D1 — top-decile delivered energy: PN alone vs PN corrected by acceptances")
print("=" * 72)
pn_mwh = float(by_basis.get("pn", np.nan))
boa_mwh = float(by_basis.get("boa", np.nan))
print(f"Delivered, final PN only          : {pn_mwh:>10,.0f} MWh")
print(f"Delivered, PN + BM acceptances    : {boa_mwh:>10,.0f} MWh")
print(f"Correction                        : {boa_mwh - pn_mwh:>+10,.0f} MWh "
      f"({(boa_mwh / pn_mwh - 1) * 100:+.1f}%)")

print("\nWhat that does to section 3's published shares (denominators unchanged):")
for label, achievable in (("vs nameplate", 264_469.0), ("vs declared (MELS)", 143_389.0)):
    print(f"  {label:<20}  PN {pn_mwh / achievable:5.0%}   "
          f"BOA-corrected {boa_mwh / achievable:5.0%}   "
          f"({(boa_mwh - pn_mwh) / achievable * 100:+.1f} points)")

if {"pn", "boa"} <= set(by_site.columns):
    d = by_site.dropna()
    d = d[d["pn"] > 0]
    d["delta_pct"] = (d["boa"] / d["pn"] - 1) * 100
    print(f"\nPer site (n={len(d)}): median change {d['delta_pct'].median():+.1f}%, "
          f"IQR {d['delta_pct'].quantile(.25):+.1f}% to {d['delta_pct'].quantile(.75):+.1f}%")
    print("Most instructed UP in top-decile hours:")
    print(d.nlargest(5, "delta_pct")[["pn", "boa", "delta_pct"]]
          .to_string(float_format=lambda v: f"{v:,.1f}"))
    print("Most instructed DOWN:")
    print(d.nsmallest(5, "delta_pct")[["pn", "boa", "delta_pct"]]
          .to_string(float_format=lambda v: f"{v:,.1f}"))
    d.to_csv(REPO_ROOT / "research/outputs/boalf_sites.csv")
    print("\nsaved -> research/outputs/boalf_sites.csv")

_publish(
    d1_window=f"{WIN_START} \u2192 {WIN_END}",
    d1_delivered_pn=f"{pn_mwh:,.0f} MWh",
    d1_delivered_boa=f"{boa_mwh:,.0f} MWh",
    d1_cut_pct=f"{(1 - boa_mwh / pn_mwh) * 100:.0f}%",
    d1_points_vs_declared=f"{abs(boa_mwh - pn_mwh) / 143_389.0 * 100:.0f} points",
)
