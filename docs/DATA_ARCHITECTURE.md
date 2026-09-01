# Data Architecture: a research tier and a presentation tier

**Status:** accepted, August 2026.

## The decision

The project has two consumers with genuinely different jobs, and they are treated as
peers rather than as a system and its cut-down version.

**The notebooks are the research instrument.** They exist to establish what is true of
the GB battery fleet, so they are *complete by default*: the full asset census, the whole
window, every feed the public sources will give up, every revenue stream that can be
priced. Nothing is trimmed from a notebook for performance. If a fact is obtainable from
public data, the notebooks should have it.

**The live dashboard is the presentation surface.** It exists to show and communicate
what the market is doing now — the thing you put in front of someone. That job requires
it to load fast and stay within free hosting limits, so it runs deliberately light: a
smaller population — the BM-registered batteries with a known energy capacity that
cycle enough to be priced from wholesale and BM alone — a rolling 60-day window, the two revenue streams it can
estimate consistently every day.

One code path serves both. The population and the window are parameters, so a metric is
written once and read at either depth. **A metric is never removed to make the dashboard
lighter** — the dashboard simply asks the same function for less.

The rule that keeps this honest: **the dashboard never claims the notebook's scope.** It
states its own coverage on the page and points at the notebook for the rest, so a light
tier never reads as a complete one.

## Why this came up

The two consumers had drifted into needing genuinely different things, and the
data layer was quietly serving the smaller need to both.

The dashboard is a Streamlit app: it re-runs on every interaction, so its
budget is seconds, and it can only afford a rolling window over a hand-verified
list of assets. The notebooks are the opposite — they run once, offline, and
their entire value is being able to say something general about the GB fleet.
A number computed on 23 hand-picked sites over three months cannot support a
general claim no matter how carefully it is computed.

Because both read the same caches, the dashboard's needs had set the depth for
everyone. Over the 2023-10-01 → 2026-08-19 research window this left two
specific holes:

- **Market data was shallow where it mattered most.** Physical Notifications
  covered all 1,054 days, but the MID price they are valued against covered 93,
  BM cashflows 92 and acceptances 61. A capture spread averaged over that pair
  was silently averaged over the three months where both existed. Wind and
  demand forecasts did not cover the window at all.
- **The fleet was a sample presented as a fleet.** The registry's 23 sites were
  a deliberate cross-section, and it says so, but nothing measured how large a
  cross-section — so every fleet-level result rested on an unstated assumption
  about representativeness.

## What follows from it

### One implementation, two depths

The population is a parameter, carried by `fleet.population.Population`: a set of
sites, the BM Units they own, and the cache suffix their day-files are written
under. Three exist — `REGISTRY`, the hand-curated list in `fleet/registry.py`;
`REGISTRY`, the fleet this project analyses, generated from the census by
`scripts/build_registry.py`; and `census_population()`, every
BM-registered battery the census can identify. Each module states its own size;
none is quoted here, because the census is rebuilt from live registers and any
count written down in this document would go stale the next time it runs.

`REGISTRY` is the **default argument of every fetcher and every metric**, so a
caller that says nothing gets the hand-verified list. The dashboard passes
`REGISTRY` and the notebooks pass the census, both explicitly. No metric is duplicated, reimplemented
or removed, and a metric added for one tier is available to both.

**Caches are keyed by population, never merged.** A day-file holds exactly the BM
Units it was fetched for, so the census writes `FLEET_PN_CENSUS/` while the
curated fetch keeps `FLEET_PN/` untouched — and the same for the stress store
(`stress_study/` vs `stress_study_census/`). Merging them would make the
dashboard parse 2.7x the records it needs on every page, which is exactly the
failure the split exists to prevent.

`fleet/population.py` imports the census **lazily, inside the function**. It sits
on the dashboard's import chain, so a top-level `fleet.census` import would drag
the whole research tier into a Streamlit process; `tests/test_population.py`
parses the module and fails if that import ever moves to the top.

### The notebooks are never trimmed for the dashboard's sake

This is the direction the constraint runs, and it only runs one way. When the
two tiers want different things, the dashboard gives — by asking for a smaller
population or a shorter window — and the notebook keeps everything. A feed that
is too slow or too large for a Streamlit process is a reason to leave it out of
the dashboard, never a reason to leave it out of the research.

Ancillary revenue is the worked example. Its per-unit history is fragmented
across three NESO publishing eras with real gaps, which makes it unfit for a
live rolling view and *essential* to an honest revenue stack. So it lives in
`fleet/ancillary.py`, the notebooks price it in full, and the dashboard says
plainly that it is out of scope there and where to find it.

### Expensive multi-year work is pre-baked, never fetched on a page load

The dashboard fetches its rolling window live, day-file cached, because that is
what "live" means. But anything spanning years — the stress store, the census,
the ancillary archive — is assembled once by a script into parquet and read
back, so no page load ever waits on work a notebook could have done in advance.
Cached reads are scoped to the window requested rather than the history on
disk, so the dashboard's cost does not grow as its cache does.

### The boundary is a test, not a convention

`tests/test_profile_boundary.py` fails the build if `dashboard/` or `live/` import
`fleet.census`, `fleet.coverage`, `fleet.ancillary` or either store builder; if the
curated registry stops being 23 sites; if the dashboard's rolling window grows past 90
days; or if cached reads stop being scoped to the requested window. The dashboard's
weight is therefore a property the build checks, not a habit maintained by care.

This is also why the dashboard *states* its coverage figures as text rather than
computing them: importing the census to render one number would pull the whole
research tier into a Streamlit process.

### Coverage is a first-class output, not a footnote

`src/data/coverage.py` reports, per feed per day, what the caches actually
contain. Every analysis can state its denominator instead of averaging over
holes, and `scripts/backfill_market_data.py` prints the same table before and
after a run. An analysis that cannot state its coverage is not finished.

### Assets have a persistent identity

Sites change owner, name and BM Unit registration. Keying on any of those
splits one asset into two across a multi-year window. `fleet.census` assigns
`GB-BESS-<root>`, keyed on the National Grid BMU root, which is tied to the
physical connection point rather than the commercial arrangement around it.

## The layers

| Module | Role | Tier |
|---|---|---|
| `fleet/population.py` | The population parameter: sites, BM Units, cache suffix | both |
| `fleet/curated.py` | Hand-researched optimiser, region and MWh — a metadata table, not a fleet | presentation |
| `fleet/registry.py` | Census sites with a known MWh, generated — **the fleet, and what the dashboard renders** | presentation |
| `fleet/census.py` | Every BM-registered battery, reconstructed from five public sources | research |
| `fleet/coverage.py` | What share of the census the registry represents, and how it is biased | research |
| `fleet/ancillary.py` | Per-unit response/reserve revenue, joined to the census by `asset_id` | research |
| `src/data/coverage.py` | Per-feed per-day cache accounting | both |
| `scripts/backfill_market_data.py` | Fills the gaps the dashboard's window never needed | research |
| `fleet/performance.py` | Every existing metric, unchanged | both |

## Identifying a battery, since nobody publishes the list

Elexon labels no BM Unit as a battery — 2,470 of 3,055 units carry no fuel type
at all — so the population is constructed rather than downloaded. Four
necessary conditions, all read off Elexon's own reference data: the unit is
physical (not a supplier portfolio or interconnector), carries no conflicting
fuel label, declares both import and export capability, and declares them
**symmetrically**.

Symmetry is what makes the rule precise instead of merely plausible. A
battery's charge and discharge ratings are near-symmetric by construction: all
47 BM Units of the curated registry sit between 0.96 and 1.14. A generator with
a site load looks bidirectional but is nowhere near symmetric — Derwent
Cogeneration declares 0.01, Cleve Hill Solar 0.01, Thurrock Power 0.02, the
Kilgallioch wind BMU 0.23. The two populations separate with a wide gap and no
tuning: widening the accepted band from [0.90, 1.20] to [0.50, 2.00] moves the
result from 126 units to 133.

The Capacity Market register, connection registers and response-auction results
are recorded as **corroboration**, not identification — their name matching is
too loose to carry a headline number. They grade confidence, so a result can be
quoted for cross-referenced assets alone if a reviewer wants that.

## What the measurement says

**The library is live. Each notebook freezes itself.**

Two feeds behind the research tier move on their own: the five registers the census is
built from, and NESO's auction results. Unpinned, two runs on different days return a
different population *and* a different revenue stack, so every count below would disagree
with the next run.

`fleet.census.SNAPSHOT` exists to fix that, and **defaults to `None`, meaning live** —
nothing in the library or the dashboard pins anything. Each research notebook sets it in
its own setup cell, so the freeze is a property of a notebook rather than of the repo.
`fleet.ancillary` reads the same constant, so a notebook's population and the revenue
joined to it are always the same vintage.

Notebooks 04, 05 and 06 are aligned on one vintage and one window end, so their results
are directly comparable. **The date itself is in their setup cells and deliberately not
repeated here** — this document describes the framework, and a date copied into it is one
more place to forget to update.

**To move a notebook's analysis forward**, change the date in that notebook's setup cell and
re-run it. It is a pin, not a policy: the fleet is still growing and a held snapshot
understates it. If the population changes, regenerate `fleet/registry.py` — the dashboard's
list is derived from this census — and update any figure of that notebook's quoted in
`README.md`, `DATA_SOURCES.md`, `research/poster/poster.typ` or here. Moving the date without
the rest is what leaves the repo disagreeing with itself.

If a pinned date's cache is not on disk — `data/` is gitignored, so a fresh clone has none —
the read falls back to live and logs a warning naming the missing file, rather than writing
today's data under the pinned name.

The live dashboard is unaffected by any of this: it reads `fleet/registry.py`, a static
generated module, and never imports the census.

**The numbers live in `research/notebooks/06_fleet_coverage_census.ipynb`, not here.** It computes
coverage on three bases — site count, MW and MWh — for the population the dashboard renders
against the full census, characterises the residual bias by size band and connection level,
and prints the one sentence any dashboard figure should be quoted beside. Run it, or read its
stored outputs; both are computed on the vintage its setup cell pins.

What is stable enough to state here is the shape of the answer, which has not changed with
any snapshot:

- Coverage is **highest at the top of the fleet and falls away down it** — effectively
  complete for the largest transmission-connected sites, thinnest in the small
  distribution-connected tail.
- The cause is **published duration, not curation effort**. The dashboard renders the census
  sites whose energy capacity someone publishes, because its cycle and duration cells divide
  by MWh and a site without one renders blank. Closing the gap means researching MWh figures,
  not adding registry entries; notebook 06 ranks the outstanding sites by how much MW each
  would bring onto the page.
- The MWh basis reads 100% **by construction** — the dashboard's population *is* the
  known-MWh subset — so it is a share of the duration that is known, not of the duration that
  exists. Hand-researched figures live in `data/reference/battery_energy_capacity.xlsx`.
- Batteries traded behind aggregator, VLP or supplier portfolios have no per-unit settlement
  data and sit outside the denominator entirely, whatever the snapshot.

This is lower than a comfortable answer would have been, and it is the number
the analysis has to be defended with. It is also directly actionable: the 47
"not curated" sites above the registry's own size floor are the shortlist for
closing the gap.

## The revenue stack tells the same story from the other side

Adding per-unit ancillary revenue (`fleet/ancillary.py`) was meant only to complete the
earnings picture, but it independently corroborates the coverage finding. Over the most recent
window carrying the full service stack, £52.9m of battery ancillary revenue splits:

| What the winning unit actually is | £m | Share |
|---|---|---|
| Aggregator portfolio | 27.3 | 51.6% |
| **Census site** | **13.7** | **25.9%** |
| VLP / supplier route | 8.8 | 16.7% |
| Unknown | 3.1 | 5.8% |

Only about a quarter of the revenue lands on a physical BM-registered site. That is the asset
census reached from the opposite direction: the part of the GB battery fleet that can be
analysed *per site* is a minority of the whole, and the aggregator tier — invisible to every
per-unit feed this project can reach — is where much of the activity and earnings sit. It is
also why the aggregator units are classified rather than dropped: the honest statement is that
they exist and are large, not that they are absent.

## What the census population costs, and why only the notebooks pay it

Expanding the population is not free, which is the whole reason it is a parameter
rather than a new default:

| | Curated registry | Census |
|---|---|---|
| BM Units | the hand-verified list | roughly 2.6x as many |
| One day of PN | 0.76 MB | 1.96 MB (2.6x) |
| Raw cache, full window | ~2 GB | ~5 GB |

For a notebook that runs once, offline, 2.6x is irrelevant. For a Streamlit
process rendering 60 days on every interaction it is the difference between a
154 MB working set and something around 400 MB, on a tier that allows roughly a
gigabyte. So the notebooks take the census and the dashboard takes the smaller generated
population —
and because the dashboard states its own coverage on the page, a reader is never
left thinking the light tier is the complete one.

### Physical capacity beats contracted capacity, where both exist

Energy capacity arrives from three places and they are not measuring the same
thing. The curated registry's figures were checked against the site. An operator
publishes a physical nameplate. The Capacity Market states a duration band the
operator *chose to bid into*, against a MW figure it *chose to register*.

Both Capacity Market choices push the same way. Its MW averages 86% of Elexon's
declared capability and is sometimes half of it — Brentwood and Berkeley each
register 49.9 MW against 104 MW declared. Its duration comes in bands of 1.0,
1.5 and 2.0 hours, and bidding a longer band means a firmer delivery obligation
under stress, so there is a standing reason to bid short. Across the census,
Capacity Market sites imply a median 1.32 hours where hand-verified and
operator-published sites both imply about 2.

The cost is measurable. Lakeside's agreement gives 149.85 MWh against the
operator's published 200, and over 702 days of dispatch that overstates its
cycling by a third — from 0.74 to 0.99 cycles per day, either side of a 0.3
threshold that decides whether a site's inferred state of charge is used at all.

So precedence is registry, then operator, then Capacity Market, because every
metric the project computes from energy capacity — cycles, state of charge,
MWh coverage — is asking what the battery can physically hold. The Capacity
Market figure is a proxy used because it is available, not because it is right
for that question; it would be the correct figure for capacity-market revenue,
which is not priced here because the clearing prices are not published by NESO.

Leaving it alone was not the neutral option. It preserved an understatement of
known direction and known size on nineteen sites.

### Only cross-referenced assets enter the analysis population

`census_sites()` defaults to the `registry` and `corroborated` grades and drops
`signature_only` — units that pass the physical test with no independent source
agreeing. All three such units turned out to be false positives: ENRON MANX (the
Isle of Man interconnector — symmetric by construction, as any interconnector
is), a hydro station's demand unit, and a gas site.

The confidence grade existed from the start; making it the default took a longer
window to justify. Across 2023-26 the three sites were 1.8% of census MW and
changed nothing. Extended to 2018, when only seven census sites existed, the
interconnector's constant 22 MW import dominated the fleet's net position and
produced quarters where the fleet appeared never to discharge into scarcity at
all. A sample small enough to be moved by one wrong member is a sample where
"corroborated by an independent source" has to be a requirement, not a label.

### Metadata is not uniform across the census

The census is identified from Elexon reference data, so its *power* is as sound
as the registry's. Its other metadata is not, and the difference matters
per-metric rather than globally:

- **MW-normalised metrics** (£/MW/day, MW per MW online, availability factor)
  are valid across every census site — declared export capability comes from Elexon.
- **MWh-normalised metrics** (cycles per day, inferred state of charge) are valid
  only for sites whose duration is known — registry, operator disclosure, or
  a Capacity Market agreement. The notebooks compute them over that subset and
  say so on the page.
  Assuming a duration would put a fabricated denominator under a headline number.
- **Optimiser and region** fall back to BM Unit lead party and GSP group, which
  are the trading party and (for transmission units) null respectively.

This is why `census_population()` returns `nan` rather than a default for unknown
energy capacity: `nan` propagates visibly and forces the subsetting to be
explicit, where a zero or a guess would silently corrupt a fleet average.
