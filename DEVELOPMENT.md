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
# Date range for all downloads and pipeline runs
START_DATE=2018-01-01
END_DATE=2019-01-01

# Increment to run a new experiment without overwriting previous results
# (pipeline writes to models/v2/, outputs/v2/, etc.)
CURRENT_VERSION=v1

# Minimum predicted edge above the penalty buffer before a signal fires (£/MWh)
DEFAULT_SIGNAL_THRESHOLD=5.0

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


## VS Code

Select the `quantenv` interpreter via **Python: Select Interpreter** (`⌘⇧P`) after cloning.

Launch configs are pre-configured in `.vscode/launch.json` (`⌘⇧D` to open):
- **Run Full Pipeline** — downloads data, preprocesses, builds features, trains, generates signals, runs backtest
- **Features Mode** (`--mode features`) — skips download; rebuilds features from already-processed data. Use after changing feature engineering.
- **Model Mode** (`--mode model`) — skips download and feature build; retrains and backtests on saved features. Fastest for tuning signal thresholds or model hyperparameters.
- **Static Analysis** — runs mypy + flake8 in parallel
- **Run All Tests** — pytest with verbose output
