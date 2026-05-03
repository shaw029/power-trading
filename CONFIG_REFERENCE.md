# Configuration Quick Reference

## Data Sources

Configure via `.env` (preferred) or by editing defaults in `src/utils/config.py`.

```python
DEFAULT_DEMAND_FORECAST_SOURCE = "NESO_API"   # "ELEXON" | "NESO_API" | "CSV"
DEFAULT_WIND_FORECAST_SOURCE   = "ELEXON"     # "ELEXON" | "CSV"
DEFAULT_GENERATION_ACTUAL_SOURCE = "ELEXON"   # "ELEXON" | "CSV"
DEFAULT_DAY_AHEAD_PRICE_SOURCE = "ENTSOE"     # "ENTSOE" | "CSV"
DEFAULT_MARKET_INDEX_SOURCE    = "ELEXON"     # "ELEXON" | "CSV"
DEFAULT_DEMAND_ACTUAL_SOURCE   = "ELEXON"     # "ELEXON" | "CSV"
DEFAULT_IMBALANCE_PRICE_SOURCE = "ELEXON"     # "ELEXON" | "CSV"
```

Per-call override: `fetch_wind_forecast("CSV")` — ignores the config default.

## Using CSV Sources (offline / fast re-runs)

**Step 1** — generate CSVs once via API:

```python
fetch_wind_forecast("ELEXON").to_csv("data/raw/wind_forecast.csv", index=False)
fetch_generation_actual("ELEXON").to_csv("data/raw/generation_actual.csv", index=False)
fetch_day_ahead_price("ENTSOE").to_csv("data/raw/day_ahead_price.csv", index=False)
fetch_market_index_price("ELEXON").to_csv("data/raw/market_index_price.csv", index=False)
fetch_demand_actual("ELEXON").to_csv("data/raw/demand_actual.csv", index=False)
fetch_imbalance_price("ELEXON").to_csv("data/raw/imbalance_price.csv", index=False)
fetch_neso_ndfd().to_csv("data/raw/neso_ndfd.csv", index=False)
```

**Step 2** — set `"CSV"` in `.env` for all sources.

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

## NESO Demand Forecast Caching

`"NESO_API"` downloads day-by-day and caches raw JSON under `data/raw/NESO_NDFD/`. Subsequent runs skip already-cached days. To force a re-download:

```bash
rm -rf data/raw/NESO_NDFD/
```

## Date Range

All API fetches use `START_DATE` / `END_DATE` from `src/utils/config.py`. CSV sources load the file as-is — filter afterwards if needed.
