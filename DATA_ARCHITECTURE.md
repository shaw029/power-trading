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
curated 23-site cross-section, a rolling 60-day window, the two revenue streams it can
estimate consistently every day.

One code path serves both. The population and the window are parameters, so a metric is
written once and read at either depth. **A metric is never removed to make the dashboard
lighter** — the dashboard simply asks the same function for less.

The rule that keeps this honest: **the dashboard never claims the notebook's scope.** It
states its own coverage on the page (45.5% of GB BM-registered battery MW) and points at
the notebook for the rest, so a light tier never reads as a complete one.

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
- **The fleet was a sample presented as a fleet.** The registry's 23 sites are
  a deliberate cross-section, and it says so, but nothing measured how large a
  cross-section — so every fleet-level result rested on an unstated assumption
  about representativeness.

## What follows from it

### One implementation, two depths

The population is a parameter, carried by `fleet.population.Population`: a set of
sites, the BM Units they own, and the cache suffix their day-files are written
under. Two exist — `REGISTRY` (the curated 23 sites / 47 BM Units) and
`census_population()` (90 sites / 127 BM Units).

`REGISTRY` is the **default argument of every fetcher and every metric**, so the
dashboard gets it without asking and its behaviour is unchanged by construction.
The notebooks pass the census explicitly. No metric is duplicated, reimplemented
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
| `fleet/registry.py` | 23 curated sites, hand-verified — the default population | presentation — **unchanged** |
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

Over the July 2026 snapshot:

| Basis | Registry | Census | Coverage |
|---|---|---|---|
| Sites | 23 | 90 | 25.6% |
| **MW (declared export)** | **2,891** | **6,348** | **45.5%** |
| MWh (where known) | 5,179 | 6,391 | 81.0% ⚠ |

⚠ Duration is known for 23/23 registry sites but only 19/67 others, so the MWh
row is biased upward and is a ceiling, not an estimate.

The registry captures **45.5% of GB BM-registered operational battery MW**, and
the bias has a clear direction: coverage is 70% of 200 MW+ assets but 14% of
20–50 MW and 0% below 20 MW, and 54% of transmission-connected MW against 28%
of distribution-connected. Batteries traded behind aggregator, VLP or supplier
portfolios have no per-unit settlement data and sit outside this denominator
entirely.

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
| Sites / BM Units | 23 / 47 | 90 / 127 |
| One day of PN | 0.76 MB | 1.96 MB (2.6x) |
| Raw cache, full window | ~2 GB | ~5 GB |

For a notebook that runs once, offline, 2.6x is irrelevant. For a Streamlit
process rendering 60 days on every interaction it is the difference between a
154 MB working set and something around 400 MB, on a tier that allows roughly a
gigabyte. So the notebooks take the census and the dashboard keeps the registry —
and because the dashboard states its own coverage on the page, a reader is never
left thinking the light tier is the complete one.

### Metadata is not uniform across the census

The census is identified from Elexon reference data, so its *power* is as sound
as the registry's. Its other metadata is not, and the difference matters
per-metric rather than globally:

- **MW-normalised metrics** (£/MW/day, MW per MW online, availability factor)
  are valid across all 90 sites — declared export capability comes from Elexon.
- **MWh-normalised metrics** (cycles per day, inferred state of charge) are valid
  for the 42 sites whose duration is published through a Capacity Market
  agreement. The notebooks compute them over that subset and say so on the page.
  Assuming a duration would put a fabricated denominator under a headline number.
- **Optimiser and region** fall back to BM Unit lead party and GSP group, which
  are the trading party and (for transmission units) null respectively.

This is why `census_population()` returns `nan` rather than a default for unknown
energy capacity: `nan` propagates visibly and forces the subsetting to be
explicit, where a zero or a guess would silently corrupt a fleet average.
