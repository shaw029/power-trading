# Notebook indicators — and whether the dashboard has them

Every indicator the six notebooks compute, and where it stands on the live dashboard.
The companion to `specs/dashboard_kpis.md`: that file says what the dashboard shows,
this one says what the research has that the dashboard does not.

**Status**

- **Yes** — on the dashboard now, same measure. The page is named.
- **Partly** — the dashboard has something close, but at a different scope or
  definition. The difference is stated, because that is the useful part.
- **No** — not on the dashboard, with the reason.

**Why a thing stays in the notebook.** Three reasons recur, and they are not the same:

| Reason | Meaning |
|---|---|
| *tier boundary* | Needs `fleet.census`, `fleet.coverage` or `fleet.ancillary`, which the dashboard may not import — see `DATA_ARCHITECTURE.md` and `tests/test_profile_boundary.py`. |
| *needs data the dashboard does not fetch* | A feed or horizon outside the rolling 60-day, four-feed diet. Addable, at a download cost. |
| *out of scope* | A different asset or question from "what is the GB battery market doing now". |

---

## 01 — Day-ahead positioning backtest

Virtual trading against imbalance, not a battery. Nothing here belongs on a BESS
dashboard; listed for completeness.

| Indicator | On the dashboard? | Note |
|---|---|---|
| Seasonally-aware baseline | No | *out of scope* — virtual trading strategy |
| Model selection, imbalance proxy | No | *out of scope* |
| Nested walk-forward hyperparameter calibration | No | *out of scope* |
| Sharpe heatmap over the signal sweep | No | *out of scope* |
| Production tear sheet, capital context | No | *out of scope* |
| Naive-baseline decomposition | No | *out of scope* |

## 02 — Hybrid execution hedge ratio

Same asset as 01. Out of scope throughout.

| Indicator | On the dashboard? | Note |
|---|---|---|
| Equity curves at key hedge ratios | No | *out of scope* |
| Archetype tear sheet | No | *out of scope* |
| Risk/reward efficient frontier | No | *out of scope* |
| Hedge-ratio optimisation sweep | No | *out of scope* |
| Worst-drawdown table | No | *out of scope* |

## 03 — BESS dispatch analysis

The 2018 out-of-sample backtest. Much of this became the benchmark pages.

| Indicator | On the dashboard? | Note |
|---|---|---|
| PnL waterfall | **Yes** | Daily summary — *Optimiser PnL bridge* |
| Dispatch explorer (prices, trades, SOC on one clock) | **Yes** | Optimiser performance — *Dispatch explorer* |
| Rebalancing impact: DA schedule vs final dispatch | **Yes** | Daily summary — *Optimiser dispatch — plan vs realised* |
| Price capture — charge/discharge profile vs DA price | **Yes** | Optimiser performance — *Price capture* |
| Monthly revenue breakdown | Partly | Dashboard splits by **day**, not month (*Daily attribution*); a 60-day window has no months to speak of |
| SOC distribution over time of day | Partly | Market regimes shows mean SOC **by regime**, not a distribution over all days |
| Dispatch efficiency — committed vs actual | Partly | The plan-vs-realised chart shows the gap; the scalar efficiency ratio is not reported |
| Intraday re-optimisation footprint | Partly | Reported as *Avg intraday improvement* and *Market reliance by regime*, not as a footprint chart |
| Re-optimisation deviation by hour of day | Partly | Visible inside the plan-vs-realised chart, not as its own view |
| Equity curve | No | Builder exists (`chart_equity_curve`) but no live page uses it — a 60-day cumulative line said little |
| Drawdown / daily PnL distribution | No | Risk framing belongs to a strategy tear sheet, not a market view |
| Degradation vs gross revenue, cumulative | No | Degradation appears as one bar of the PnL bridge instead |
| DA capacity allocation frontier | No | The **allocation lever** is on the sidebar; the frontier that justifies a setting is notebook work |
| Duration comparison | No | Builder exists, unused live — duration is a sidebar lever, so the page shows one at a time |

## 04 — Alignment gap

The priced-benchmark narrative. Most of the headline numbers are on the Alignment gap page.

| Indicator | On the dashboard? | Note |
|---|---|---|
| Benchmark revenue over the window | **Yes** | Optimiser performance — *Avg net PnL* |
| Stress / surplus classification | **Yes** | Alignment gap, and GB system's stress metrics |
| Stress coverage | **Yes** | Alignment gap — *Stress coverage* |
| Surplus absorption | **Yes** | Alignment gap — *Surplus absorption* |
| Readiness at stress onset | **Yes** | Alignment gap — *Readiness* |
| Cost of full alignment | **Yes** | Alignment gap — *Cost of full alignment* |
| Alignment cost by day type | **Yes** | Alignment gap — *Cost by day type* |
| Real fleet on the profit/alignment plane | **Yes** | Alignment gap — *Profit vs alignment* |
| Exemplar-day dispatch against system state | **Yes** | Alignment gap — *Exemplar day dispatch* |
| Fleet median stress coverage | Partly | The scatter shows every site; the median is not stated as a number |
| Stress delivery forgone (MWh) | Partly | The **cost** is a KPI; the MWh it buys is not |
| Alignment frontier — the λ sweep | No | *needs data the dashboard does not fetch* — re-solves the LP many times per window; the dashboard solves it once |
| "Nearly all the alignment is nearly free" | No | The frontier's headline; same reason |
| Duration moves the frontier further than money | No | Needs the frontier at several durations |
| Dispatch–residual correlation | No | A single scalar the page's charts already imply |
| Coverage–revenue correlation | No | Same — the scatter shows it, the number is not printed |
| Third revenue stream (ancillary) | No | *tier boundary* — `fleet.ancillary` |
| Winter cross-check on 2018 prices | No | *needs data the dashboard does not fetch* — outside the rolling window |
| Bootstrap confidence intervals on the headlines | No | Research-grade uncertainty; the dashboard states point figures |

## 05 — Stress response study

The three-winter fleet study. Its RQ2 is now on the dashboard; the rest needs either
a longer window or feeds the dashboard does not carry.

| Indicator | On the dashboard? | Note |
|---|---|---|
| System tightness across the window | **Yes** | Alignment gap — *System tightness* |
| LoLP / de-rated margin classification, tier ladder | **Yes** | Alignment gap — tier-2 metrics |
| Capacity Market Notices | **Yes** | Alignment gap — *Capacity Market Notices* |
| **RQ2 — fleet net position as the system tightens** | **Yes** | Alignment gap — *Fleet response by de-rated margin*, added from this notebook. Bands are window quantiles rather than fixed GW thresholds, because a rolling summer window never reaches scarcity |
| RQ1 — fleet response by system state | Partly | The margin-band chart answers the same question against DRM; the notebook also conditions on LoLP percentile and CMN windows |
| CMN case studies (48h panels per notice) | Partly | The dashboard counts notices; it does not draw the event |
| Feed coverage by week | No | *out of scope* — a build-quality check for a three-year store |
| Fleet buildout over the window | No | *needs data the dashboard does not fetch* — 60 days shows no buildout |
| Availability factor (ΣMELS ÷ online nameplate) | No | *needs data the dashboard does not fetch* — MELS would be a fourth per-day feed |
| Inferred state of charge, stressed vs all periods | No | Needs the SoC inference scheme and its usability filter |
| Trend by quarter / three winters with CIs | No | *needs data the dashboard does not fetch* — multi-year by construction |
| RQ3 — advance visibility, hours of warning | No | Needs **all** forecast horizons; the dashboard keeps the latest print per period |
| RQ3 — SoC and dispatch running into stress | No | Needs inferred SoC plus matched controls |
| RQ3 — event study around the trigger | No | Same |
| RQ4 — cashout spike frequency by discharge quartile | No | *needs data the dashboard does not fetch* — system buy price / NIV |
| RQ4 — Volatility Dampening Index | No | Same, plus a matched design the notebook argues for at length |

## 06 — Fleet coverage census

The denominator for every fleet claim. The dashboard **states** these figures rather
than computing them — that is the rule, not an omission.

| Indicator | On the dashboard? | Note |
|---|---|---|
| Representativeness — sites, MW, MWh covered | **Yes**, as a statement | Methodology — the `SCOPE` block quotes the MW share and points at this notebook |
| Gap characterised by size band | **Yes**, as a statement | Same block: 70% coverage above 200 MW, 14% in the 20–50 MW band |
| Census build and BMU classification | No | *tier boundary* — `fleet.census` |
| Coverage funnel / Tier-1 table | No | *tier boundary* |
| Symmetry-rule audit, recall check | No | *tier boundary* — census build quality |
| Persistent asset ID | No | *tier boundary* |
| Robustness to the size threshold | No | *tier boundary* |
| Revenue stack: what is visible and what is not | Partly | Methodology explains which streams are estimated; the priced comparison is notebook work |
| Ancillary earnings by era | No | *tier boundary* — `fleet.ancillary` |

---

## What this says

Of the indicators that are **about the GB battery market now** — notebooks 03 to 06,
setting aside the two virtual-trading notebooks — the dashboard carries the operational
core: the benchmark's earnings and dispatch, the alignment scores, the tier ladder, and
now the fleet's response to tightening margins.

What it does not carry falls into three clean groups, and only one of them is a decision
still open:

1. **Multi-year or full-census work** — trends across winters, buildout, the census
   itself. These are the notebook's reason to exist and should stay there.
2. **Feeds outside the daily diet** — MELS availability, cashout prices, every forecast
   horizon. Each is addable at a measured download cost, and each would need to earn it.
3. **Research-grade uncertainty** — bootstrap intervals, matched controls, sensitivity
   sweeps. The dashboard states point figures; whether that is honest enough for a
   presentation surface is a judgement worth making deliberately rather than by default.

The nearest thing to a free promotion left is **RQ1's availability factor**: one extra
feed (MELS), reusing `site_limit_profile`, which already exists and is lite-safe.
