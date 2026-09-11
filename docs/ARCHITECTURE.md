# Strategy architecture: GB power positioning and BESS dispatch

## 1. Day-ahead entry: forecast the settlement basis

The virtual research strategy takes a financial position in a half-hour delivery
contract at the day-ahead auction and settles the unclosed volume at imbalance.
It predicts `SSP − DA` using information assigned to the D−1 10:30 London decision
cutoff. A long earns `(SSP − DA) × MWh`; a short earns `(DA − SBP) × MWh`, before
costs. Cashout is the settlement mechanism for the residual position, not a quoted
execution venue. The framework does not model participant access or collateral.

Notebook 01 selects the model on development MAE and signal settings on development
account Sharpe within the specified cost tier. The current selected run is
`s4_n15_t30_vm00_tc10`: linear regression, up to 15 periods per direction per market
day, £3/MWh threshold, zero volatility multiplier and £1/entry-MWh fees. The fee
buffer is added to the threshold, so the effective entry hurdle is £4/MWh for this
cashout-only configuration. Top-N limits the schedule; it does not establish
market depth or independent risk across those periods.

A contract covers one half-hour of delivery. Its exposure starts at the preceding
day's auction and lasts until closure or settlement; its holding horizon is not
just the half-hour delivery duration. The selected signal is fixed at auction.

## 2. Execution: decide how much exposure to close

Three separate experiments use the same framework:

| Study | Quantity and exit | What it measures |
|---|---|---|
| Notebook 01 | Auction-equity sizing; selected cashout exit | Signal performance under the specified account rules |
| Notebook 02a | Fixed 1 MWh per signal; 0/25/50/75/100% intraday closure, TP/SL off | Cost and risk trade-off of the exit mix on matched observations |
| Notebook 02b | Account restarts and optional book stress budgets | Capital survival and path dependence |

For a hedge share `h`, the engine can close `h × MWh` at MID, adjusted for crossing
cost. Its remaining slice can use conditional TP/SL proxy exits or settle at SSP
for longs / SBP for shorts. Setting `h=0` alone does **not** disable TP/SL when MID
and forecast inputs are supplied. The generic API retains its legacy 15% hedge
and active-gate defaults; these are not selected production parameters. Use the
explicit example config for the canonical study.

Notebook 02a isolates pure static hedges. It charges £1 per entry MWh and £2 per
intraday MWh, uses one shared complete-price mask, and attributes hedge PnL as
`h × signed_MWh × (MID − cashout) − h × MWh × crossing_cost`. With fixed volume,
net PnL is linear in `h`; an interior hedge choice requires a risk preference or
constraint rather than a claim of higher absolute profit. Its 148 priced forecast
dates exclude two unpriced dates and the 12-day gap without forecasts. Partial
price days remain matched-observation subtotals, not complete-day estimates.

MID is an aggregate of completed trades, not a bid/offer quote or an intraday
path. A TP/SL threshold is tested against the single adjusted MID observation;
if triggered, the exit is that observation, which can be beyond the threshold.
A stop therefore does not cap the realised loss. Timestamped executable prices
are required to evaluate a deployable intraday decision rule.

## 3. Forecasts, timing and signal construction

Features use the pre-auction forecast vintage and lagged prices. The model input
contains auction residual load (demand forecast less wind forecast), the change
in wind forecasts between 07:00 and 10:30, 48/72-hour price and cashout-basis lags,
and cyclical London hour/day-of-week terms. Lag checks enforce availability
against each delivery row's auction decision time; label availability includes
settlement-period end plus the declared publication delay.

The directional gate is
`max(execution_buffer, 0) + max(threshold, vol_multiplier × vol_threshold)`.
The buffer reflects entry fees and, for an intraday exit configuration, crossing
cost. Volatility is measured on the lagged cashout-to-DA basis, not `SBP − SSP`.
Longs require predicted spread above the gate; shorts require it below the
negative gate. Within each direction, retain the top-N absolute forecasts.

The 2018 archive supplies training data and the saved July–December forecast
sample. It provides one historical regime, not proof of a stable edge. The final
60 market dates were excluded from the current selection but inspected in earlier
research, so they are retrospective evaluation. Revised historical observations
are not a point-in-time publication archive. Coverage gaps and uncertainty are
reported with the results; no period is removed merely because it loses money.

## 4. Account sizing and risk

The engine sizes a delivery book from equity observable at its auction, using a
fixed £50/MWh reference by default. The 2% reference-notional allocation per signal
is not 2% cash loss at risk. A common book cap can scale correlated entries together,
though at the published settings it never engages — see section 7;
settlement PnL is released after the delivery day ends plus the one-hour assumption.
The legacy `max_drawdown_pct` stops new books at a floor relative to initial capital,
while previously committed books still settle. It is not a trailing peak limit.

An optional book-risk policy reserves stress capacity for unsettled books and tests
smaller aggregate allocations; it is declared in `configs/execution_risk_study.yaml`
and driven by `scripts/run_execution_risk_study.py`. `scripts/run_start_date_study.py`
restarts empty accounts without rebasing an existing PnL path. Both are retrospective
implementation studies, and
[notebook 02b](../research/notebooks/02b_start_date_sensitivity.ipynb) runs and
documents them. Notebook 02a's fixed-volume ledger does not simulate this capital
process.

## 5. Phase 3: Physical Asset (BESS) Optimisation

Phase 3 extends the framework beyond virtual trading to physical asset dispatch. A Battery Energy Storage System (BESS) is modelled as a state machine with capacity, power, separate charge and discharge efficiencies, and cycle degradation constraints.

### Commercial Rationale

The BESS strategy decomposes the trading day into three settlement layers, each targeting a different liquidity venue:

1. **Day-Ahead (LP Optimisation):** A linear program (PuLP/HiGHS) solves the optimal charge/discharge schedule against an ML-generated DA price *forecast*, maximising `Σ [(discharge_h − charge_h) × forecast_price_h − (discharge_h + charge_h) × degradation_cost_per_mwh] × resolution_h` subject to SOC, power, efficiency, and optional cycle-cap constraints. Degradation cost is included in the primal objective so the solver avoids unprofitable cycling — not applied only as a post-hoc deduction. Revenue is then settled against the *actual* cleared DA price, so forecast quality directly drives PnL. The schedule length adapts to the configured `resolution_h` (BESS config key; e.g. 48 half-hourly periods or 24 hourly). The LP respects a configurable **SOC operating window** (`min_soc_pct`–`max_soc_pct`, default 10–90%) to protect cell longevity; the usable capacity is therefore `(max_soc_pct − min_soc_pct) × capacity_mwh`. An optional `target_daily_cycles` cap limits total discharge energy per day (`Σ discharge_h × duration_h ≤ target_daily_cycles × capacity_mwh`). The end-of-day SOC is unconstrained — the LP ends wherever it is optimal — and the actual ending SOC is **carried forward** as the starting SOC for the next day's LP, so days are not treated independently.

2. **Intraday (Rolling-Horizon Re-Optimisation — DA-Proxy MID):** The day-ahead schedule is locked at the 11:00 auction and its *financial* position cannot be changed, but during delivery the battery's *physical* dispatch can still deviate from the plan and settle the deviation in the continuous intraday market. A linear program re-optimises the physical schedule over the remaining horizon and books the deviation against the benchmark. The frozen DA schedule is what a trader is measured against; everything the re-optimisation adds on top is consolidated into a single **Intraday DA Improvement** bucket.

   - **Observed now, proxied for the future.** The intraday market is *continuous*, so the price for each configured delivery period is **represented in this simulation by its MID aggregate** — the current period's MID is *observed*, not guessed. Only the not-yet-visible **future** periods are uncertain, and those are priced from a **DA proxy**: the cleared DA price (known since the 11:00 auction) ± a configurable basis — extra discharge assumed to clear at `da − margin_sell`, extra charge at `da + margin_buy`. The basis is **conservatism on the proxy only**: it tempers netting the locked DA commitment or opening a new position on a still-*guessed* future price. The current-period proxy carries no such hurdle; its executable availability is not established by the historical MID archive.

   - **Rolling walk, execute only the visible period.** Under the simulation’s one-visible-period convention, the engine walks the day period by period. At step `h` it re-solves an LP over the **remaining** horizon `[h:]` — the current period priced at the observed MID, every future period at the hurdled proxy — then **executes and locks only period `h`**, advances SOC and the cycle budget, and rolls to `h+1`, where one more real MID has appeared. The LP chooses the physical net dispatch `P_k` maximising the value of the deviations `dev_k = P_k − da_schedule_k`, net of execution friction and degradation:

     ```
     max Σ_{k≥h} [ dev⁺_k · sell_k − dev⁻_k · buy_k
                   − (dev⁺_k + dev⁻_k) · exec_cost
                   − (charge_k + discharge_k) · degradation_cost ] · duration_h
     ```

     where `sell_h = buy_h = mid_h` (observed, no hurdle) for the current period and `sell_k = da_k − margin_sell`, `buy_k = da_k + margin_buy` for future `k > h`. The locked DA revenue is a constant and drops out, so maximising deviation value is equivalent to maximising net PnL. Genuine new information — one more observed MID — arrives every step, so the re-solve actually adapts (unlike a static single solve). Phase 4 replaces the future-period DA proxy with a live, updating MID *forecast*, sharpening exactly the part the engine currently has to guess.

   - **Settlement and feasibility.** The executed deviation `dev_h` settles at the **observed MID** `mid_h`. It is clamped to what the battery can physically deliver from the current SOC, so the executed position is always feasible. A **cycle cap** bounds total discharge throughput at `target_daily_cycles × capacity_mwh`, decremented as the walk dispatches each period.

   - **Live-benchmark variant (perfect foresight).** The live GB BESS dashboard settles on *realised* data, so it opts into a single whole-day LP that prices every period at its **actual MID** (`run_intraday_session(..., perfect_foresight=True)`) rather than the DA proxy. Because following the DA plan is always feasible, that idealised optimum is bounded below by the benchmark — the intraday layer can only add value. The Phase-3 backtest above keeps the rolling, no-lookahead engine.

   > **Execution proxy limitation.** MID is an aggregate of completed trades, not an executable pre-delivery quote. The rolling simulation reads the current period's MID and uses DA proxies for future periods. This avoids reading future MID periods, but remains an idealised execution study; it does not establish a fully point-in-time trading backtest.

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
- **`execution_costs_paid`** — slippage (`execution.slippage`, default 2.0 £/MWh — an illustrative crossing-cost assumption) paid on every traded (deviated) MWh, isolated into its own bucket rather than netted into the improvement.
- **`imbalance_pnl`** — retained at ≈ 0. Each executed period is clamped to what the battery can physically deliver and any gap to the DA commitment is flattened at MID, so no volume spills to SSP/SBP in this phase; the bucket stays for continuity and the Phase-4 case where a forecast can leave a position unflattened at gate closure.
- **`degradation_cost`** — throughput wear on the physically cycled volume `Σ |P_h|`.

The buckets sum exactly to Net PnL. For continuity the engine also surfaces `da_revenue` (= `benchmark_da_revenue`), `intraday_pnl` (= `intraday_da_improvement`), `cycles_saved_mwh` (wear avoided by re-optimising away from the benchmark plan: benchmark throughput − actual throughput), and `accumulated_intraday_throughput_mwh` (the deviated MWh the re-optimisation traded).

This decomposition lets the analyst attribute value to each layer independently — see `research/notebooks/03_bess_dispatch_analysis.ipynb` for the full waterfall.

## 6. Results and selection

Performance numbers are run-specific and live with the experiment that produced them. See the equity curve, drawdown analysis, and sensitivity sweep in `research/notebooks/01_da_positioning_backtest.ipynb`; quantitative metrics are saved to `artifacts/{strategy}/{run_name}/{mode}/trading/metrics.json` after each run.

**Best-run selection criterion:** choose the model family/hyperparameters on development MAE. Within the £1/MWh cost tier, require at least one executed trade per development market day; rank signal settings on development Sharpe, breaking ties on return-to-drawdown. Calmar is descriptive and uses annualised return divided by peak-relative drawdown. Candidate runs reserve the last 60 market days without predicting them (`evaluate_holdout=False`). Only the frozen configuration evaluates that tail. Because it was inspected in earlier research, it is a retrospective evaluation split, not a new untouched sample.

## 7. Timing, coverage and reproducibility

- Quantity uses a fixed pre-auction £50/MWh sizing reference by default, floored at £10 in the optional `sizing_prices` input. The book exposure cap uses that same reference; it is a reference-notional budget, not a guarantee on realised cleared notional. The sizing reference cancels out of the cap's comparison, which therefore reduces to a contract count: the cap binds only above `max_book_exposure_pct / risk_pct` contracts in one book, or 50 at the defaults, against a delivery day of at most 48 settlement periods. It is a backstop against a future sizing change and constrains none of the published runs; the per-signal allocation is what limits them. The funded-account book-risk policy in notebook 02b is the control that does bind.
- Each London delivery book is committed at D−1 10:30. Its PnL enters available auction equity only at the next London midnight plus a one-hour publication assumption, including empty days and date gaps. The halt is a loss floor against starting capital, not a trailing peak limit.
- Training labels and lag checks use settlement-period end plus a one-hour publication assumption. Historical revised prices are not a point-in-time publication archive, so this timing convention cannot prove vintage availability.
- Demand interpolation remains within eligible daily forecast vintages. Missing values remain missing in saved features. The virtual model drops incomplete feature rows; BESS fills missing inputs using medians fitted separately within each training fold and records `feature_imputed` on predictions.
- BESS research dispatch uses exact London market-day indices (23/24/25 hours) with two observed half-hours required per hourly price/forecast bin. Forecasts are joined by timestamp. Opening SOC is conditional on carried inventory; pre-auction uncertainty about that inventory is not simulated. The live policy benchmark instead uses explicitly labelled UTC days, always 24 hours, consistently with its existing charts and policy study.
- Research cache manifests hash code/configuration and the raw-file path/size/modification-time manifest; dependent runs additionally hash feature bytes. Changing an input revision must update its modification time. A missing or mismatched manifest rebuilds the cache. Data period ends are exclusive London boundaries.
- Recent raw Elexon, Nord Pool and fleet files expire after 15 minutes for a five-day provisional window. Older files are archived observations, not guaranteed final revisions. Substituted MID coverage is retained in settlement results and displayed in the live dashboard.
- Bootstrap intervals resample observed daily cash PnL and daily percentage returns (10,000 independent day draws, seed 7). They are conditional on the observed selected experiment: they do not rerun sizing, halts or parameter selection, and do not account for serial dependence. The always-short control uses model-selected periods, so it is a directional control, not a model-free scheduling baseline.
