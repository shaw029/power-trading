# Quantitative Strategy Whitepaper: Day-Ahead Power Positioning

## 1. Executive Summary: Virtual Trading & Imbalance Proxying
This system models the behavior of a **Non-Physical Participant (Virtual Trader)** in the Great Britain (GB) wholesale power market. Lacking physical generation or demand, the strategy seeks to extract Alpha from structural grid forecasting inefficiencies (e.g., wind forecast errors vs. actual delivery).

**The Objective:** The strategy takes directional exposure in the **EPEX SPOT Day-Ahead (DA) auction** based on expected system imbalance, then actively manages intraday risk by splitting volume between a passive Market Index Price (MID) hedge and an active Take-Profit/Stop-Loss engine rather than leaving 100 % exposed to Imbalance settlement.

*Crucial Market Distinction:* The strategy does *not* treat the Imbalance mechanism (SSP/SBP) as a primary liquidity venue for arbitrage. Instead, it uses machine learning to proxy expected system imbalance via forecast-driven residual load. **Mispricing is explicitly defined as the deviation between the model-implied fair value (derived from residual load and forecast dynamics) and the observed Day-Ahead auction price.** The strategy takes a DA position when this mispricing is detected, with the intended exit path being the continuous Intraday (ID) market, leaving only residual, unhedged exposure to the Imbalance settlement mechanism.

## 2. Market Regime & Data Justification (2018)
The current backtest engine is validated on 2018 market data (January–December).

* **Stable Baseline for Alpha Validation:** Developing a foundational algorithm during structural market breaks (e.g., the 2020 COVID demand crash or the 2022 European gas crisis) introduces extreme volatility that can generate false-positive returns. Isolating the development phase to a stable regime proves the ML feature engineering possesses a genuine statistical edge independent of macro black swans.
* **Data Fidelity (Pre-Brexit):** Post-Brexit (Jan 1, 2021), the UK decoupled from the EU Internal Energy Market (IEM), fracturing established data pipelines. Pre-decoupling data guarantees high-fidelity, contiguous inputs.
* **Regime Limitations (Intellectual Honesty):** It is explicitly noted that 2018 represents a relatively low-renewables penetration regime compared to the current grid. The model's robustness in modern, high-volatility, wind-dominated regimes (post-2021) remains an area for future out-of-sample stress testing and regime segmentation.

## 3. System Boundaries & Signal Logic
The pipeline implements a directional DA trading desk with strict institutional portfolio constraints:

* **Strict Leakage Prevention:** The DA auction closes at 11:00 AM on Day-1. The feature set relies entirely on the D-1 10:30 AM pre-auction forecast vintage. Latency and gate closure constraints are strictly observed. No same-day actuals are included; lagged data uses a strict 48-period (24-hour) offset.
* **Signal Definition & Volatility Gating:** A position is initiated *only* when the model predicts a forward price deviation exceeding a volatility-adjusted threshold, which is calibrated using historical imbalance spread distributions. This ensures exposure is taken only when conviction outweighs the expected cost of residual imbalance.
* **Execution Constraints & Risk Budgeting (Top-5):** Signals are capped at the Top 5 highest-conviction periods per direction per day. This constraint approximates real-world liquidity and capital allocation limits, ensuring the strategy concentrates risk in the highest-confidence signals rather than diluting exposure across the full curve.
* **Position Horizon:** Positions are held over a single settlement interval (half-hourly) unless rebalanced by updated signals, ensuring strict alignment with short-term forecast error resolution dynamics.

### Feature Engineering

All features are constructed from the D-1 10:30 pre-auction forecast vintage. No same-day actuals are used; lagged inputs apply a strict 48-period (24-hour) minimum offset.

| Group | Features | Rationale |
|---|---|---|
| **Auction Fundamentals** | `auction_residual_load` | Demand forecast minus wind forecast at the 10:30 vintage — the primary proxy for grid tightness and the core mispricing signal |
| **Pre-Auction Drift** | `wind_auction_drift` | Wind forecast at 10:30 minus wind forecast at 07:00 — captures how much the grid picture shifted in the hours before auction close, signalling late-breaking supply uncertainty |
| **Historical Lags** | `day_ahead_price_lag48`, `day_ahead_price_lag96`, `system_sell_price_lag48`, `system_sell_price_lag96`, `system_buy_price_lag48`, `system_buy_price_lag96`, `imbalance_spread_lag48`, `imbalance_spread_lag96` | 24 h and 48 h lookbacks on DA price, both imbalance settlement legs (SSP and SBP), and their spread (SBP − SSP). In GB's dual-price system tracking only SSP omits the buy-side cost signal; the spread is also the quantity the signal gate is calibrated against. The 48-period offset is the minimum lag that avoids forward leakage at 30-minute resolution. |
| **Temporal** | `hour_sin`, `hour_cos`, `dow_sin`, `dow_cos` | Cyclical sine/cosine encoding of settlement period (0.0–23.5 fractional hour) and day-of-week, computed in the Europe/London calendar to correctly handle BST transitions |

## 5. Phase 3: Physical Asset (BESS) Optimisation

Phase 3 extends the framework beyond virtual trading to physical asset dispatch. A Battery Energy Storage System (BESS) is modelled as a state machine with capacity, power, separate charge and discharge efficiencies, and cycle degradation constraints.

### Commercial Rationale

The BESS strategy decomposes the trading day into three settlement layers, each targeting a different liquidity venue:

1. **Day-Ahead (LP Optimisation):** A linear program (PuLP/HiGHS) solves the optimal charge/discharge schedule against an ML-generated DA price *forecast*, maximising `Σ (discharge_h − charge_h) × forecast_price_h` subject to SOC, power, and efficiency constraints. Revenue is then settled against the *actual* cleared DA price, so forecast quality directly drives PnL. The schedule length adapts to the configured `duration_h` (e.g. 48 half-hourly periods or 24 hourly).

2. **Intraday (Rules-Based Rebalancing):** During the delivery window, a rules engine adjusts the DA schedule in real time against Market Index Prices:
   - **Rule 1 — DA Dispatch Execution:** Execute the committed schedule; any shortfall from SOC constraints settles at the imbalance price.
   - **Rule 2 — SOC Drift Rebalance:** If actual SOC drifts more than 5% from the DA-implied trajectory, buy/sell at MID to realign.
   - **Rule 3 — Spread Improvement:** If spare capacity exists and MID exceeds DA + degradation cost (or the inverse for charging), take the incremental trade.

3. **Imbalance Settlement (Ex-Post):** Any volume that could not be physically delivered or absorbed — because SOC hit a bound — is settled at the system imbalance price (SSP/SBP), appearing as a residual cost or credit.

### Asset Model (`BESSAsset`)

The `BESSAsset` dataclass tracks internal state across the trading day:

| Parameter | Description |
|---|---|
| `capacity_mwh` | Total energy storage capacity |
| `power_mw` | Maximum charge/discharge rate |
| `charge_efficiency` | Fraction of energy stored in the battery during charging |
| `discharge_efficiency` | Fraction of stored energy delivered to the grid during discharge |
| `degradation_cost_per_mwh` | £/MWh throughput cost representing battery wear |
| `initial_soc_pct` | Starting state-of-charge as a fraction of capacity |

The asset enforces physical feasibility: `charge()` and `discharge()` raise if power or SOC limits are violated, and `can_charge()`/`can_discharge()` allow the intraday manager to test feasibility before acting.

### PnL Decomposition

Net PnL for each day is decomposed into four components:

```
net_pnl = da_revenue + intraday_pnl + imbalance_pnl − degradation_cost
```

This decomposition lets the analyst attribute value to each settlement layer independently — see `notebooks/03_bess_dispatch_analysis.ipynb` for the full waterfall.

## 6. Validated Results

Performance numbers are run-specific and live with the experiment that produced them. See the headline metrics in [README.md](README.md) and the full tear sheet — equity curve, drawdown analysis, and sensitivity sweep — in `notebooks/01_da_positioning_backtest.ipynb`.