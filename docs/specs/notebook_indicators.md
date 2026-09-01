# Notebook indicators — and whether the dashboard has them

Every indicator the ten notebooks compute, and where it stands on the live dashboard.
The companion to `docs/specs/dashboard_kpis.md`: that file says what the dashboard shows,
this one says what the research has that the dashboard does not.

**Status**

- **Yes** — on the dashboard now, same measure. The page is named.
- **Partly** — the dashboard has something close, but at a different scope or
  definition. The difference is stated, because that is the useful part.
- **No** — not on the dashboard, with the reason.

**Why a thing stays in the notebook.** Three reasons recur, and they are not the same:

| Reason | Meaning |
|---|---|
| *tier boundary* | Needs `fleet.research.census`, `fleet.research.coverage` or `fleet.research.ancillary`, which the dashboard may not import — see `docs/DATA_ARCHITECTURE.md` and `tests/test_profile_boundary.py`. |
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
| Re-optimisation deviation by hour of day | **Yes** | Market regimes — *Intraday re-optimisation by hour*, promoted from this notebook and cut by regime, which the notebook does not do |
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
| Third revenue stream (ancillary) | No | *tier boundary* — `fleet.research.ancillary` |
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
| Availability factor (ΣMELS ÷ online nameplate) | No | *needs data the dashboard does not fetch* — MELS measured at +1.02 MB/day, about +2s on a 30-day window with concurrent fetching. The cheapest promotion left |
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
| Census build and BMU classification | No | *tier boundary* — `fleet.research.census` |
| Coverage funnel / Tier-1 table | No | *tier boundary* |
| Symmetry-rule audit, recall check | No | *tier boundary* — census build quality |
| Persistent asset ID | No | *tier boundary* |
| Robustness to the size threshold | No | *tier boundary* |
| Revenue stack: what is visible and what is not | Partly | Methodology explains which streams are estimated; the priced comparison is notebook work |
| Ancillary earnings by era | No | *tier boundary* — `fleet.research.ancillary` |

## 07 — Regime shift

Whether notebook 05's rising response is a trend or a step at the Open Balancing
Platform cutover. The window is 2018–2026 by construction: the question is what
changed across a break in October 2023, which a rolling 60-day window cannot
contain. Nothing here is promotable, and that is a property of the question.

| Indicator | On the dashboard? | Note |
|---|---|---|
| Fleet position normalised per MW online | Partly | The dashboard plots mean fleet net MW by margin band (*Alignment gap — Fleet response by de-rated margin*); it does not divide by capacity online, which is what makes eras comparable |
| Composition change across the break | No | *needs data the dashboard does not fetch* — multi-year by construction |
| Response by era | No | Same |
| Step vs slope vs step+slope by AIC | No | Same. The preferred model, the break date and the 3.4× fleet ratio are all statements about an eight-year series |
| Fixed panel of 35 sites reporting in both eras | No | Same — the control for composition needs both eras present |
| Response at matched de-rated margin | Partly | The dashboard conditions on margin bands, but within one window; the notebook's point is the comparison *between* eras at matched tightness |

## 08 — Stress response, modern era

Notebook 05's measurements re-cut from April 2024. It is the closest of the four
to the dashboard's window, and still mostly out of reach — because it anchors to
absolute operator thresholds (`LoLP >= 1e-4`, `DRM < 1 GW`, CMN issued) that a
rolling summer window does not reach. The dashboard says so itself on ALN-18.

| Indicator | On the dashboard? | Note |
|---|---|---|
| Fixed conditioning sets, never re-estimated in-window | No | *needs data the dashboard does not fetch* — the dashboard bands by window quantile precisely because absolute thresholds render empty here (ALN-17) |
| How far inside the LOLE standard the system sat | Partly | ALN-18 states what the window contained — tightest margin against the 1,000 MW bar, and whether loss of load rose above zero. It does not report LOLE hours against the 3-hour standard |
| State of charge at scarcity onset | Partly | ALN-4 reports readiness at onset, but for a top-decile **load** block. Different ruler: utilisation, not scarcity |
| Response by conditioning set | Partly | ALN-15 and ALN-17 answer the same question against de-rated margin, on window quantiles rather than the absolute bar |
| Events, and how the fleet moves through them | No | *needs data the dashboard does not fetch* — 45 events over two years; a summer window carries none |
| How hard individual sites push under scarcity | No | Same. The dashboard has per-site money and coverage (ALN-12), not per-site scarcity response |
| Both eras on one set of rules | No | Multi-year by construction |

## 09 — Model vs fleet, one yardstick

Puts the benchmark and the real fleet on the same ruler. The ruler is on the
dashboard; the counterfactual that makes the comparison meaningful is not, because
it needs declared availability (MELS) and the census denominators.

| Indicator | On the dashboard? | Note |
|---|---|---|
| The yardstick — top-decile residual load | **Yes** | Alignment gap — ALN-2, the same classifier (`live.resilience.classify_periods`) |
| What the fleet actually delivered, MWh | Partly | Fleet performance — FLT-8 carries fleet volume on delivery; the notebook restricts it to top-decile hours |
| Achievable delivery — the MELS counterfactual | No | *needs data the dashboard does not fetch* — declared availability is the one feed that would unlock this, and it is the cheapest promotion left (see below) |
| Fleet 85% and model 82% of achievable, a 3-point gap | No | The headline; needs the counterfactual above |
| Ancillary as the competing explanation | No | *tier boundary* — `fleet.research.ancillary` |
| Denominator sensitivity — declared vs nameplate vs registry | No | *tier boundary* — `fleet.research.coverage`, and the point of the section is that the choice of denominator moves the answer |
| Availability gap, state-of-charge sensitivity | No | *needs data the dashboard does not fetch* — MELS, plus the inferred-SoC scheme |

## 10 — Acceptances

The one notebook whose central correction the dashboard **already applies**.
`live_app` fetches BOALF per day and rebuilds the physical position from it,
falling back to notifications only when acceptances have not published yet.

| Indicator | On the dashboard? | Note |
|---|---|---|
| Delivery measured on acceptances, not notifications | **Yes** | Fleet performance — the page computes throughput, cycles and capture spread on the corrected position, and says so in its header |
| Notified against instructed volume | **Yes** | FLT-8 splits each direction by market, signed, so an accepted bid removes discharge |
| Size of the correction over a pinned window | Partly | The dashboard states the effect for its own window (~25% below notified); the notebook's 27% is a different, pinned window and is not a dashboard figure |
| Achievable denominators, declared and nameplate | No | *needs data the dashboard does not fetch* — MELS again |
| Response under scarcity, notified vs corrected | No | *needs data the dashboard does not fetch* — the scarcity lane needs years |
| Readiness at onset, notified vs corrected | No | Same |
| Gate-closure decomposition — planned, delivered, instructed away | Partly | FLT-8 shows the same split as a volume chart; the decomposition into shares is notebook work |

---

## What this says

Of the indicators about the GB battery market now — notebooks 03 to 10, setting
aside the two virtual-trading notebooks — the dashboard carries the operational
core: the benchmark's earnings and dispatch, the alignment scores, the tier ladder,
the fleet's response to tightening margins, and delivery measured on acceptances
rather than notifications.

What it does not carry falls into three groups, and only one is a decision still open:

1. **Multi-year or full-census work** — the regime shift, the era comparison, trends
   across winters, the census itself. Notebook 07 is entirely of this kind, and most of
   08 is. These are the notebooks' reason to exist and should stay there.
2. **Feeds outside the daily diet** — declared availability (MELS), cashout prices,
   every forecast horizon. Each is addable at a measured cost, and each would need to
   earn it.
3. **Research-grade uncertainty** — bootstrap intervals, matched controls, sensitivity
   sweeps. The dashboard states point figures; whether that is honest enough for a
   presentation surface is a judgement worth making deliberately rather than by default.

Mapping 09 and 10 sharpens the second group into a single item. **Declared availability
is the one feed standing between the dashboard and a whole class of results**: it is the
denominator in notebook 09's counterfactual, in notebook 10's achievable shares, and in
notebook 05's availability factor. One feed, reusing `site_limit_profile`, which already
exists and is lite-safe. Measured cost is +1.02 MB/day and roughly +2s on a 30-day window
now that day fetches run concurrently — so the question is whether those metrics earn a
page, not whether the dashboard can afford them.

Nothing else on this sheet is a near-term promotion. The rest is either barred by the
tier boundary, or it is asking a question a 60-day rolling window cannot answer.
