# Dashboard KPI sheet

What the live dashboard shows, page by page, in plain terms.

Use it to decide what to add or cut, hand it to a design pass, then hand it to a build.
Every row is either **Built** (on screen now) or an **Idea** (not yet). Types are
**Number**, **Graph**, **Table**, **Filter**, **Note**, **Download** — that's the distinction
design cares about.

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

## Day — one day in full

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
| DAY-14 | Half-hourly detail | Table | The underlying numbers, plus a CSV download. | Built |
| DAY-15 | Real batteries this day | Table | What actual GB sites earned. | Built |

## History — the whole window

*Data: the simulation across every day shown.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| HIS-1 | Average daily PnL | Number | Typical earnings per MW per day — the number every other page compares against. | Built |
| HIS-2 | Total PnL | Number | Everything made across the window. | Built |
| HIS-3 | Positive days | Number | How often it made money at all. | Built |
| HIS-4 | Best day | Number | The high-water mark, and when. | Built |
| HIS-5 | Daily earnings | Graph | Day by day, split by where the money came from. | Built |
| HIS-6 | When it trades | Graph | Charging and discharging by hour, against the average price. | Built |

## System overview — the GB grid itself

No simulation here, only observed data.
*Data: generation by fuel, demand, solar, wholesale prices.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| SYS-1 | Days shown | Number | How many days the filters left. | Built |
| SYS-2 | Average peak demand | Number | How high demand typically climbed. | Built |
| SYS-3 | Low-carbon share | Number | How much came from wind, solar, nuclear, hydro and biomass. | Built |
| SYS-4 | Net interconnectors | Number | Whether GB was importing or exporting overall. | Built |
| SYS-5 | Generation mix over time | Graph | What powered GB, day by day. | Built |
| SYS-6 | Low-carbon over time | Graph | Is the mix getting cleaner across the window? | Built |
| SYS-7 | Wholesale prices | Graph | Daily average price. | Built |

## Fleet performance — real GB batteries

Estimated from public data. Sites earning mainly from grid services look worse than they
are, so they're flagged rather than quietly mixed in.
*Data: real sites' declared output, market prices, balancing payments.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| FLT-1 | Site / operator / region / duration | Filter | Narrow to the batteries you care about. | Built |
| FLT-2 | Metric switch | Filter | View by revenue, volume, cycles or size. | Built |
| FLT-3 | Fleet tracked | Number | How much battery capacity is on screen. | Built |
| FLT-4 | Best vs typical site | Number | What operator skill and location were worth. | Built |
| FLT-5 | Fleet average | Number | Typical real-world earnings per MW per day. | Built |
| FLT-6 | Top site | Number | Who won the window. | Built |
| FLT-7 | Site league table | Graph | Ranked by the chosen metric. | Built |
| FLT-8 | Fleet over time | Graph | How the fleet did day by day. | Built |
| FLT-9 | Site detail | Table | Every site's numbers. | Built |

## Day types — what kind of day pays

*Data: day tags from the classifier, plus simulated earnings.*

| ID | Shows | Type | What it tells you | Status |
|---|---|---|---|---|
| DTY-1 | Earnings by day type | Graph | Which kinds of day actually pay. | Built |
| DTY-2 | Which tags travel together | Graph | Windy days are often also low-price days, etc. | Built |
| DTY-3 | How common each type is | Graph | Frequency of each kind of day. | Built |
| DTY-4 | Trading shape by type | Graph | Does it trade differently on a windy day? | Built |
| DTY-5 | Days behind the tags | Table | Which real dates sit in each group. | Built |
| DTY-6 | *(no headline number)* | — | This page has no Number at the top. Decide whether that's a gap. | Idea |

## Benchmark vs fleet — simulation against reality

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

## Alignment gap — does profit serve the grid?

The research page, and the busiest one: eight Numbers in two rows. Check crowding before
adding a ninth.
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

## Methodology

Plain-English explanation of every number above, plus a glossary. Nothing computed.

---

## Ideas — not built

From the three-winter study in `notebooks/05_stress_response_study.ipynb`. The numbers already
exist there; these rows are about whether they belong on screen.

| ID | Shows | Type | What it would tell you | Effort |
|---|---|---|---|---|
| ALN-15 | What the real fleet did under stress | Number | Real batteries discharge hard when the grid is tight — roughly twelve times their normal output. The strongest single finding in the study. | Small — data already flows |
| ALN-16 | Charging while the grid is tight | Graph | How often the fleet is *taking* power as margins thin. It falls to zero at the tightest, which is the reassuring answer. | Small — data already flows |
| ALN-17 | How much warning there was | Number | Nearly all risk periods were visible twelve hours ahead. | Medium |
| ALN-18 | Reserve built before stress | Graph | The fleet does *not* arrive fuller than usual, despite the warning. The most interesting finding, and the most arguable. | Larger — needs care, and its caveats shown |
| FLT-10 | Declared availability | Number | How much of the fleet was offered to the market at all. | Medium |
| DTY-6 | Headline number for Day types | Number | Fills the one page with no Number at the top. | Small |

---

## Keeping it current

Edit a row when you decide something; the build updates it when something ships. If it drifts
slightly it's still useful — this is a thinking document, not a build artifact, and it isn't
worth wrapping in process.
