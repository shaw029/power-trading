# Data Sources

Seven datasets are fetched from three APIs. Each source can be switched to a local CSV for offline runs or faster iteration.

## Source Configuration

Configured in `configs/config.yaml` under the `data:` block:

```yaml
data:
  periods:
    - start: "2018-01-01"
      end:   "2019-01-01"
      demand_source: NESO_API   # NESO_API | ENTSOE | CSV
  wind_source:            ELEXON    # ELEXON | CSV
  generation_source:      ELEXON    # ELEXON | CSV
  day_ahead_price_source: ENTSOE    # ENTSOE | NORDPOOL | CSV
  market_index_source:    ELEXON    # ELEXON | CSV
  demand_actual_source:   ELEXON    # ELEXON | CSV
  imbalance_source:       ELEXON    # ELEXON | CSV
```

`demand_source` is set per period because the available feeds differ across date ranges (NESO_API from mid-2017 onwards; ENTSOE for earlier periods). All other sources apply across all periods.

> **Day-ahead price — `ENTSOE` vs `NORDPOOL`:** `ENTSOE` reads the historical archive (the source for the backtest; GB coverage stopped post-Brexit, so it only serves cached/older dates). `NORDPOOL` reads GB (N2EX) day-ahead prices from the Nord Pool data portal — the source for the **live benchmark**: recent ~60 days, GBP, **no API key**. The live Streamlit dashboard (`dashboard/live_app.py`) uses `NORDPOOL` by default; the historical pipeline uses `ENTSOE`.

Per-call override (ignores config default): `fetch_wind_forecast("CSV")`

> **ENTSOE demand forecast note:** the A65 feed has no intraday revisions — all periods in a day share a single publish time stamped at D-1 10:30 Europe/London. Rolling features (`fc_rel_*`) will be flat within the day; only `fc_da_d1_1030` carries real signal with this source. Use `NESO_API` for full rolling feature resolution.

## Using CSV Sources (offline / fast re-runs)

**Quick start** — download all raw data in one go (or run `python bootstrap_data.py` for a 3-day sample):

```python
from src.data.download import (
    fetch_demand_forecast,
    fetch_wind_forecast,
    fetch_generation_actual,
    fetch_day_ahead_price,
    fetch_market_index_price,
    fetch_demand_actual,
    fetch_imbalance_price,
    fetch_neso_ndfd,
)

fetch_neso_ndfd().to_csv("data/raw/neso_ndfd.csv", index=False)
fetch_wind_forecast("ELEXON").to_csv("data/raw/wind_forecast.csv", index=False)
fetch_generation_actual("ELEXON").to_csv("data/raw/generation_actual.csv", index=False)
fetch_day_ahead_price("ENTSOE").to_csv("data/raw/day_ahead_price.csv", index=False)
fetch_market_index_price("ELEXON").to_csv("data/raw/market_index_price.csv", index=False)
fetch_demand_actual("ELEXON").to_csv("data/raw/demand_actual.csv", index=False)
fetch_imbalance_price("ELEXON").to_csv("data/raw/imbalance_price.csv", index=False)
```

Once the CSVs exist, change the relevant `*_source` keys in `configs/config.yaml` to `CSV`.

### Required CSV columns

| CSV file | Required columns |
|---|---|
| `neso_ndfd.csv` | `TARGETDATE`, `DELIVERYTIME`, `FORECASTDEMAND`, `PUBLISHTIME` |
| `wind_forecast.csv` | `startTime`, `publishTime`, `generation` |
| `generation_actual.csv` | `startTime`, `fuelType`, `generation` |
| `day_ahead_price.csv` | `time`, `value` |
| `market_index_price.csv` | `startTime`, `dataProvider`, `price` |
| `demand_actual.csv` | `startTime`, `demand` |
| `imbalance_price.csv` | `startTime`, `systemBuyPrice`, `systemSellPrice`, `netImbalanceVolume` |

## Caching

All API sources download day-by-day and cache raw JSON under `data/raw/<DATASET>/`. Subsequent runs skip already-cached days. To force a re-download, delete the relevant directory:

```bash
rm -rf data/raw/NESO_NDFD/               # demand forecast (NESO_API)
rm -rf data/raw/entsoe_demand_forecast/  # demand forecast (ENTSOE)
rm -rf data/raw/WINDFOR/                 # wind forecast (Elexon)
rm -rf data/raw/B1770/   # imbalance prices (SBP/SSP)
rm -rf data/raw/FUELHH/  # generation mix
rm -rf data/raw/ITSDO/                   # demand actual (Elexon)
rm -rf data/raw/MID/                     # market index price (Elexon)
rm -rf data/raw/entsoe_day_ahead_price/  # day-ahead price (ENTSO-E, historical)
rm -rf data/raw/NORDPOOL_DA/             # day-ahead price (Nord Pool N2EX, live GB)
rm -rf data/raw/PVLIVE_SOLAR/            # GB embedded solar outturn (PV_Live)
rm -rf data/raw/LOLPDRM/                 # LoLP / de-rated margin (Elexon, live GB)
rm -rf data/raw/CMN/                     # Capacity Market Notice register (NESO)
rm -rf data/raw/FLEET_PN/                # per-BMU Physical Notifications (fleet)
rm -rf data/raw/FLEET_MELS/              # per-BMU max export limits (fleet)
rm -rf data/raw/FLEET_MILS/              # per-BMU max import limits (fleet)
rm -rf data/raw/FLEET_BOALF/             # per-BMU accepted bid-offer levels (fleet)
```

> **What counts as renewable:** wind, solar, biomass and run-of-river hydro. **Pumped storage is not in the hydro band** — it is storage rather than a generation source, only as clean as whatever charged it, and net negative over any window (−13 GWh across a recent ten days), so it falls into `Other`. **Grid batteries are absent too, but not by choice:** Elexon's `FUELHH` has no battery fuel type, so a tracked fleet of ~2.7 GW is either invisible to the generation mix or buried inside `Other`. The mix chart therefore never shows storage discharge, and the renewable denominator does not include it.

> **Fleet physical delivery:** a Physical Notification is a *plan*; a Balancing Mechanism acceptance (`BOALF`) is the system operator instructing the unit to do something else. For GB batteries the correction is material — delivered throughput runs about 25% below notified over a recent week — so cycles, volume and capture spread are measured on PN overwritten by acceptances. Acceptances are often only minutes long, so the two are combined on a minute grid before averaging onto settlement periods; resolving them half-hourly would let a three-minute instruction rewrite a thirty-minute period. Revenue still prices the notified position at MID, with acceptances paid separately through `EBOCF` cashflows, so neither side double-counts.

> **Fleet declared-limit feeds:** `MELS` and `MILS` (per-BMU maximum export / import limits) are fetched by `fleet/fetch_fleet.py` alongside `PN`, for the stress-response study's availability metrics. Records carry *irregular* sub-period spans — a mid-period redeclaration cuts a settlement period into pieces and each carries a `notificationTime`/`notificationSequence` — so `fleet.performance.site_limit_profile` resolves them onto the half-hourly grid by painting a minute grid in notification order and time-weighting. A unit derated for 24 of 30 minutes reads as 80% available, which is the point.

> **Live-dashboard-only feeds:** two datasets are fetched only by the live benchmark (`dashboard/live_app.py`), not the historical pipeline. **LoLP / De-rated Margin** comes from Elexon's `forecast/system/loss-of-load` endpoint (keyless, not under `/datasets/`); the raw cache keeps every forecast-horizon print (12/8/4/2/1 h ahead) per settlement period, and `process_lolpdrm` reduces to the latest print (`lolp`, `drm_mw`). **Capacity Market Notices** come from the NESO GB CMN register (`gbcmn.nationalenergyso.com/api/notifications`); the `types[]` filter is mandatory (1 = issued, 4 = expiry/cancellation), and since the register is not day-partitioned the snapshot is cached under the *fetch* date (`CMN/CMN_<today>.json`) — at most one network hit per day.

## Asset registers (fleet census)

Five register sources answer a different question from the time-series feeds above: not *what
happened*, but *which assets exist*. They are not day-partitioned, so each is cached once per
**fetch** date under `data/raw/REGISTERS/` — at most one network round per source per day.

| Source | Endpoint | What it contributes |
|---|---|---|
| Elexon BMU reference | `/reference/bmunits/all` | The BM Unit universe: IDs, lead party, declared import/export capability, GSP group |
| NESO Capacity Market register | CKAN `25a5fa2e-…` | Explicit `Storage` technology **with duration** — the only free source of GB battery MWh |
| NESO TEC register | CKAN `17becbab-…` | Transmission-connected storage projects, connected MW, connection date |
| NESO Embedded register | CKAN `68b6f3a1-…` | The same for distribution-connected projects |
| NESO EAC results by unit | CKAN `a63ab354-…` | Explicit `Batteries` technology type per response/reserve participant |

> **Elexon publishes no battery fuel type.** 2,470 of 3,055 BM Units carry `fuelType: null` and
> not one row says "battery", so the population cannot be downloaded — `fleet/research/census.py`
> constructs it. A unit qualifies when it is physical (not a supplier portfolio or
> interconnector), carries no conflicting fuel label, and declares import and export capability
> **symmetrically**. Symmetry is the discriminating condition: all 47 BM Units of the curated
> registry fall in [0.96, 1.14], while a generator with a site load sits two orders of magnitude
> below (Derwent Cogeneration 0.01, Cleve Hill Solar 0.01, Kilgallioch wind 0.23). The Capacity
> Market, connection and auction sources grade *confidence*; they do not decide the verdict,
> because their name matching is too loose to carry a headline number.

## Ancillary service revenue (per unit)

Frequency response and reserve have historically been the dominant GB battery revenue stream,
so wholesale plus BM cashflow is a knowingly incomplete stack. `fleet/research/ancillary.py` adds the
third stream at unit level. It joins with no fuzzy matching: NESO names the winning unit by its
National Grid BM Unit name (`KILSB-5`, `CLAYB-1`), which is what `fleet.research.census` already keys on.

| Source | CKAN resource | Period | Services |
|---|---|---|---|
| DC, DR & DM Results By Unit | `ddc4afde-…` | 2021-09-16 → 2023-11-02 | Response (DC/DR/DM) |
| Balancing-Reserve Results By Unit | `5d8e47be-…` | 2024-03-12 → 2025-10-29 | Balancing Reserve |
| Response-Reserve Results By Unit (EAC) | `a63ab354-…` | 2026-03-31 → present | Response, Quick and Slow Reserve |

> **The history is fragmented and must be reported as such.** NESO replaced its auction platform
> twice, leaving real gaps (2023-12 → 2024-02 and 2025-11 → 2026-02 within the analysis window),
> and the eras cover *different services*. A month with no data is not a month of zero revenue,
> and two months that both have data are not comparable if their service sets differ — the
> 2024-03 → 2025-10 stretch carries only Balancing Reserve, so reading its £0.3m/month against
> the £7.8m/month of the DC era shows a collapse that is purely an artefact of publication.
> `coverage_by_month` and `comparable_windows` exist to refuse both mistakes; only rows sharing
> a `comparable_group` are like-for-like.

> **Half of the revenue is not earned by a site.** `classify_units` labels each winning unit as
> a census site, a VLP/supplier route (Elexon `bmUnitType` V or S), an aggregator house code, or
> unknown. Over the most recent full-stack window, £27.3m went to aggregator portfolios and only
> £13.7m (26%) to physical BM-registered sites. Those units are correctly *outside* the site
> census rather than missing from it, and attributing their earnings to a site would invent an
> asset. Block length is read from each record's own timestamps (4-hour EFA blocks under the old
> schema, 30 minutes under the auction platforms) rather than assumed.

## Populations: which batteries a fetch is for

Every per-BMU fetch takes a `fleet.population.Population`, defaulting to the curated
metadata table. The live dashboard passes `fleet.registry.REGISTRY` explicitly and fetches
its own day-files on demand, so a backfill is a research-tier concern:

```bash
# The curated list in fleet/registry.py — the default, and the metadata baseline
python scripts/backfill_market_data.py --start 2023-10-01

# Full BM-registered census — every battery the rule identifies; what the notebooks read
python scripts/backfill_market_data.py --population census --start 2023-10-01
python scripts/build_stress_store.py --population census --start 2023-10-01
```

A census run fetches **only the per-BMU feeds** (`FLEET_PN`, `FLEET_BOALF`,
`FLEET_EBOCF`, `FLEET_MELS`, `FLEET_MILS`). Prices, system state and forecasts are
market-wide and identical whichever fleet is studied, so they are never re-fetched.

> **Populations never share a cache.** A day-file holds exactly the BM Units it was
> fetched for, so the census writes `data/raw/FLEET_PN_CENSUS/` and the stress store
> writes `data/processed/stress_study_census/`. If they shared a directory, the dashboard
> would parse 2.6x the records it needs on every page load, and a coverage report could
> not tell whether a day had been fetched for 47 units or 127.

## Coverage and backfill

`src/data/coverage.py` reports, per feed per day, what the caches actually contain. Use it
before quoting any windowed statistic — an analysis window is only as trustworthy as its
thinnest feed:

```python
import datetime as dt
from src.data import coverage
coverage.coverage_summary(dt.date(2023, 10, 1), dt.date(2026, 8, 19))
```

`scripts/backfill_market_data.py` fills whatever that table says is missing. It fetches only
absent days, records a failing day rather than aborting, and prints coverage before and after:

```bash
python scripts/backfill_market_data.py --report-only          # what is missing
python scripts/backfill_market_data.py --start 2023-10-01     # fill it
python scripts/backfill_market_data.py --feeds MID,WINDFOR    # one or two feeds
```

> **`NORDPOOL_DA` cannot be backfilled.** The Nord Pool portal serves a rolling ~65-day window,
> so it is deliberately excluded from the default feed list — asking would log a thousand
> failures. For historical GB day-ahead-adjacent prices use `MID`, whose `N2EXMIDP` and
> `APXMIDP` data providers cover the full archive.

> **NDFD backfills as a range, not day by day.** The whole NESO demand-forecast resource is only
> tens of thousands of rows, so `download_neso_ndfd_range` fetches a month per call and fans the
> rows out into the same per-day cache files `download_neso_ndfd_daily` writes. Existing readers
> are unaffected.

The raw data directory defaults to `data/raw/`. Override via `.env` to point at a renamed folder:
```
RAW_DATA_DIR=data/raw_2018
```

## Date Range

All API fetches use the `start`/`end` dates defined in `config.yaml` under `data.periods`. CSV sources load the file as-is — filter afterwards if needed.
