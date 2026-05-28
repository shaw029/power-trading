# Data Sources

Seven datasets are fetched from three APIs. Each source can be switched to a local CSV for offline runs or faster iteration.

## Source Configuration

Set in `.env` (or override per-call — see below):

```python
DEFAULT_DEMAND_FORECAST_SOURCE = "NESO_API"   # "NESO_API" | "ENTSOE" | "CSV"
DEFAULT_WIND_FORECAST_SOURCE   = "ELEXON"     # "ELEXON" | "CSV"
DEFAULT_GENERATION_ACTUAL_SOURCE = "ELEXON"   # "ELEXON" | "CSV"
DEFAULT_DAY_AHEAD_PRICE_SOURCE = "ENTSOE"     # "ENTSOE" | "CSV"
DEFAULT_MARKET_INDEX_SOURCE    = "ELEXON"     # "ELEXON" | "CSV"
DEFAULT_DEMAND_ACTUAL_SOURCE   = "ELEXON"     # "ELEXON" | "CSV"
DEFAULT_IMBALANCE_PRICE_SOURCE = "ELEXON"     # "ELEXON" | "CSV"
```

Per-call override (ignores the `.env` default): `fetch_wind_forecast("CSV")`

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
rm -rf data/raw/B1770/                   # generation actual (Elexon)
rm -rf data/raw/FUELHH/                  # generation by fuel type (Elexon)
rm -rf data/raw/ITSDO/                   # demand actual (Elexon)
rm -rf data/raw/MID/                     # market index price (Elexon)
rm -rf data/raw/entsoe_day_ahead_price/  # day-ahead price (ENTSO-E)
```

The raw data directory defaults to `data/raw/`. Override via `.env` to point at a renamed folder:
```
RAW_DATA_DIR=data/raw_2018
```

## Date Range

All API fetches use `START_DATE` / `END_DATE` from `.env`. CSV sources load the file as-is — filter afterwards if needed.
