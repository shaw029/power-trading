# Day-Ahead Power Trading

End-to-end quantitative trading system for the GB electricity market. Predicts the spread between imbalance settlement prices and the EPEX day-ahead auction price, then schedules the highest-conviction bids using only information available before the 11:00 AM auction close.

**2018 backtest (74-day test set):** +54% return · 3.96 Sharpe · 53.6% win rate

---

- Features are pinned to pre-auction vintages (D-1 10:30 cut-off); no same-day actuals leak in
- Signals are gated by a rolling imbalance cost estimate, then capped at top-5 per direction per day
- Position size scales with equity so drawdowns shrink exposure and gains compound

---

```bash
python main.py                 # full pipeline: download → features → train → backtest
python main.py --mode features # rebuild features from existing processed data
python main.py --mode model    # retrain on saved features (fastest)
```

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — strategy design, signal logic, backtest mechanics
- [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) — data sources, CSV fallbacks, caching
- [DEVELOPMENT.md](DEVELOPMENT.md) — environment setup, static analysis, VS Code
