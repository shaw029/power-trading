# Day-Ahead Power Positioning

End-to-end quantitative research framework for virtual trading in the GB wholesale electricity market. The system uses machine learning to proxy residual load mispricing against the EPEX Day-Ahead auction price, then schedules high-conviction bids using only pre-auction information.

**2018 validated backtest:** +285.8% return · 3.70 Sharpe · 53.6% win rate · net of £0.50/MWh transaction costs

![Equity Curve](notebooks/assets/equity_curve.png)

---

- Signal is derived from ML-proxied forecast error in residual load — not naive spread arbitrage
- Features pinned to the D-1 10:30 pre-auction vintage; no same-day data, no lookahead
- Walk-forward validation on sliding 200-day windows adapts to seasonal regime shifts
- Position sizing scales with equity so drawdowns automatically reduce exposure

---

```bash
python main.py --config configs/config.yaml                   # full pipeline
python main.py --config configs/config.yaml --mode features   # features only
python main.py --config configs/config.yaml --mode model      # train & backtest
```

## Docs

| | |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Strategy design, market rationale, signal logic, performance, and development roadmap |
| [DATA_SOURCES.md](DATA_SOURCES.md) | Seven datasets across three APIs, CSV fallbacks, and per-day caching |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Environment setup, project structure, and VS Code launch configs |

## Research Notebook

`notebooks/01_da_positioning_backtest.ipynb` — Full tournament sweep: model shootout, hyperparameter calibration under walk-forward discipline, execution stress-testing with transaction costs, and a production tear sheet.

## Roadmap

The current system is a validated foundational layer. Two extensions are planned:

**Phase 2 — Intraday Execution:** Replace the DA-to-imbalance settlement assumption with realistic continuous ID market exits. Ingest order book snapshots and MIP data to simulate scaling out of DA positions before gate closure, subjecting the strategy to real bid/ask slippage.

**Phase 3 — Physical Asset Optimisation (BESS):** Extend the engine to support battery storage dispatch. Introduce state-of-charge tracking, cycle degradation costs, and MWh capacity constraints to optimise charge/discharge schedules against the DA and ID price curves.
