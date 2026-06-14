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

2. **Intraday (Opportunity-Cost Engine — Two-Step Spread Capture):** During the delivery window a dynamic engine walks each period `h` sequentially and improves on the locked DA schedule, bounded by forward-looking physical guardrails derived solely from the *remaining* cleared DA schedule (`da_schedule[h+1:]`) and its already-settled prices — never from live, unrealised market data. The frozen DA schedule is the benchmark a trader is measured against; everything the engine adds on top is consolidated into a single **Intraday DA Improvement** bucket. The process has two steps per period.

   - **Step 1 — Physical Envelope.** Before any discretionary trade, the engine derives two SOC bounds from the remaining locked DA commitments, converting each one to its SOC impact through the asset's round-trip efficiencies:
     - **Required Reserve `R_h`** — the minimum SOC the pack must hold at the *end* of period `h` so that every future scheduled **discharge** can still be served without breaching `min_soc`. Computed as `min_soc_mwh + Σ future_discharge_mwh / discharge_efficiency`, capped at `max_soc_mwh`.
     - **Available Headroom `H_h`** — the maximum SOC the pack may hold so that every future scheduled **charge** can still be absorbed without breaching `max_soc`. Computed as `max_soc_mwh − Σ future_charge_mwh × charge_efficiency`, floored at `min_soc_mwh`.

     The Step-2 *physical* arbitrage is clamped to keep SOC inside `[R_h, H_h]`, so honouring future DA commitments is never starved. A live **cycle cap** enforces the throughput budget: once accumulated intraday throughput reaches `target_daily_cycles × capacity_mwh`, the envelope collapses to the current SOC (`R_h = H_h = SOC`) and no further intraday movement is allowed.

     > The base DA leg itself is **not** clamped to `[R_h, H_h]` — it is bounded only by the absolute SOC limits, so the day-ahead plan is always dispatched first and the envelope governs only the discretionary Step-2 arbitrage. Any DA volume that still cannot be delivered or absorbed (SOC hits an absolute bound) settles at the imbalance price — SBP for an undelivered discharge (BESS is short), SSP for an unabsorbed charge (BESS is long).

   - **Step 2 — Intraday DA Improvement.** With the envelope fixed, the engine improves on the period's DA position in two complementary ways:
     - **Financial netting (zero-wear spread capture).** When the current MID beats the period's *own* locked DA price by more than the configured margin plus the execution buffer — `mid ≤ da − margin_buy − exec_cost` for a scheduled discharge, or `mid ≥ da + margin_sell + exec_cost` for a scheduled charge — the engine nets the position *financially*: it books the offsetting trade at MID and keeps the DA credit, leaving a net-zero physical position. The battery never cycles, so the leg incurs **zero degradation**. The netted MWh is reported as `cycles_saved_mwh`; only the un-netted remainder is physically dispatched. These trades carry `trade_type = "financial_netting"`.
     - **Opportunity-cost arbitrage (physical).** Using the power left after the DA leg, the engine trades physically at MID whenever it beats the best price reachable in the *remaining* DA curve, net of degradation: discharge when `mid > max(future_da) + degradation_cost + exec_cost`, charge when `mid < min(future_da) − degradation_cost − exec_cost`. Degradation *widens* a no-trade deadzone around the reachable DA reference — a standalone intraday cycle is only taken when MID beats the price it forgoes by more than the wear it costs. On the final period no future DA position exists, so the reference falls back to the current DA price (still ± degradation plus the execution buffer). These trades are clamped to the `[R_h, H_h]` envelope, never reverse a scheduled leg, and accumulate against the cycle cap. They carry `trade_type = "opportunity_arb"`.

   > **No look-ahead bias.** Both the envelope and the opportunity-cost hurdles benchmark against `da_price_actual[h+1:]` — the **locked future Day-Ahead prices** that cleared at the D-1 11:00 auction and are fully known before the delivery window opens. They are *not* live intraday market prices, so the engine takes no forward-looking peek at unrealised data; using the already-settled DA curve to size reserves and hurdles is information the trader genuinely holds at execution time.

3. **Imbalance Settlement (Ex-Post):** Any volume that could not be physically delivered or absorbed — because SOC hit an absolute bound — is settled at the system imbalance price (SSP/SBP), appearing as a residual cost or credit.

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

Net PnL for each day is reported as a **trader's-alpha ledger**: the frozen day-ahead schedule is the benchmark the desk is measured against, the Step-2 engine's contribution is consolidated into a single improvement bucket, and execution friction is broken out separately.

```
net_pnl = benchmark_da_revenue + intraday_da_improvement − execution_costs_paid + imbalance_pnl − degradation_cost
```

- **`benchmark_da_revenue`** — the planned LP schedule settled at the *actual* cleared DA prices, frozen up front before any intraday action is taken. This is the benchmark.
- **`intraday_da_improvement`** — the cash the Step-2 engine adds on top of the benchmark: the financial-netting leg plus the opportunity-cost physical leg, reported **gross** of execution friction.
- **`execution_costs_paid`** — slippage (`execution.slippage`, default 0.5 £/MWh) paid on every traded MWh — both the netting and the physical legs — isolated into its own bucket rather than netted into the improvement.
- **`imbalance_pnl`** — SSP/SBP settlement of any DA volume that could not be physically delivered or absorbed.
- **`degradation_cost`** — throughput wear on the physically cycled volume.

The buckets sum exactly to Net PnL. For continuity the engine also surfaces the legacy split — `da_revenue` (`da_revenue_delivered` + `da_revenue_netted`), `intraday_pnl` (`financial_netting_pnl` + `physical_dispatch_pnl`), `cycles_saved_mwh` (throughput resolved financially without wear), and `accumulated_intraday_throughput_mwh` (physically cycled intraday MWh, governed by the cycle cap).

This decomposition lets the analyst attribute value to each layer independently — see `notebooks/03_bess_dispatch_analysis.ipynb` for the full waterfall.

## 6. Validated Results

Performance numbers are run-specific and live with the experiment that produced them. See the equity curve, drawdown analysis, and sensitivity sweep in `notebooks/01_da_positioning_backtest.ipynb`; quantitative metrics are saved to `artifacts/{strategy}/{run_name}/{mode}/trading/metrics.json` after each run.

**Best-run selection criterion (Section 4 sweep):** configurations are ranked by **Calmar Ratio** (primary), then Sharpe Ratio, then Profit Factor, then Total Return, evaluated within the TC = £1.00/MWh execution cost tier with a minimum 500-trade liquidity floor. This priority reflects the quant PM view: drawdown-adjusted return (Calmar) is the headline risk metric; Sharpe and Profit Factor confirm consistency; raw return is the tiebreak only.