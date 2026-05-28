# Day-Ahead Power Trading

End-to-end quantitative research framework for virtual and physical trading in the GB wholesale electricity market.

**Virtual Strategy** — ML-proxied residual load mispricing against the EPEX Day-Ahead auction, with hybrid intraday execution splitting volume between a passive MID hedge and an active TP/SL engine.

**BESS Strategy** — Battery Energy Storage System dispatch optimisation via LP-based Day-Ahead scheduling, rules-based intraday rebalancing, and ex-post imbalance settlement.

**2018 validated backtest (Virtual):** +285.8% return · 3.70 Sharpe · 53.6% win rate

![Equity Curve](notebooks/assets/equity_curve.png)

---

## Quick-Start

```bash
# 1. Create and activate the environment
conda create -n power-trading python=3.12 && conda activate power-trading

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API keys and experiment settings
cp .env.example .env
cp configs/config.example.yaml configs/config.yaml
# Edit .env with your ENTSO-E API key; edit config.yaml for dates, model params, etc.

# 4. Seed sample data
python bootstrap_data.py

# 5. Install the pre-commit hook (run once — blocks commits that break CI)
make install-hooks

# 6. Lint, type-check, and run tests
make check

# 7. Run the full pipeline
python -m src.pipeline
```

---

## How It Works

### Virtual Strategy

- Signal is derived from ML-proxied forecast error in residual load
- Features pinned to the D-1 10:30 pre-auction vintage
- Walk-forward validation on sliding 200-day windows adapts to seasonal regime shifts
- Position sizing scales with equity so drawdowns automatically reduce exposure
- Intraday execution splits volume between a passive MID hedge and an active TP/SL engine, reducing imbalance tail-risk

### BESS Strategy

- Day-Ahead schedule solved via linear programming (PuLP/HiGHS) to maximise charge/discharge revenue against an ML DA price forecast
- Intraday session applies three rules: execute DA dispatch, SOC drift rebalance against MID, and spread-improvement trades when MID beats DA + degradation cost
- Separate charge and discharge efficiencies model asymmetric conversion losses realistically
- DA schedule is optimised against an ML price forecast; revenue settles against actual cleared DA prices
- State-of-charge tracking and cycle degradation costs are enforced throughout

```bash
# Virtual strategy (default)
python main.py --config configs/config.yaml                   # full pipeline
python main.py --config configs/config.yaml --mode features   # features only
python main.py --config configs/config.yaml --mode model      # train & backtest

# BESS strategy — set strategy_type: "bess" in the config
python main.py --config configs/config.yaml
```

---

## Execution & Backtest Assumptions

| Assumption | Detail | Notebook |
|---|---|---|
| **DA pricing** | Day-Ahead positions are priced at the cleared DA auction price. The model takes directional exposure only when ML-predicted mispricing exceeds a volatility-adjusted threshold, and exposure is capped at the top 5 highest-conviction periods per direction per day. | `01_da_positioning_backtest.ipynb` |
| **Intraday exit (hybrid)** | Positions are unwound using a hybrid strategy: a configurable fraction is hedged passively at the Market Index Price (MID) when sufficient liquidity exists, with residual unhedged volume settled at the system Imbalance price (SSP/SBP). An active TP/SL engine can further reduce tail-risk on the unhedged slice. | `02_hybrid_execution_analysis.ipynb` |
| **BESS dispatch** | The Day-Ahead schedule is solved via LP optimisation (PuLP/HiGHS) against an ML price forecast, maximising charge/discharge revenue subject to SOC, power, and separate charge/discharge efficiency constraints. Revenue settles against the actual cleared DA price. During the intraday window a rules engine rebalances against MID: executing the DA schedule, correcting SOC drift, and capturing spread improvements when MID exceeds DA + degradation cost. Any undeliverable volume settles at the Imbalance price. | `03_bess_dispatch_analysis.ipynb` |

All notebooks live in `notebooks/`.

---

## Signal Logic & Feature Engineering

The pipeline implements a directional DA trading desk with strict institutional portfolio constraints:

- **Leakage prevention:** The DA auction closes at 11:00 AM on D-1. The feature set uses only the 10:30 AM pre-auction forecast vintage. No same-day actuals; lagged data uses a strict 48-period (24-hour) offset.
- **Signal gating:** A position is initiated only when predicted price deviation exceeds a volatility-adjusted threshold calibrated from historical imbalance spread distributions.
- **Top-5 cap:** Signals are capped at the top 5 highest-conviction periods per direction per day, approximating real-world liquidity and capital constraints.
- **Position horizon:** Each position is held over a single settlement interval (half-hourly).

### Features

All features are constructed from the D-1 10:30 pre-auction forecast vintage.

| Group | Features | Rationale |
|---|---|---|
| **Auction Fundamentals** | `auction_residual_load` | Demand forecast minus wind forecast — primary proxy for grid tightness |
| **Pre-Auction Drift** | `wind_auction_drift` | Wind forecast delta (10:30 vs. 07:00) — captures late-breaking supply uncertainty |
| **Historical Lags** | `day_ahead_price_lag48/96`, `system_sell_price_lag48/96` | 24h and 48h lookbacks on DA price and imbalance price; 48-period offset avoids leakage |
| **Temporal** | `hour_sin/cos`, `dow_sin/cos` | Cyclical encoding of settlement period and day-of-week in Europe/London time |

---

## BESS Asset Model

The `BESSAsset` dataclass tracks battery state across the trading day:

| Parameter | Description |
|---|---|
| `capacity_mwh` | Total energy storage capacity |
| `power_mw` | Maximum charge/discharge rate |
| `charge_efficiency` | Fraction of energy stored in the battery during charging |
| `discharge_efficiency` | Fraction of stored energy delivered to the grid during discharge |
| `degradation_cost_per_mwh` | £/MWh throughput cost representing battery wear |
| `initial_soc_pct` | Starting state-of-charge as a fraction of capacity |

PnL for each day decomposes into four components:

```
net_pnl = da_revenue + intraday_pnl + imbalance_pnl − degradation_cost
```

See `notebooks/03_bess_dispatch_analysis.ipynb` for the full waterfall.

---

## Configuration

### Strategy Type

```yaml
strategy_type: "virtual"   # "virtual" (default) | "bess"
```

### Execution Config (Virtual)

```yaml
execution:
  mode: hybrid                # hybrid | imbalance_only
  baseline_hedge_ratio: 0.5   # fraction hedged passively at MID (0.0–1.0)
  take_profit_pct: 0.08       # TP trigger as fraction of predicted spread
  stop_loss_price_delta: 15.0  # per-period stop-loss cap in £/MWh
```

### BESS Config

```yaml
bess:
  capacity_mwh: 100.0
  power_mw: 50.0
  charge_efficiency: 0.94
  discharge_efficiency: 0.94
  degradation_cost_per_mwh: 8.50
  initial_soc_pct: 0.50
```

### Artifact Layout

```
artifacts/{strategy}/{run_name}/
├── features/features.parquet          # shared between modes
├── virtual/
│   ├── model/model.joblib, metadata.json
│   └── trading/predictions.csv, signals.csv, pnl.csv, metrics.json
└── bess/
    ├── model/model.joblib, metadata.json
    └── trading/pnl.csv, metrics.json
```

---

## Environment Variables (.env)

All local settings live in `.env` (gitignored). Copy from `.env.example` and fill in your values.

```bash
ENTSOE_API_KEY=your_key_here       # register at https://transparency.entsoe.eu
START_DATE=2018-01-01
END_DATE=2019-01-01
```

Each data source can be switched to CSV for offline runs:

```bash
DEFAULT_DEMAND_FORECAST_SOURCE=NESO_API   # ELEXON | NESO_API | CSV
DEFAULT_WIND_FORECAST_SOURCE=ELEXON       # ELEXON | CSV
DEFAULT_GENERATION_ACTUAL_SOURCE=ELEXON   # ELEXON | CSV
DEFAULT_DAY_AHEAD_PRICE_SOURCE=ENTSOE     # ENTSOE | CSV
DEFAULT_MARKET_INDEX_SOURCE=ELEXON        # ELEXON | CSV
DEFAULT_DEMAND_ACTUAL_SOURCE=ELEXON       # ELEXON | CSV
DEFAULT_IMBALANCE_PRICE_SOURCE=ELEXON     # ELEXON | CSV
```

---

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
├── artifacts/
│   └── {strategy}/{run_name}/
│       ├── features/               # features.parquet
│       ├── model/                  # model.joblib, metadata.json
│       └── trading/                # predictions.csv, signals.csv, pnl.csv, metrics.json
├── notebooks/
│   ├── 01_da_positioning_backtest.ipynb
│   ├── 02_hybrid_execution_analysis.ipynb
│   └── 03_bess_dispatch_analysis.ipynb
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
├── pipeline.py                     # End-to-end orchestrator
├── main.py                         # CLI entry point
└── requirements.txt
```

---

## Research Notebooks

| Notebook | Contents |
|---|---|
| `01_da_positioning_backtest.ipynb` | Full tournament sweep: model shootout, hyperparameter calibration under walk-forward discipline, execution stress-testing with transaction costs, and a production tear sheet |
| `02_hybrid_execution_analysis.ipynb` | Compares four execution archetypes (pure imbalance, pure MID hedge, hybrid passive, hybrid active TP/SL) across return, risk, and tail-exposure metrics |
| `03_bess_dispatch_analysis.ipynb` | BESS dispatch deep-dive: DA price vs. MW dispatch overlay, state-of-charge tracking, rebalancing impact, and PnL waterfall decomposition |

---

## Docs

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Strategy design, market rationale, signal logic, and BESS commercial model |
| [DATA_SOURCES.md](DATA_SOURCES.md) | Seven datasets across three APIs, CSV fallbacks, and per-day caching |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Environment setup, VS Code launch configs, and project structure |

---

## Roadmap

- [x] **Phase 1 — DA Positioning Engine (complete):** End-to-end ML pipeline for virtual trading in the GB Day-Ahead market. Walk-forward validated XGBoost model predicting residual load mispricing, with signal gating, execution constraints, and dynamic position sizing.
- [x] **Phase 2 — Intraday Execution (complete):** Hybrid execution engine that splits DA positions between a passive Market Index Price (MID) hedge and an active Take-Profit/Stop-Loss engine. Configurable hedge ratio, TP/SL thresholds, and per-period stop-loss cap reduce tail-risk from full imbalance exposure.
- [x] **Phase 3 — Physical Asset Optimisation / BESS (complete):** Battery storage dispatch via LP Day-Ahead scheduling (PuLP/HiGHS), rules-based intraday rebalancing, and imbalance settlement. State-of-charge tracking, separate charge/discharge efficiencies, and cycle degradation costs enforced throughout.

---

## Acknowledgements

Data is sourced from three open platforms:

- **[ENTSO-E Transparency Platform](https://transparency.entsoe.eu)** — GB Day-Ahead auction prices
- **[Elexon BMRS](https://bmrs.elexon.co.uk)** — Wind forecasts, generation actuals, demand actuals, market index prices, and imbalance settlement prices
- **[NESO CKAN API](https://data.nationalgrideso.com)** — Demand forecasts

Built mainly with XGBoost, scikit-learn, pandas, PuLP, and NumPy.
