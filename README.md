# Day-Ahead Power Trading

End-to-end quantitative trading system for the GB electricity market. Predicts the spread between imbalance settlement prices and the EPEX day-ahead auction price, then schedules the highest-conviction bids using only information available before the 11:00 AM auction close.

**2018 backtest (74-day test set):** +54% return · 3.96 Sharpe · 53.6% win rate

---

- Features are pinned to pre-auction vintages (D-1 10:30 cut-off);
- Signals are gated by a rolling imbalance cost estimate, then capped at top-5 per direction per day
- Position size scales with equity so drawdowns shrink exposure and gains compound

---

```bash
python main.py --config configs/config.yaml                          # full pipeline
python main.py --config configs/config.yaml --mode features          # features only
python main.py --config configs/config.yaml --mode model             # train & backtest
```

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — strategy design, signal logic, backtest mechanics
- [DATA_SOURCES.md](DATA_SOURCES.md) — data sources, CSV fallbacks, caching
- [DEVELOPMENT.md](DEVELOPMENT.md) — environment setup, static analysis, VS Code
