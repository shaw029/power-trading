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

## Pre-commit Hook

A git pre-commit hook lives in `scripts/pre-commit`. It runs the full check suite — flake8, mypy, and pytest — before every `git commit`, blocking the commit if anything fails. This closely mirrors the CI pipeline so failures are caught locally rather than on GitHub Actions.

Install it once after cloning:

```bash
make install-hooks
```

The hook is a plain shell script tracked in `scripts/`. Because `.git/hooks/` is never cloned, every contributor must run `make install-hooks` once on their own machine.

To bypass in an emergency (strongly discouraged — fix the issue instead):

```bash
git commit --no-verify
```

## Local Configuration (.env)

All local settings live in a `.env` file at the project root. It is gitignored — never committed.
`config.py` loads it automatically on startup; the values inside override the defaults in code.

Create the file and fill in your values:

```bash
# ENTSO-E key — register at https://transparency.entsoe.eu
#   → My Account Settings → Web API Security Token
ENTSOE_API_KEY=your_key_here

# Elexon BMRS and NESO CKAN are open — no key required.
# ELEXON_API_KEY=
```

Date ranges and data source selections are configured in `configs/config.yaml` under the `data:` block, not in `.env`. See **Experiment Configs** below.


## Experiment Configs

`configs/config.yaml` is gitignored — it holds your local experiment settings and is never committed. `configs/config.example.yaml` is the committed template; copy it to get started:

```bash
cp configs/config.example.yaml configs/config.yaml
```

Experiments are driven by YAML files in `configs/`. Pass one with `--config`:

```bash
python main.py --config configs/config.yaml
```

The config controls model hyperparameters, walk-forward settings, signal threshold, execution behaviour, and where all artifacts are written. Each config must declare a `strategy` and `run_name`; the pipeline writes everything to:

```
artifacts/{strategy}/{run_name}/features/               # features.parquet (shared)
artifacts/{strategy}/{run_name}/virtual/model/          # model.joblib, metadata.json
artifacts/{strategy}/{run_name}/virtual/trading/        # predictions.csv, signals.csv, pnl.csv, metrics.json
artifacts/{strategy}/{run_name}/bess/model/             # model.joblib, metadata.json
artifacts/{strategy}/{run_name}/bess/trading/           # pnl.csv, metrics.json
```

### Strategy Type

The top-level `strategy_type` key selects which pipeline branch to run:

```yaml
strategy_type: "virtual"   # "virtual" (default) | "bess"
```

- **`virtual`** — ML-driven DA positioning with hybrid intraday execution (Phases 1 & 2).
- **`bess`** — Physical battery dispatch: LP Day-Ahead scheduling, rules-based intraday rebalancing, and imbalance settlement (Phase 3).

### Signal Config

The `signal` block controls trade signal generation and cost assumptions:

```yaml
signal:
  threshold: 2.0         # minimum edge required to fire (£/MWh)
  top_n: 5               # max concurrent positions
  vol_multiplier: 1.0    # gate = max(threshold, vol_multiplier × rolling_vol)
  vol_window: 336        # rolling std lookback in half-hour periods (336 = 7 days)
  transaction_cost: 1.0  # cost applied per trade (£/MWh of position)
```

| Key | Type | Default | Description |
|---|---|---|---|
| `threshold` | float | 5.0 | Minimum predicted edge (£/MWh) required to open a position. `config.example.yaml` uses 2.0 — a calibrated starting value for 2018 data; the code default is 5.0. |
| `top_n` | int | 5 | Maximum number of concurrent positions |
| `vol_multiplier` | float | 1.0 | Multiplier applied to rolling volatility for dynamic gating |
| `vol_window` | int | 336 | Rolling standard-deviation lookback in half-hour periods |
| `transaction_cost` | float | 1.0 | Cost deducted per trade in £/MWh of position size |

### Execution Config (Virtual)

The `execution` block controls how DA positions are managed during the intraday window:

```yaml
execution:
  baseline_hedge_ratio: 0.5   # fraction of position hedged passively at MID (0.0–1.0)
  take_profit_pct: 0.90        # take-profit trigger as fraction of predicted spread
  stop_loss_price_delta: 5.00  # per-period stop-loss cap in £/MWh
  slippage: 0.50               # execution slippage cost in £/MWh
```

Execution archetype is controlled numerically by `baseline_hedge_ratio`: set `1.0` for a full passive hedge (all volume exits at MID), or `0.0` for imbalance-only settlement (Phase 1 behaviour). The default `0.5` runs the hybrid two-slice engine.

| Key | Description |
|---|---|
| `baseline_hedge_ratio` | Share of each position passively exited at the Market Index Price. Must be between 0 and 1 |
| `take_profit_pct` | Fraction of predicted spread at which the active slice locks in profit |
| `stop_loss_price_delta` | Maximum adverse price move (£/MWh) before the active slice is stopped out |

### BESS Config

The `bess` block defines battery asset parameters (used when `strategy_type: "bess"`):

```yaml
bess:
  capacity_mwh: 100.0              # total energy storage capacity (MWh)
  power_mw: 50.0                   # max charge/discharge rate (MW)
  charge_efficiency: 0.94          # fraction stored during charging
  discharge_efficiency: 0.94       # fraction delivered during discharge
  degradation_cost_per_mwh: 5.00   # £/MWh throughput cost for battery wear
  initial_soc_pct: 0.50            # first-day starting SOC; subsequent days carry over
  min_soc_pct: 0.10                # lower SOC operating bound (never discharge below)
  max_soc_pct: 0.90                # upper SOC operating bound (never charge above)
  resolution_h: 1.0                # dispatch interval in hours (1 = hourly)
  soc_drift_tolerance: 0.05        # max SOC drift before intraday rebalance (fraction of capacity)
  target_daily_cycles: 1.5         # max daily discharge energy as a multiple of capacity; null disables
  price_history_lookback_days: 7   # days of DA price history behind the naive forecast (dashboard)
```

| Key | Description |
|---|---|
| `capacity_mwh` | Total energy the battery can store |
| `power_mw` | Maximum instantaneous power for charge or discharge |
| `charge_efficiency` | Fraction of energy stored in the battery during charging (0.0–1.0) |
| `discharge_efficiency` | Fraction of stored energy delivered to the grid during discharge (0.0–1.0) |
| `degradation_cost_per_mwh` | Cost per MWh of throughput (charge + discharge), representing battery wear |
| `initial_soc_pct` | State of charge used on the **first backtest day only**; subsequent days start from the previous day's actual ending SOC |
| `min_soc_pct` | Lower SOC operating bound as a fraction of capacity. The LP and intraday engine will not discharge below this level |
| `max_soc_pct` | Upper SOC operating bound as a fraction of capacity. The LP and intraday engine will not charge above this level |
| `soc_drift_tolerance` | Maximum SOC deviation (fraction of capacity) from the DA-implied trajectory before the intraday rebalancing rule triggers |
| `target_daily_cycles` | Optional cap on daily discharge energy: `Σ discharge × duration ≤ target_daily_cycles × capacity_mwh`. Set to `null` to disable |
| `price_history_lookback_days` | Days of trailing DA prices averaged into the naive forecast used by the Streamlit dashboard (default 7) |

## Project Structure

```
power-trading/
├── configs/                        # YAML experiment configs
│   └── config.yaml     # gitignored — copy from config.example.yaml
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
├── artifacts/
│   └── {strategy}/{run_name}/
│       ├── features/
│       │   └── features.parquet    # Engineered features (shared between modes)
│       ├── virtual/
│       │   ├── model/
│       │   │   ├── model.joblib    # Spread-prediction XGBoost model
│       │   │   └── metadata.json
│       │   └── trading/
│       │       ├── predictions.csv # actual_spread, predicted_spread
│       │       ├── signals.csv     # auction_time, signal, direction
│       │       ├── pnl.csv         # Per-period net PnL (£)
│       │       └── metrics.json
│       └── bess/
│           ├── model/
│           │   ├── model.joblib    # DA price-prediction XGBoost model
│           │   └── metadata.json
│           └── trading/
│               ├── pnl.csv         # Daily BESS PnL decomposition
│               └── metrics.json
├── src/
│   ├── data/                       # download.py, preprocess.py
│   ├── evaluation/                 # splitter.py (walk-forward)
│   ├── features/                   # build_features.py
│   ├── models/                     # train.py, signal.py
│   ├── backtest/                   # engine.py
│   ├── bess/                       # BESS strategy modules
│   │   ├── bess_asset.py           # BESSAsset state-machine dataclass
│   │   ├── da_optimizer.py         # LP Day-Ahead schedule (PuLP/HiGHS)
│   │   └── intraday_manager.py     # Rules-based intraday rebalancing
│   └── utils/                      # config.py
├── tests/
├── app.py                          # Streamlit dashboard (make dashboard)
├── pipeline.py                     # End-to-end orchestrator
├── main.py                         # CLI entry point
└── requirements.txt
```

## VS Code

Select the `quantenv` interpreter via **Python: Select Interpreter** (`⌘⇧P`) after cloning.

Launch configs are pre-configured in `.vscode/launch.json` (`⌘⇧D` to open):
- **Download Only** — fetch and cache all raw API data without preprocessing or training.
- **Full Pipeline** — download data, build features, train model, run backtest
- **Features Only** — rebuild features from existing processed data, then stop. Use after changing data sources or feature engineering.
- **Virtual: Train & Backtest** — retrain model and run backtest on already-built features. Fastest for tuning hyperparameters or signal thresholds.
- **Static Analysis** — runs mypy + flake8 in parallel
- **Run All Tests** — pytest with verbose output
