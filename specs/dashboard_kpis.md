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

Types are **Number**, **Graph**, **Table**, **Filter**, **Note** (a line of computed text, not
static prose) and **Download** — that's the distinction design cares about.

## Design conventions

Decisions that apply to the whole dashboard, not one page. New rows follow them; existing
pages are brought into line when we next work on them.

| Convention | Rule | Rolled out |
|---|---|---|
| **Units** | The unit sits on a second label line beneath the name — "Avg wholesale price" over "£/MWh" — and the value stays a bare number (`62`). Labels render in muted grey, so the unit reads as a caption and the eye can compare magnitudes down a row without stepping over a currency sign. | System overview · Fleet performance · Optimiser performance |
| **Percentages** | The exception to the above: the sign stays welded to the value (`68%`) and the label carries no unit line. A percent sign is read at a glance; a whole line for it is noise. | System overview · Fleet performance · Optimiser performance |
| **Tooltips** | A chart with unified hover already prints the date or time once in its header, so no series repeats it. Charts using closest-hover still carry it, because there is no header to carry it for them. | All charts |
| **Ranges in tooltips** | A band named for a range shows both ends — "Min–max £-15 → £180", never one number beside a two-ended label. | All charts |

**Pending:** the unit and percentage rules are live on the three pages rebuilt so far. The rest —
including Day, whose values still carry their units — get them as they are opened, a page at a
time, so every change carries its own review rather than being scattered through unrelated work.

## How the pages are grouped

The sidebar nav has four groups, and the grouping means something: it separates what is
simulated from what actually happened, and keeps analysis that mixes the two in its own place.

| Group | Pages | What the group is |
|---|---|---|
| **Benchmark** | Daily summary · Optimiser performance | The simulated battery. Numbers here come from a model, not the market. |
| **GB power system** | System overview · Fleet performance | Observed reality. Nothing simulated, so the battery settings are hidden. |
| **Research** | Day types · Benchmark vs fleet · Alignment gap | Analysis that uses both sides. |
| **About** | Methodology | What every number means, and what it isn't. |

Daily summary is the default landing page and the only place a single day is chosen; the research pages
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

## Daily summary — one day in full  ·  *Benchmark*  ·  URL `/daily`

The landing page. Everything about a single delivery day. Its twelve numbers sit in three
labelled groups, because they answer three different questions — what the model did, what the
grid did, and what the real fleet did — and ungrouped they read as one undifferentiated wall.
*Data: day-ahead and intraday prices, generation, demand, the real fleet.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| DAY-1 | Day picker | Filter | Which day you're looking at. Defaults to the most recent settled day and persists across pages; a filter change that strands the choice snaps it back to the latest. | Built |
| DAY-17 | Day-type tags | Note | The classifier's tags for this day (`windy`, `volatile`, and so on), as chips under the picker. Absent on a day with no clear character. | Built |
| — | **Baseline optimiser** | — | — | — |
| DAY-2 | Net PnL | Number | What the battery made today, per MW, against a typical day in the window. | Built |
| DAY-3 | Intraday improvement | Number | What re-optimising against the realised intraday price added on top of the day-ahead schedule, and its share of net PnL. Perfect foresight, so an upper bound. | Changed |
| DAY-4 | Cycles | Number | How hard it worked today, with the cycle target beside it. | Built |
| DAY-20 | Capture spread | Number | Gross margin per MWh discharged today. Same measure as the optimiser and fleet pages, and shares units with the degradation lever, so a day below it earned less per MWh than wear cost. | Added |
| — | **GB system** | — | — | — |
| DAY-6 | DA P90−P10 spread | Number | Cheapest to dearest decile today — the opportunity a battery could actually work. | Changed |
| DAY-21 | Peak & floor price | Number | The dearest and cheapest hours the auction cleared. A negative floor means generators paid to keep running. | Added |
| DAY-18 | Peak residual load | Number | The tightest the grid got today (demand − wind − solar), and how many half-hours were top-decile stress. | Changed |
| DAY-22 | Renewable share | Number | Wind, solar, hydro and biomass as a share of GB generation today — grounds the price volatility beside it. | Added |
| — | **Real GB fleet** | — | — | — |
| DAY-23 | Fleet median PnL | Number | What the typical real battery earned today, with how many sites reported. | Added |
| DAY-24 | Operator dispersion | Number | Interquartile spread across the real batteries today — what operator skill and siting were worth, measured where one exceptional site cannot move it. Mirrors FLT-4. | Built |
| DAY-25 | Fleet median cycles | Number | How hard the typical real battery worked, with the simulation's own cycles beside it. | Added |
| DAY-26 | Top real site | Number | The best-earning real battery today and the party trading it. | Added |
| DAY-16 | Optimiser dispatch — plan vs realised | Graph | What the simulated battery physically did by hour, against the day-ahead commitment it locked in — the ghost step line. The gap between them is the intraday reshaping. | Changed |
| DAY-11 | Optimiser PnL bridge | Graph | The day's PnL split into day-ahead revenue, intraday improvement, execution costs and degradation. | Changed |
| DAY-13 | Generation mix | Graph | What powered GB that day, with demand overlaid. | Changed |
| DAY-27 | Fleet dispersion | Graph | Every real site plotted by cycles today against £/MW, with the fleet medians as crosshairs and the optimiser starred. Shows the spread of physical strategies on the day — who traded smartest versus who just cycled hardest. | Built |
| DAY-15 | Real batteries this day | Table | In the **Fleet this day** panel: what actual GB sites earned, best first. | Built |

Dropped: **Capture** (net PnL as a share of the day-ahead optimum) and **DA benchmark**. Both
described the model against itself; the fleet group now answers the same question against
reality instead.

Rows are in screen order. The three panels at the foot of the page are fold-out expanders,
closed by default: **Battery detail**, **System detail**, **Fleet this day**.

## Baseline optimiser performance — the whole window  ·  *Benchmark*

Sidebar label: **Optimiser performance**  ·  URL `/optimiser`.

*Data: the simulation across every day shown.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| HIS-1 | Avg net PnL | Number | Typical earnings per MW per day — the unit every other page and every fleet estimate reports in. | Built |
| HIS-4 | Best / worst day | Number | The best and worst single day per MW with their dates — the spread shows how much of the average rests on a few days. | Built |
| HIS-11 | Avg intraday improvement | Number | What re-optimising against the realised intraday price added on top of the frozen day-ahead schedule, and its share of net PnL. Currently around an eighth of earnings — and the engine has perfect foresight, so it is the least replicable part of the headline. | Built |
| HIS-5 | Daily attribution | Graph | Each day's earnings split into where the money came from. | Built |
| HIS-6 | Price capture | Graph | Charging and discharging by hour of day, averaged per day, against the average day-ahead price — when the battery trades, not just how much. Per day rather than window totals, which would say more about the date filter than the battery. | Built |
| HIS-9 | Avg capture spread | Number | Margin on every MWh discharged, averaged over the window — the same measure the fleet page reports, so simulated and real batteries compare on margin. | Built |
| HIS-10 | Capture spread by day | Graph | That margin day by day, against the window mean and the degradation cost the lever is set to. Days below the wear line earned less per MWh than cycling cost. | Built |
| HIS-8 | Dispatch explorer | Graph | Hour by hour over exactly the days the sidebar selected: prices, what the battery traded, and its state of charge on one timeline. No day control of its own. | Built |

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
| SYS-1 | Days shown | Note | How many days the active date filter covers. Sits as a small chip in the page header beside the date range — deliberately not a KPI tile, because it describes the filter rather than the grid. | Built |
| SYS-3 | Renewable share | Number | Wind, solar, run-of-river hydro and biomass as a share of GB generation. Nuclear is clean but runs flat, so leaving it out keeps the number moving with the weather; pumped storage is excluded as storage, not a source. | Built |
| SYS-5 | Generation mix over time | Graph | What powered GB day by day, aggregated into presentation groups. | Built |
| SYS-6 | Renewable share over time | Graph | How much of GB ran on wind, solar, hydro and biomass, day by day — the variability a battery trades against. | Built |
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
*Data: real sites' notified output corrected by balancing-market acceptances, market prices, balancing payments.*

**Throughput is measured on delivery, not the plan.** A Physical Notification says what a battery intended; an accepted balancing instruction says what it was told to do instead. Over a recent week delivered throughput ran about 25% below notified, so cycles, volume and capture spread all use the corrected figure. Revenue still prices the notified position, with acceptances paid through the balancing cashflows.

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
| FLT-8 | Fleet over time | Graph | Whole-fleet daily trajectory for the active metric. On Volume it also splits each direction by market: solid is what the unit notified, hatched is what the balancing mechanism instructed on top — signed, since an accepted bid removes discharge. Together they show whether a day's throughput was traded or dispatched. | Built |
| FLT-12 | Typical site by day | Graph | The median site with an interquartile band and the full min–max range behind it, for the active metric — what *a site* did, which differs from the fleet total when one large battery carries a day. The gap between the two bands is the tail the quartiles deliberately hide. | Built |
| FLT-9 | Site detail | Table | Site, operator, duration, capacity, total revenue, total cycles and capture spread. | Built |
| FLT-10 | By optimiser | Graph | The active metric aggregated by trading party — the cut a per-site ranking cannot show. | Built |
| FLT-11 | By region | Graph | The active metric aggregated by GB region. | Built |

## Day types — what kind of day pays  ·  *Research*

*Data: day tags from the classifier, plus simulated earnings.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| DTY-1 | Capture rate by day type | Graph | How close the optimiser got to the perfect-foresight ceiling on each kind of day — a distribution, with every day plotted, not one number per type. Capture normalises away how big the opportunity was, so this reads as strategy fit rather than "volatile days pay more". | Built |
| DTY-2 | Which tags travel together | Graph | Windy days are often also low-price days, etc. | Built |
| DTY-3 | How common each type is | Graph | Frequency of each kind of day. | Built |
| DTY-4 | Mean state of charge by price character | Graph | Average state of charge through the day for each price tag — volatile, negative-price, peaky. Grouped by price character only: driver tags like *windy* are deliberately left out, because averaging them blurs distinct shapes. | Built |
| DTY-5 | Days behind the tags | Table | Every day in the window with its tags, £/MW/day, capture and cycles, newest first. | Built |

## Benchmark vs fleet — simulation against reality  ·  *Research*

*Data: the simulation and the real fleet over the days they share.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| SVF-1 | Include grid-services sites | Filter | Off by default — including them exaggerates the gap. | Built |
| SVF-2 | Simulation ceiling | Number | The best a perfect trader could have done. | Built |
| SVF-3 | Fleet wholesale avg | Number | The wholesale leg (PN × MID) only, MW-weighted across the comparison sites — the single leg the simulation also plays. Balancing revenue is deliberately outside it. | Built |
| SVF-4 | Realisation | Number | Real earnings as a share of the ceiling — the headline gap. | Built |
| SVF-5 | Sites compared | Number | How many real batteries are in the comparison. | Built |
| SVF-9 | Per-site vs the ceiling | Graph | Each site's £/MW/day split into the wholesale leg and the balancing leg, against the simulation ceiling drawn as a reference line. Only the wholesale leg is comparable — the sim does not play the balancing market. | Built |
| SVF-6 | Day by day | Graph | Simulation against fleet over time. | Built |
| SVF-7 | Trading shape | Graph | Do real batteries move at the same hours? Mean net output by hour, discharge positive. Absent on a window with no usable per-hour fleet shape. | Built |
| SVF-10 | Work rate vs earnings | Graph | Every site plotted by cycles per day against £/MW/day, with the benchmark starred — does trading harder actually pay? | Built |
| SVF-8 | Gap by day type | Graph | On which kinds of day does reality fall furthest short? Absent when no day in the window carries a tag. | Built |

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

## Keeping it current

Edit a row when you decide something; the build updates it when something ships. If it drifts
slightly it is still useful — this is a thinking document, not a build artifact.

It should not drift *silently*, though, so one command checks it:

```bash
python scripts/audit_kpi_sheet.py
```

It compares Numbers, Graphs, Tables and Downloads page by page. Filters and Notes are left out
on purpose: one Filter row often covers several widgets (the fleet's four site multiselects are
one control to a reader), and a Note has no single call to match.
