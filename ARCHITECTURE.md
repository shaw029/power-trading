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

2. **Intraday (Rolling-Horizon Re-Optimisation — DA-Proxy MID):** The day-ahead schedule is locked at the 11:00 auction and its *financial* position cannot be changed, but during delivery the battery's *physical* dispatch can still deviate from the plan and settle the deviation in the continuous intraday market. A linear program re-optimises the physical schedule over the remaining horizon and books the deviation against the benchmark. The frozen DA schedule is what a trader is measured against; everything the re-optimisation adds on top is consolidated into a single **Intraday DA Improvement** bucket.

   - **Observed now, proxied for the future.** The intraday market is *continuous*, so the price each quarter-hour is trading at becomes **visible shortly before its delivery** — the current period's MID is *observed*, not guessed. Only the not-yet-visible **future** periods are uncertain, and those are priced from a **DA proxy**: the cleared DA price (known since the 11:00 auction) ± a configurable basis — extra discharge assumed to clear at `da − margin_sell`, extra charge at `da + margin_buy`. The basis is **conservatism on the proxy only**: it tempers netting the locked DA commitment or opening a new position on a still-*guessed* future price. The visible current period carries no such hurdle — its price is known.

   - **Rolling walk, execute only the visible period.** Because only the current period is tradeable (its price is visible), the engine walks the day period by period. At step `h` it re-solves an LP over the **remaining** horizon `[h:]` — the current period priced at the observed MID, every future period at the hurdled proxy — then **executes and locks only period `h`**, advances SOC and the cycle budget, and rolls to `h+1`, where one more real MID has appeared. The LP chooses the physical net dispatch `P_k` maximising the value of the deviations `dev_k = P_k − da_schedule_k`, net of execution friction and degradation:

     ```
     max Σ_{k≥h} [ dev⁺_k · sell_k − dev⁻_k · buy_k
                   − (dev⁺_k + dev⁻_k) · exec_cost
                   − (charge_k + discharge_k) · degradation_cost ] · duration_h
     ```

     where `sell_h = buy_h = mid_h` (observed, no hurdle) for the current period and `sell_k = da_k − margin_sell`, `buy_k = da_k + margin_buy` for future `k > h`. The locked DA revenue is a constant and drops out, so maximising deviation value is equivalent to maximising net PnL. Genuine new information — one more observed MID — arrives every step, so the re-solve actually adapts (unlike a static single solve). Phase 4 replaces the future-period DA proxy with a live, updating MID *forecast*, sharpening exactly the part the engine currently has to guess.

   - **Settlement and feasibility.** The executed deviation `dev_h` settles at the **observed MID** `mid_h`. It is clamped to what the battery can physically deliver from the current SOC, so the executed position is always feasible. A **cycle cap** bounds total discharge throughput at `target_daily_cycles × capacity_mwh`, decremented as the walk dispatches each period.

   - **Live-benchmark variant (perfect foresight).** The live GB BESS dashboard settles on *realised* data, so it opts into a single whole-day LP that prices every period at its **actual MID** (`run_intraday_session(..., perfect_foresight=True)`) rather than the DA proxy. Because following the DA plan is always feasible, that idealised optimum is bounded below by the benchmark — the intraday layer can only add value. The Phase-3 backtest above keeps the rolling, no-lookahead engine.

   > **No look-ahead bias.** The current period's MID is genuinely observable before its delivery in the continuous market, so reading it is not a peek; future periods are *not* read — they fall back to the DA proxy (prices the trader already holds from the 11:00 auction). The walk never prices a future period off unrealised intraday data, and each period is executed only once its own price is visible.

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

Net PnL for each day is reported as a **trader's-alpha ledger**: the frozen day-ahead schedule is the benchmark the desk is measured against, the re-optimisation's contribution is consolidated into a single improvement bucket, and execution friction is broken out separately.

```
net_pnl = benchmark_da_revenue + intraday_da_improvement − execution_costs_paid + imbalance_pnl − degradation_cost
```

- **`benchmark_da_revenue`** — the planned LP schedule settled at the *actual* cleared DA prices, frozen up front before any intraday action is taken. This is the benchmark.
- **`intraday_da_improvement`** — the cash the rolling re-optimisation adds on top of the benchmark: for each period, the value of its executed physical deviation `dev_h = P_h − da_schedule_h` **settled at that period's observed MID**, summed over the day and reported **gross** of execution friction.
- **`execution_costs_paid`** — slippage (`execution.slippage`, default 0.5 £/MWh) paid on every traded (deviated) MWh, isolated into its own bucket rather than netted into the improvement.
- **`imbalance_pnl`** — retained at ≈ 0. Each executed period is clamped to what the battery can physically deliver and any gap to the DA commitment is flattened at MID, so no volume spills to SSP/SBP in this phase; the bucket stays for continuity and the Phase-4 case where a forecast can leave a position unflattened at gate closure.
- **`degradation_cost`** — throughput wear on the physically cycled volume `Σ |P_h|`.

The buckets sum exactly to Net PnL. For continuity the engine also surfaces `da_revenue` (= `benchmark_da_revenue`), `intraday_pnl` (= `intraday_da_improvement`), `cycles_saved_mwh` (wear avoided by re-optimising away from the benchmark plan: benchmark throughput − actual throughput), and `accumulated_intraday_throughput_mwh` (the deviated MWh the re-optimisation traded).

This decomposition lets the analyst attribute value to each layer independently — see `notebooks/03_bess_dispatch_analysis.ipynb` for the full waterfall.

## 6. Validated Results

Performance numbers are run-specific and live with the experiment that produced them. See the equity curve, drawdown analysis, and sensitivity sweep in `notebooks/01_da_positioning_backtest.ipynb`; quantitative metrics are saved to `artifacts/{strategy}/{run_name}/{mode}/trading/metrics.json` after each run.

**Best-run selection criterion (Section 4 sweep):** configurations are ranked by **Calmar Ratio** (primary), then Sharpe Ratio, then Profit Factor, then Total Return, evaluated within the TC = £1.00/MWh execution cost tier with a minimum 500-trade liquidity floor. This priority reflects the quant PM view: drawdown-adjusted return (Calmar) is the headline risk metric; Sharpe and Profit Factor confirm consistency; raw return is the tiebreak only.