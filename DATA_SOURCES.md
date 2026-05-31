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
  day_ahead_price_source: ENTSOE    # ENTSOE | CSV
  market_index_source:    ELEXON    # ELEXON | CSV
  demand_actual_source:   ELEXON    # ELEXON | CSV
  imbalance_source:       ELEXON    # ELEXON | CSV
```

`demand_source` is set per period because the available feeds differ across date ranges (NESO_API from mid-2017 onwards; ENTSOE for earlier periods). All other sources apply across all periods.

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

Once the CSVs exist, set `"CSV"` in `.env` for the relevant sources.

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
rm -rf data/raw/entsoe_day_ahead_price/  # day-ahead price (ENTSO-E)
```

The raw data directory defaults to `data/raw/`. Override via `.env` to point at a renamed folder:
```
RAW_DATA_DIR=data/raw_2018
```

## Date Range

All API fetches use the `start`/`end` dates defined in `config.yaml` under `data.periods`. CSV sources load the file as-is — filter afterwards if needed.
