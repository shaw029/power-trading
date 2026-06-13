# Quantitative Strategy Whitepaper: Day-Ahead Power Positioning

## 1. Executive Summary: Virtual Trading & Imbalance Proxying
This system models the behavior of a **Non-Physical Participant (Virtual Trader)** in the Great Britain (GB) wholesale power market. Lacking physical generation or demand, the strategy seeks to extract Alpha from structural grid forecasting inefficiencies (e.g., wind forecast errors vs. actual delivery).

**The Objective:** The strategy takes directional exposure in the **EPEX SPOT Day-Ahead (DA) auction** based on expected system imbalance, then manages exit through a two-slice hybrid engine:

1. **Passive slice** (`baseline_hedge_ratio`, default 50%) — always unwound at the Market Index Price (MID), the continuous intraday mid-market. This is the primary exit path and the one the whitepaper refers to as "intraday."
2. **Active slice** (`1 − baseline_hedge_ratio`) — exits at MID if a Take-Profit or Stop-Loss level is reached; if neither trigger fires, it settles at the system imbalance price (SSP for longs, SBP for shorts). Imbalance is the terminal fallback for this slice, not an accident of undeliverable volume.

*Crucial Market Distinction:* The strategy does *not* treat the Imbalance mechanism (SSP/SBP) as a primary liquidity venue for arbitrage. Instead, it uses machine learning to proxy expected system imbalance via forecast-driven residual load. **Mispricing is explicitly defined as the deviation between the model-implied fair value (derived from residual load and forecast dynamics) and the observed Day-Ahead auction price.** A DA position is taken when this mispricing is detected; the passive slice always exits at MID, and the active slice targets MID via TP/SL — with imbalance as its deliberate terminal settlement when the price target is not reached within the delivery window.

## 2. Market Regime & Data Justification (2018)
The current backtest engine is validated on 2018 market data (January–December).

* **Stable Baseline for Alpha Validation:** Developing a foundational algorithm during structural market breaks (e.g., the 2020 COVID demand crash or the 2022 European gas crisis) introduces extreme volatility that can generate false-positive returns. Isolating the development phase to a stable regime proves the ML feature engineering possesses a genuine statistical edge independent of macro black swans.
* **Data Fidelity (Pre-Brexit):** Post-Brexit (Jan 1, 2021), the UK decoupled from the EU Internal Energy Market (IEM), fracturing established data pipelines. Pre-decoupling data guarantees high-fidelity, contiguous inputs.
* **Regime Limitations (Intellectual Honesty):** It is explicitly noted that 2018 represents a relatively low-renewables penetration regime compared to the current grid. The model's robustness in modern, high-volatility, wind-dominated regimes (post-2021) remains an area for future out-of-sample stress testing and regime segmentation.

## 3. System Boundaries & Signal Logic
The pipeline implements a directional DA trading desk with strict institutional portfolio constraints:

* **Strict Leakage Prevention:** The DA auction closes at 11:00 AM on Day-1. The feature set relies entirely on the D-1 10:30 AM pre-auction forecast vintage. Latency and gate closure constraints are strictly observed. No same-day actuals are included; lagged data uses a strict 48-period (24-hour) offset.
* **Signal Definition & Volatility Gating:** A position is initiated *only* when the model predicts a forward price deviation exceeding a volatility-adjusted threshold, which is calibrated using historical imbalance spread distributions. This ensures exposure is taken only when conviction outweighs the expected cost of residual imbalance.
* **Long vs Short — Direction Rule:** The model predicts `spread = SSP − DA_price` for each half-hour settlement period. A **LONG** (buy DA, settle at SSP) fires when `predicted_spread > gate`; a **SHORT** (sell DA, settle at SBP) fires when `predicted_spread < −gate`. The gate is `clip(penalty_buffer, 0) + max(threshold, vol_multiplier × vol_threshold)`, where `penalty_buffer` is the rolling SBP−SSP spread cost, `threshold` is the configured minimum floor (default 5.0 £/MWh), and `vol_threshold` is a lagged rolling standard deviation of the imbalance spread. A long is the view that the grid will be short — SSP will exceed the DA clearing price. A short is the view that the grid will be long — SBP will be below DA, allowing a buy-back at a cheaper imbalance price.
* **Execution Constraints & Risk Budgeting (`signal.top_n`):** Signals are capped at the top-N highest-conviction periods per direction per day, controlled by the configurable `signal.top_n` parameter (default 5, calibrated via the tournament sweep in `notebooks/01_da_positioning_backtest.ipynb`). Within each direction, periods are ranked by `|predicted_spread|` and only the top-N are retained. This constraint approximates real-world liquidity and capital allocation limits, ensuring the strategy concentrates risk in the highest-confidence signals rather than diluting exposure across the full curve.
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

1. **Day-Ahead (LP Optimisation):** A linear program (PuLP/HiGHS) solves the optimal charge/discharge schedule against an ML-generated DA price *forecast*, maximising `Σ [(discharge_h − charge_h) × forecast_price_h − (discharge_h + charge_h) × degradation_cost_per_mwh] × resolution_h` subject to SOC, power, efficiency, and optional cycle-cap constraints. Degradation cost is included in the primal objective so the solver avoids unprofitable cycling — not applied only as a post-hoc deduction. Revenue is then settled against the *actual* cleared DA price, so forecast quality directly drives PnL. The schedule length adapts to the configured `resolution_h` (BESS config key; e.g. 48 half-hourly periods or 24 hourly). The LP respects a configurable **SOC operating window** (`min_soc_pct`–`max_soc_pct`, default 10–90%) to protect cell longevity; the usable capacity is therefore `(max_soc_pct − min_soc_pct) × capacity_mwh`. An optional `target_daily_cycles` cap limits total discharge energy per day (`Σ discharge_h × duration_h ≤ target_daily_cycles × capacity_mwh`). The end-of-day SOC is unconstrained — the LP ends wherever it is optimal — and the actual ending SOC is **carried forward** as the starting SOC for the next day's LP, so days are not treated independently.

2. **Intraday (Rules-Based Rebalancing — Ledger & Reserve):** During the delivery window, a rules engine adjusts the DA schedule in real time against Market Index Prices (MID). The engine is built on a *ledger-and-reserve* model: rather than tracking SOC drift against a single implied trajectory, it computes — for every period — exactly how much energy must be **reserved** to honour every remaining locked DA commitment, and how much spare energy or headroom is therefore free to monetise financially. The three rules below run in order per period `h`.

   - **Rule 1 — Physical Guardrails.** Before any trade, the engine derives two forward-looking bounds from the *remaining* locked DA schedule `da_schedule[h+1:]`. Both are accumulated by walking the future commitments and converting each one to its SOC impact through the asset's round-trip efficiencies:
     - **Required Reserve `R_h`** — the minimum SOC the pack must hold at the *end* of period `h` so that every future scheduled **discharge** can still be served without breaching `min_soc`. Starting from `min_soc_mwh`, each future discharge `d` adds the energy it will draw, `d × duration_h / discharge_efficiency`; each future charge `c` releases reserve, subtracting `|c| × duration_h × charge_efficiency` (floored at `min_soc_mwh`).
     - **Available Headroom `H_h`** — the maximum SOC the pack may hold at the end of period `h` so that every future scheduled **charge** can still be absorbed without breaching `max_soc`. Starting from `max_soc_mwh`, each future charge subtracts the energy it will store; each future discharge adds it back (capped at `max_soc_mwh`).

     All physical execution in the period is then clamped so the resulting SOC stays inside `[R_h, H_h]`. Any DA volume that cannot be delivered or absorbed inside this band settles at the imbalance price (SBP for an undelivered discharge — the BESS is short; SSP for an unabsorbed charge — the BESS is long).

   - **Rule 2 — Constrained Financial Netting.** The engine looks to capture the DA–MID spread *financially* — booking the trade at MID without physically cycling the battery, hence **zero degradation**. Only energy that is free of the Rule 1 guardrails is eligible: for a scheduled discharge the eligible volume is `min(mw, H_h − SOC)`; for a scheduled charge it is `min(|mw|, SOC − R_h)`. The benefit is bounded by a **bottleneck** in the forward DA curve: walking the implied SOC forward over `da_schedule[h+1:]`, `t_ceiling` is the first future period at which SOC would hit `max_soc` (for a discharge netting) and `t_floor` the first at which it would hit `min_soc` (for a charge netting). The future-DA window the netting is benchmarked against is therefore `da_price_actual[h+1 : t_ceiling]` (or `… : t_floor`) — only as far ahead as the pack can physically hold the position.
     - For a **discharge** period, the engine nets (a `financial_buyback`) when `mid_prices[h] ≤ max(window) − margin_buy`: MID is cheap enough today that buying the position back now and re-selling into the higher locked future DA price is accretive.
     - For a **charge** period, the engine nets (a `financial_sellback`) when `mid_prices[h] ≥ min(window) + margin_sell`: MID is rich enough today to sell the position forward against the cheaper locked future DA price.

     The netted MWh is settled at MID and carries a net-zero physical position; only the un-netted remainder is physically dispatched under Rule 1's clamp. Netted volume is reported as `cycles_saved_mwh` — throughput monetised without wear.

   - **Rule 3 — High-Conviction Alpha Override.** When MID is exceptionally rich, the engine will aggressively dump available discharge energy *now* even if doing so eats into the Required Reserve `R_h`. The resulting reserve deficit is a naked short on a future floor period, so it is covered by a **proxy forward hedge** rather than left to settle at imbalance. The hedge is priced off the bottleneck floor period `t_floor`:

     ```
     hedge_cost = da_price_actual[t_floor] + vol_multiplier × volatility[h]
     ```

     i.e. the locked future DA price at which the short must be re-covered, plus a volatility buffer (`vol_multiplier × volatility[h]`) to account for execution uncertainty. The override fires only when the net edge clears the conviction floor:

     ```
     mid_prices[h] − hedge_cost − degradation_cost > alpha_threshold
     ```

     On trigger, the dumped energy is sold at MID, the hedge cost is booked immediately, and the hedged energy is restored to the pack so downstream periods stay whole and incur **no** imbalance penalty for the deficit. The rule is skipped entirely when no `volatility_array` is supplied (`alpha_threshold` defaults to 5.0 £/MWh, `vol_multiplier` to 1.0).

   > **No lookahead bias.** The guardrail, bottleneck, and hedge calculations all benchmark against `da_price_actual[h+1:]` — the **locked future Day-Ahead prices**, which cleared at the D-1 11:00 auction and are fully known before the delivery window opens. They are *not* live intraday market prices. Using the already-settled DA curve to decide how much energy to reserve or net is information the trader genuinely holds at execution time, so the engine takes no forward-looking peek at unrealised prices.

3. **Imbalance Settlement (Ex-Post):** Any volume that could not be physically delivered or absorbed — because SOC hit a bound — is settled at the system imbalance price (SSP/SBP), appearing as a residual cost or credit.

### Asset Model (`BESSAsset`)

The `BESSAsset` dataclass tracks internal state across the trading day:

| Parameter | Description |
|---|---|
| `capacity_mwh` | Total energy storage capacity |
| `power_mw` | Maximum charge/discharge rate |
| `charge_efficiency` | Fraction of energy stored in the battery during charging |
| `discharge_efficiency` | Fraction of stored energy delivered to the grid during discharge |
| `degradation_cost_per_mwh` | £/MWh throughput cost representing battery wear, applied symmetrically to both charge and discharge volume |
| `initial_soc_pct` | Starting state-of-charge for the **first day** only; subsequent days inherit the actual end-of-day SOC from the previous day |
| `min_soc_pct` | Lower SOC operating bound (default 10%) — LP and intraday engine never discharge below this level |
| `max_soc_pct` | Upper SOC operating bound (default 90%) — LP and intraday engine never charge above this level |

The asset enforces physical feasibility: `charge()` and `discharge()` raise if power or SOC window limits are violated, and `can_charge()`/`can_discharge()` allow the intraday manager to test feasibility before acting. The effective usable capacity is `(max_soc_pct − min_soc_pct) × capacity_mwh`.

### PnL Decomposition

Net PnL for each day is decomposed into four components:

```
net_pnl = da_revenue + intraday_pnl + imbalance_pnl − degradation_cost
```

The `intraday_pnl` term itself splits into `financial_netting_pnl` (the zero-degradation MID-vs-DA capture from Rules 2 and 3) and `physical_dispatch_pnl` (the Rule 4 spread-improvement trades that actually cycle the pack). The intraday engine also reports `cycles_saved_mwh` — the throughput resolved financially without battery wear.

This decomposition lets the analyst attribute value to each settlement layer independently — see `notebooks/03_bess_dispatch_analysis.ipynb` for the full waterfall.

## 6. Validated Results

Performance numbers are run-specific and live with the experiment that produced them. See the equity curve, drawdown analysis, and sensitivity sweep in `notebooks/01_da_positioning_backtest.ipynb`; quantitative metrics are saved to `artifacts/{strategy}/{run_name}/{mode}/trading/metrics.json` after each run.

**Best-run selection criterion (Section 4 sweep):** configurations are ranked by **Calmar Ratio** (primary), then Sharpe Ratio, then Profit Factor, then Total Return, evaluated within the TC = £1.00/MWh execution cost tier with a minimum 500-trade liquidity floor. This priority reflects the quant PM view: drawdown-adjusted return (Calmar) is the headline risk metric; Sharpe and Profit Factor confirm consistency; raw return is the tiebreak only.