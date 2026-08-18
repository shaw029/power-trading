# Dashboard KPI sheet

What the live dashboard shows, page by page, in plain terms.

**This is both the record and the plan.** The **Status** column says where each row stands:

- **Built** — on the dashboard now.
- **Added** — you want it; it doesn't exist yet.
- **Removed** — on the dashboard now, but it should come off.
- **Changed** — on the dashboard now, but this row describes something different from what is there.

To plan, edit this file: add a row marked *Added*, mark an existing row *Removed*, reword one
to change what it says, or move one between pages. That edit is the instruction — hand the file
over and every *Added* and *Removed* row is the job. Both flip to *Built* (or disappear) once
the dashboard matches.

Types are **Number**, **Graph**, **Table** and **Filter** — that's the distinction design
cares about.

## Design conventions

Decisions that apply to the whole dashboard, not one page. New rows follow them; existing
pages are brought into line when we next work on them.

| Convention | Rule | Rolled out |
|---|---|---|
| **Units** | The unit sits on a second label line beneath the name — "Avg wholesale price" over "£/MWh" — and the value stays a bare number (`62`). Labels render in muted grey, so the unit reads as a caption and the eye can compare magnitudes down a row without stepping over a currency sign. | System overview · Fleet performance |
| **Percentages** | The exception to the above: the sign stays welded to the value (`68%`) and the label carries no unit line. A percent sign is read at a glance; a whole line for it is noise. | System overview · Fleet performance |
| **Tooltips** | A chart with unified hover already prints the date or time once in its header, so no series repeats it. Charts using closest-hover still carry it, because there is no header to carry it for them. | All charts |
| **Ranges in tooltips** | A band named for a range shows both ends — "Min–max £-15 → £180", never one number beside a two-ended label. | All charts |

**Pending:** the unit and percentage rules are live on System overview and Fleet performance —
the two pages rebuilt so far. The remaining six get them as they are opened, a page at a time,
so every change carries its own review rather than being scattered through unrelated work.

## How the pages are grouped

The sidebar nav has four groups, and the grouping means something: it separates what is
simulated from what actually happened, and keeps analysis that mixes the two in its own place.

| Group | Pages | What the group is |
|---|---|---|
| **Benchmark** | Day · History | The simulated battery. Numbers here come from a model, not the market. |
| **GB power system** | System overview · Fleet performance | Observed reality. Nothing simulated, so the battery settings are hidden. |
| **Research** | Day types · Benchmark vs fleet · Alignment gap | Analysis that uses both sides. |
| **About** | Methodology | What every number means, and what it isn't. |

Day is the default landing page and the only place a single day is chosen; the research pages
pick their own example days and say so.

---

## Filters — always on the sidebar

These set which days every page is about.

| ID | Shows | Type | What it does | Status |
|---|---|---|---|---|
| GLB-1 | Period | Filter | Last 7 / 14 / 30 / 60 days, or a custom range. Defaults to 30 days. | Built |
| GLB-2 | Day types | Filter | Show only windy days, volatile days, weekends, and so on. Nothing selected means all days. | Built |

## Battery settings — sidebar, on the simulated pages only

Change one and the whole simulation re-runs, but only after **Apply**. Hidden on the two
pages that show real-world data, since they aren't affected.

| ID | Shows | Type | What it does | Status |
|---|---|---|---|---|
| GLB-3 | Duration | Filter | 1h, 2h or 4h of storage at 50 MW. | Built |
| GLB-4 | Cycle target | Filter | How hard the battery is allowed to work each day. | Built |
| GLB-5 | Degradation cost | Filter | What wear costs per MWh — higher makes it pickier about trades. | Built |
| GLB-6 | State-of-charge band | Filter | How full and how empty it's allowed to get. | Built |
| GLB-7 | Day-ahead commitment | Filter | How much of the battery the day-ahead auction may book, versus held back for intraday. | Built |

---

## Day — one day in full  ·  *Benchmark*

The landing page. Everything about a single delivery day.
*Data: day-ahead and intraday prices, generation, demand, the real fleet.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| DAY-1 | Day picker | Filter | Which day you're looking at. Defaults to the most recent. | Built |
| DAY-2 | Net PnL | Number | What the battery made that day, per MW, and how that compares to a typical day in the window. | Built |
| DAY-3 | DA benchmark | Number | What it would have made on the day-ahead plan alone, before any intraday trading. | Built |
| DAY-4 | Cycles | Number | How hard it worked — one cycle is one full discharge. | Built |
| DAY-5 | Capture | Number | How much of the day's available money it actually caught. | Built |
| DAY-6 | DA spread | Number | Cheapest to dearest hour — the raw opportunity before any strategy. | Built |
| DAY-7 | The day on one timeline | Graph | Prices, what it did, how full it was, and how stressed the grid was — all stacked on the same clock. | Built |
| DAY-8 | Dispatch vs grid stress | Graph | Did it discharge when the system was tight? | Built |
| DAY-9 | Prices | Graph | Day-ahead against intraday. | Built |
| DAY-10 | State of charge | Graph | How full it was through the day. | Built |
| DAY-11 | Where the money came from | Graph | Revenue broken into its parts. | Built |
| DAY-12 | This day vs the window | Graph | Was this a good day or a dull one? | Built |
| DAY-13 | Generation mix | Graph | What was powering GB that day (in a fold-out panel). | Built |
| DAY-16 | Realised shape | Graph | Mean dispatch and execution prices by hour of day, in a fold-out panel — what the battery physically did after intraday, as opposed to what it planned. | Built |
| DAY-14 | Half-hourly detail | Table | The underlying numbers, plus a CSV download. | Built |
| DAY-15 | Real batteries this day | Table | What actual GB sites earned. | Built |

## History — the whole window  ·  *Benchmark*

*Data: the simulation across every day shown.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| HIS-1 | Avg net PnL | Number | Typical earnings per MW per day — the unit every other page and every fleet estimate reports in. | Built |
| HIS-2 | Total net PnL | Number | Everything the 50 MW battery made across the window, in absolute pounds. | Built |
| HIS-3 | Positive days | Number | How many days closed in profit, out of how many. | Built |
| HIS-4 | Best day | Number | The high-water mark per MW, with the date beneath it. | Built |
| HIS-5 | Daily attribution | Graph | Each day's earnings split into where the money came from. | Built |
| HIS-6 | Price capture | Graph | Charging and discharging by hour of day across the whole window, against the average day-ahead price — when the battery trades, not just how much. | Built |
| HIS-7 | Explorer window | Filter | Day range for the explorer below, defaulting to the last 7 days. Drawing the full history at once made the page sluggish, so only the chosen slice is rendered. | Built |
| HIS-8 | Dispatch explorer | Graph | Hour by hour across the chosen days: prices, what the battery traded, and its state of charge on one timeline. | Built |

## System overview — the GB grid itself  ·  *GB power system*

No simulation here, only observed data. The page shifts from "what did GB generate" toward
"how expensive and how stretched was it" — prices and stress, not just the mix.
*Data: generation by fuel, demand, solar, day-ahead prices.*

**Prices here are day-ahead** (the auction price the benchmark trades against). Day-ahead is
hourly, so period counts on this page are hours. **Stress** is a half-hour in the top decile of
residual load across the window shown, the same definition the Alignment page uses — so it
moves when the date filter moves.

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| SYS-1 | Days shown | Number | How many days the active date filter covers. Sits as a small chip in the page header beside the date range — deliberately not a KPI tile, because it describes the filter rather than the grid. | Built |
| SYS-3 | Low-carbon share | Number | How much generation came from wind, solar, nuclear, hydro and biomass. | Built |
| SYS-5 | Generation mix over time | Graph | What powered GB day by day, aggregated into presentation groups. | Built |
| SYS-6 | Low-carbon over time | Graph | Is the mix getting cleaner across the window? | Built |
| SYS-8 | Average wholesale price | Number | Mean day-ahead price across the window. | Built |
| SYS-9 | Highest wholesale price | Number | The peak day-ahead price reached in the window. | Built |
| SYS-10 | Lowest wholesale price | Number | The floor day-ahead price in the window — below zero when generators paid to keep running. | Built |
| SYS-11 | Negative price count | Number | How many hours cleared below £0. | Built |
| SYS-12 | Max daily P90–P10 spread | Number | The widest single day between its top and bottom price deciles — the most tradable day in the window. | Built |
| SYS-13 | Max daily peak demand | Number | The highest demand reached in the window. | Built |
| SYS-14 | Max system stress | Number | The highest residual load (demand − wind − solar) — the biggest burden the rest of the fleet had to carry. | Built |
| SYS-15 | Daily price volatility | Graph | A daily envelope of min, P10, average, P90 and max price, so intraday spread is visible day by day. | Built |
| SYS-16 | Stress vs total demand | Graph | Daily peak demand against daily peak residual load — the gap between the two lines is what renewables covered. | Built |
| SYS-17 | Stress & negative-price frequency | Graph | Daily counts of the two ends of the story side by side: top-decile stress periods, and hours that cleared below £0. | Built |

**Placement.** SYS-1 is a badge in the page header beside the date range, not a tile. The eight
Numbers sit in two rows of four — low-carbon share, average price, highest price, lowest price,
then negative price count, max P90–P10 spread, max peak demand, max system stress. The five
Graphs run full width beneath them in this order: daily price volatility (directly under the
numbers, since most of them are prices), generation mix, low-carbon over time, stress vs total
demand, stress & surplus frequency.

Two places the mockup differs from this sheet, decided in favour of the sheet: the page keeps
the name **System overview** (it now covers prices, demand and stress, not just generation),
and SYS-17 carries **three** series, not the two its legend showed.

## Fleet performance — real GB batteries  ·  *GB power system*

Estimated from public data. Sites earning mainly from grid services look worse than they
are, so they're flagged rather than quietly mixed in.
*Data: real sites' declared output, market prices, balancing payments.*

**The numbers follow the metric switch.** Choosing a metric in FLT-2 re-computes the four
Numbers as well as every chart, so the page describes one thing at a time. Today those Numbers
are revenue-only whatever the switch says — that is the main change on this page.

**Capture spread** is total revenue ÷ total discharged MWh: gross margin on every MWh pushed
through the battery, normalised for power and duration at once, so a 500 MW site and a 34 MW
one compare honestly. It shares units with the degradation-cost lever, which makes it readable
against wear — a site earning less per MWh than its wear costs is losing money by trading.
It is deliberately **not** divided by days: £/MWh is already a rate, so a per-day version would
read 60× smaller over a 60-day window than over one day for identical trading, and would stop
being comparable to the degradation lever.

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| FLT-1 | Site / operator / region / duration | Filter | Narrow to specific physical batteries. | Built |
| FLT-2 | Metric switch | Filter | Revenue (£/MW/day), capture spread (£/MWh), cycles per day, volume (MWh/day) or capacity (MW). Every metric is a rate, so nothing grows just because the date filter widened. Re-computes every number and chart below. | Built |
| FLT-3 | Active capacity | Number | Total MW, total MWh, and how many sites are visible. | Built |
| FLT-4 | Operator dispersion | Number | Interquartile spread (P75 − P25) across the visible sites for the active metric — what skill and siting were worth. | Built |
| FLT-5 | Fleet baseline | Number | Median across the visible sites for the active metric — the typical real battery, robust to one outlier. | Built |
| FLT-6 | Top performer | Number | The winning site and the operator behind it, for the active metric. | Built |
| FLT-7 | Site league table | Graph | Horizontal bars ranking every visible site by the active metric. | Built |
| FLT-8 | Fleet over time | Graph | Whole-fleet daily trajectory for the active metric — what the fleet did. | Built |
| FLT-12 | Typical site by day | Graph | The median site with an interquartile band and the full min–max range behind it, for the active metric — what *a site* did, which differs from the fleet total when one large battery carries a day. The gap between the two bands is the tail the quartiles deliberately hide. | Built |
| FLT-9 | Site detail | Table | Site, operator, duration, capacity, total revenue, total cycles and capture spread. | Built |
| FLT-10 | By optimiser | Graph | The active metric aggregated by trading party — the cut a per-site ranking cannot show. | Built |
| FLT-11 | By region | Graph | The active metric aggregated by GB region. | Built |

## Day types — what kind of day pays  ·  *Research*

*Data: day tags from the classifier, plus simulated earnings.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| DTY-1 | Earnings by day type | Graph | Which kinds of day actually pay. | Built |
| DTY-2 | Which tags travel together | Graph | Windy days are often also low-price days, etc. | Built |
| DTY-3 | How common each type is | Graph | Frequency of each kind of day. | Built |
| DTY-4 | Trading shape by type | Graph | Does it trade differently on a windy day? | Built |
| DTY-5 | Days behind the tags | Table | Which real dates sit in each group. | Built |

## Benchmark vs fleet — simulation against reality  ·  *Research*

*Data: the simulation and the real fleet over the days they share.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| SVF-1 | Include grid-services sites | Filter | Off by default — including them exaggerates the gap. | Built |
| SVF-2 | Simulation ceiling | Number | The best a perfect trader could have done. | Built |
| SVF-3 | Real fleet average | Number | What real batteries actually made on the same footing. | Built |
| SVF-4 | Realisation | Number | Real earnings as a share of the ceiling — the headline gap. | Built |
| SVF-5 | Sites compared | Number | How many real batteries are in the comparison. | Built |
| SVF-6 | Day by day | Graph | Simulation against fleet over time. | Built |
| SVF-7 | Trading shape | Graph | Do real batteries trade at the same hours? | Built |
| SVF-8 | Gap by day type | Graph | On which kinds of day does reality fall furthest short? | Built |
| SVF-9 | Per-site vs the ceiling | Graph | Each site's £/MW/day split into the wholesale leg and the balancing leg, against the simulation ceiling drawn as a reference line. Only the wholesale leg is comparable — the sim does not play the balancing market. | Built |
| SVF-10 | Work rate vs earnings | Graph | Every site plotted by cycles per day against £/MW/day, with the benchmark starred — does trading harder actually pay? | Built |

## Alignment gap — does profit serve the grid?  ·  *Research*

The research page, and the busiest one: eight Numbers in two rows.
*Data: grid stress signals, the operator's own margin warnings, the simulation, the fleet.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| ALN-1 | Exemplar day | Filter | Picks the most stressed day automatically; override to inspect another. | Built |
| ALN-2 | Stress coverage | Number | How much of its discharge landed when the grid was tight. | Built |
| ALN-3 | Surplus absorption | Number | How much of its charging landed when power was abundant. | Built |
| ALN-4 | Readiness | Number | How full it was when stress began — the energy actually available. | Built |
| ALN-5 | Cost of full alignment | Number | What it would cost to always serve the grid instead of the spread. | Built |
| ALN-6 | Tightest margin | Number | The thinnest the grid's spare capacity got, and when. | Built |
| ALN-7 | Risk periods | Number | How many half-hours the operator saw real risk of falling short. | Built |
| ALN-8 | Coverage at confirmed stress | Number | Same as ALN-2, but judged against the operator's own margin data instead of our proxy. | Built |
| ALN-9 | Capacity Market Notices | Number | Formal shortfall warnings. Usually "None in window" — they're rare by design. | Built |
| ALN-10 | Exemplar day dispatch | Graph | The chosen day against grid stress. | Built |
| ALN-11 | System tightness | Graph | Spare capacity over the window, with risk periods and warnings marked. | Built |
| ALN-12 | Profit vs alignment | Graph | Every real site plotted on money against grid service. | Built |
| ALN-13 | Cost by day type | Graph | Which days make alignment expensive. | Built |
| ALN-14 | Tightest periods | Table | The hardest half-hours, and what each battery did. | Built |

## Methodology  ·  *About*

Plain-English explanation of every number above, plus a glossary. Nothing computed.
