# Development Environment

This project uses a Conda environment for all development and testing.

## Setup

```bash
conda create -n quantenv python=3.12
conda activate quantenv
pip install -r requirements.txt
```

## Running Tests

```bash
pytest tests/
```

Or use the VS Code Test Explorer (flask icon in the sidebar) — pytest discovery is pre-configured in `.vscode/settings.json`.

## Static Analysis & Formatting

We use `flake8` for linting, `mypy` for static type checking, and `black` for code formatting. To install the required tools, run:

```bash
pip install flake8 mypy black
```

A `Makefile` is provided for convenience. You can run all checks at once or individually:

```bash
# Run formatting, linting, type checks, and tests
make check

# Or run them individually
make format
make lint
make typecheck
```

## Local Configuration (.env)

All local settings live in a `.env` file at the project root. It is gitignored — never committed.
`config.py` loads it automatically on startup; the values inside override the defaults in code.

Create the file and fill in your values:

```bash
# ── API Keys ───────────────────────────────────────────────────────────────
# ENTSO-E key — register at https://transparency.entsoe.eu
#   → My Account Settings → Web API Security Token
ENTSOE_API_KEY=your_key_here

# Elexon BMRS and NESO CKAN are open — no key required.
# ELEXON_API_KEY=

# ── Experiment settings ────────────────────────────────────────────────────
# Date range for all downloads
START_DATE=2018-01-01
END_DATE=2019-01-01

# ── Data sources ───────────────────────────────────────────────────────────
# Switch any source to "CSV" to load from a local file instead of the API.
DEFAULT_DEMAND_FORECAST_SOURCE=NESO_API   # ELEXON | NESO_API | CSV
DEFAULT_WIND_FORECAST_SOURCE=ELEXON       # ELEXON | CSV
DEFAULT_GENERATION_ACTUAL_SOURCE=ELEXON   # ELEXON | CSV
DEFAULT_DAY_AHEAD_PRICE_SOURCE=ENTSOE     # ENTSOE | CSV
DEFAULT_MARKET_INDEX_SOURCE=ELEXON        # ELEXON | CSV
DEFAULT_DEMAND_ACTUAL_SOURCE=ELEXON       # ELEXON | CSV
DEFAULT_IMBALANCE_PRICE_SOURCE=ELEXON     # ELEXON | CSV
```


## Experiment Configs

Experiments are driven by YAML files in `configs/`. Pass one with `--config`:

```bash
python main.py --config configs/config.yaml
```

The config controls model hyperparameters, walk-forward settings, signal threshold, and where all artifacts are written. Each config must declare a `strategy` and `run_name`; the pipeline writes everything to:

```
outputs/{strategy}/{run_name}/   # features.parquet, predictions.csv, signals.csv, pnl.csv, metrics.json
models/{strategy}/{run_name}/    # model.joblib, metadata.json
```

## Project Structure

```
power-trading/
├── configs/                        # YAML experiment configs
│   └── config.yaml
├── data/
│   ├── raw/                        # Per-day cached API responses
│   │   ├── B1770/                  # Imbalance prices (Elexon)
│   │   ├── FUELHH/                 # Generation mix (Elexon)
│   │   ├── WINDFOR/                # Wind forecast (Elexon)
│   │   ├── ITSDO/                  # Demand actual (Elexon)
│   │   ├── MID/                    # Market index price (Elexon)
│   │   ├── NESO_NDFD/              # Demand forecast (NESO)
│   │   └── entsoe_day_ahead_price/ # Day-ahead price (ENTSO-E)
│   └── processed/
│       └── processed_data.parquet  # All sources merged on a 30-min UTC grid
├── models/
│   └── {strategy}/{run_name}/      # model.joblib, metadata.json
├── outputs/
│   └── {strategy}/{run_name}/
│       ├── features.parquet        # Engineered features for this run
│       ├── predictions.csv         # actual_spread, predicted_spread
│       ├── signals.csv             # auction_time, signal, direction
│       ├── pnl.csv                 # Per-period net PnL (£)
│       └── metrics.json            # Model + trading performance
├── src/
│   ├── data/                       # download.py, preprocess.py
│   ├── evaluation/                 # splitter.py (walk-forward)
│   ├── features/                   # build_features.py
│   ├── models/                     # train.py, signal.py
│   ├── backtest/                   # engine.py
│   └── utils/                      # config.py
├── tests/
├── pipeline.py                     # End-to-end orchestrator
├── main.py                         # CLI entry point
└── requirements.txt
```

## VS Code

Select the `quantenv` interpreter via **Python: Select Interpreter** (`⌘⇧P`) after cloning.

Launch configs are pre-configured in `.vscode/launch.json` (`⌘⇧D` to open):
- **Run with Config** — full pipeline using `configs/config.yaml`
- **Run with Config (features only)** — download + preprocess + build features, then stop. Use after changing data sources or feature engineering.
- **Run with Config (model only)** — retrain and backtest on already-built features. Fastest for tuning hyperparameters or signal thresholds.
- **Static Analysis** — runs mypy + flake8 in parallel
- **Run All Tests** — pytest with verbose output
