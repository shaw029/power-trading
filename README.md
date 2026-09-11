# Power Trading

An end-to-end quantitative trading framework for the GB wholesale electricity
market: day-ahead virtual positioning against imbalance, hybrid intraday
execution, and battery dispatch optimised by LP with rolling-horizon
re-optimisation — studied on a 2018 backtest and benchmarked live against the
real GB battery fleet.

**[Live GB BESS benchmark →](https://power-trading-live-gb-bess.streamlit.app)** — the battery engine running on this week's
GB market data.

![Partial intraday hedges: cumulative net PnL and drawdown](research/notebooks/assets/equity_curve.png)

<!-- partial-hedge-summary:start -->
Five exit policies on the same 1,911 entries, 1 MWh each, through 2018-12-31 — fixed volume, so this is edge per unit traded, not an equity curve. Shaded gaps are missing coverage.

**Read the ordering as window-specific.** It comes from one period and one account inception. [Notebook 02a](research/notebooks/02a_hybrid_execution_analysis.ipynb) prices the profit/exposure/tail trade-off; [02b](research/notebooks/02b_start_date_sensitivity.ipynb) restarts the same signals from five monthly inceptions and the ranking moves — full imbalance wins four of five windows, October puts conditional TP/SL on top. At the original 2% sizing, a July start halts four of the five policies on the capital floor; under managed book risk none of them halt and full imbalance earns +8.8% instead of +485.9%. The sizing policy, not the exit policy, decides whether the account survives.
<!-- partial-hedge-summary:end -->

![Battery dispatch in the DA market](research/notebooks/assets/bess_strategy_showcase.png)

---

## Layout

```
src/          strategy machinery — LP dispatch, ML models, features, backtest
fleet/        the GB battery fleet: who exists, what they did
live/         live GB feeds, classification, settlement
dashboard/    two Streamlit apps: backtest replay, live benchmark
research/     the study — notebooks 01-10 (02 splits into 02a/02b), robustness, A0 poster
docs/         architecture, data sources, specs
scripts/      store builders and maintenance tooling
tests/        run in CI on every push
```

## Quick-start

There are two installs, and the research one is **not** `requirements.txt`.
That file is deliberately trimmed to what the Streamlit Cloud dashboard imports,
because adding the ML stack to it breaks the deploy.

```bash
conda create -n quantenv python=3.12 && conda activate quantenv

# Research / pipeline / notebooks / tests — a superset of the dashboard runtime.
pip install -r requirements-ml.txt

# Formatting, linting and type-checking (only needed for `make check`).
pip install black flake8 mypy pandas-stubs types-PyYAML types-requests

cp .env.example .env                          # add your ENTSO-E API key
cp configs/config.example.yaml configs/config.yaml

python bootstrap_data.py                      # seed 3 recent days from the live feeds
make install-hooks                            # pre-commit hook, blocks CI-breaking commits
make check                                    # format, lint, type-check, test
python main.py --config configs/config.yaml   # run the pipeline
```

To run only the live dashboard, `pip install -r requirements.txt` is enough.

**`bootstrap_data.py` seeds three recent days — it does not reproduce the study.**
The 2018 experiment needs a 200-day training window plus a 30-day fold and a
60-day holdout, so a full rebuild means backfilling the whole
`data.periods` range in the config (see `scripts/backfill_market_data.py`).

```bash
python main.py --config configs/config.yaml --mode bess   # battery strategy
python main.py --config configs/config.yaml --mode all    # both, sequentially
make dashboard                                            # backtest replay
streamlit run dashboard/live_app.py                       # live GB benchmark
make poster                                               # compile the A0 board
```

---

## The strategies

**Day-ahead positioning — trade the DA–cashout basis.** Forecast the settlement
spread before the auction: buy DA when expected cashout exceeds the auction
price by the entry hurdle, or sell DA when the reverse holds. The selected linear
model uses pre-auction demand/wind forecasts and lagged prices; walk-forward
selection caps the schedule at 15 periods per direction per day. The canonical
run carries the position to imbalance. PnL comes from the realised spread after
fees; forecast error, correlated delivery periods and cashout spikes are the
main risks. Notebook 01 tests the signal and its account-level implementation.

**Intraday execution — price the cost of reducing that exposure.** A partial
unwind replaces some uncertain cashout exposure with an intraday exit and its
crossing cost. Notebook 02a holds the entry signal and quantity fixed, comparing
0%, 25%, 50%, 75% and 100% closure. It measures profit retained, daily volatility,
tail loss and drawdown: less residual MWh need not mean a smaller realised loss.
The chart uses 1 MWh per entry across the full saved period. Funded-account sizing
and capital limits are assessed separately in the implementation studies.

**BESS — optimise the physical asset across DA and intraday.** A linear programme
chooses charge/discharge volumes against a DA price forecast, subject to power,
SOC, efficiency and cycle constraints, with degradation inside the objective.
The resulting DA commitment is settled at the cleared price. A rolling intraday
solve adjusts physical dispatch and trades the deviation from that commitment;
SOC and the remaining cycle budget carry forward. The `da_commit_fraction`
parameter reserves both power and cycling capacity for intraday. Notebook 03
attributes net PnL to the DA position, intraday deviations, execution costs,
imbalance and degradation, and tests the allocation trade-off.

The 2018 study uses a previously inspected retrospective evaluation split.
Intraday prices are represented by MID, an aggregate traded-price index rather
than an executable quote. Notebook 03 reveals one MID period at each step; the
live benchmark uses realised full-day prices with perfect foresight. Their
results answer different questions. Detailed assumptions and coverage are in
the notebooks and architecture documentation.

→ Commercial model, asset state machine and PnL decomposition in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#5-phase-3-physical-asset-bess-optimisation).

---

## Research

**Strategy — does it make money, and where does the money come from?**

| | | |
|---|---|---|
| **01** | DA positioning | Model shootout, walk-forward calibration on a development period with an explicit stability check, execution sweep under liquidity and risk constraints, and a single scoring of the frozen configuration on a reserved retrospective 60-day evaluation split |
| **02a** | Partial intraday hedging | Identical entries, five exit mixes: full-period net PnL, volatility and tail losses, hedge-cost attribution, monthly stability and a stress-day explanation |
| **02b** | Start-date sensitivity | The same five policies restarted from five monthly account inceptions. The ranking moves and, at 2% sizing, four of five breach the capital floor — so 02a's ordering is a property of its window, not a recommendation |
| **03** | BESS dispatch | PnL waterfall from DA benchmark through intraday improvement, execution friction, imbalance and degradation; price capture, rebalancing impact, and the DA/intraday capacity allocation frontier |

**The fleet study — the same machinery turned on a different question:** does
profit-optimal dispatch serve a system under stress, and what would closing the
gap cost? **04** poses it against a modelled battery, **05** takes it to the real
GB fleet on the operator's own scarcity instruments, **07** attacks 05's own trend
model, **09** concedes 04 and 05 were never comparable and rebuilds them onto one
ruler, and **10** corrects three earlier notebooks for the difference between a
notified plan and what the operator actually instructed.

The finding: energy prices already secure most of a modelled battery's
high-load alignment. Response during scarcity and readiness before scarcity
emerge as distinct dimensions of battery behaviour.

The notebooks, implementation appendices, robustness checks and A0 board:
**[research/](research/)**

---

## Dashboards

The pipeline reports aggregate PnL, which tells you how much the battery made
but not why it acted as it did. Two Streamlit apps close that gap.

**Backtest replay** (`dashboard/app.py`) faithfully replays the strategy the
pipeline runs and exposes the per-hour decision trail — why it charged or
discharged in each settlement period, how SOC evolved, where the forecast misled
it, where it hit limits. A model-debugging tool, not a trading interface.

**[Live GB benchmark](https://power-trading-live-gb-bess.streamlit.app)** (`dashboard/live_app.py`) runs the same engine on current
market data, settling three reference batteries (50 MW at 1h/2h/4h) against
actual day-ahead and intraday prices. Day-ahead from Nord Pool (N2EX), intraday
MID, generation and demand from Elexon — both public, **no API key**. Pages are
grouped by epistemic status: the simulated benchmark, the observed GB system, and
the research layer, plus a methodology page carrying scope and caveats.

→ Deploy steps and structure in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#dashboard).

---

## Docs

| | |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Strategy design, market rationale, signal logic, BESS commercial model |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | Seven datasets across three APIs, CSV fallbacks, per-day caching |
| [docs/DATA_ARCHITECTURE.md](docs/DATA_ARCHITECTURE.md) | The two tiers — notebooks as the full research instrument, the dashboard as a light presentation surface — and how the battery census is built |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Environment, config reference, project structure, dashboards, VS Code launch configs |
| [research/README.md](research/README.md) | The study: what each notebook asks, and why they are read in order |

---

## Roadmap

- [x] **Phase 1 — DA positioning engine.** Development-selected forecasting model on residual-load mispricing, with signal gating, execution constraints and dynamic sizing.
- [x] **Phase 2 — Intraday execution.** Configurable partial MID closure and conditional TP/SL proxy exits; matched-volume hedge research in notebook 02.
- [x] **Phase 3 — Physical asset optimisation.** LP day-ahead scheduling plus rolling-horizon intraday re-optimisation, SOC tracking, asymmetric efficiencies, priced degradation, and the market-allocation lever. Used in the live GB benchmark and compared with observed fleet behaviour.
- [ ] **Phase 4 — Stochastic optimisation and MID forecasting (planned).** Replace the constant `da_commit_fraction` with a two-stage scenario LP; replace the DA-price proxy for unseen periods with a genuine updating MID forecast; then reformulate the replan as a multi-stage stochastic programme, producing dispatch robust to forecast error rather than point-optimal against a single forecast.

---

## Data

- **[Nord Pool data portal](https://data.nordpoolgroup.com)** — GB (N2EX) day-ahead prices for the live benchmark (recent ~60 days, no key)
- **[ENTSO-E Transparency Platform](https://transparency.entsoe.eu)** — GB day-ahead prices for the historical backtest
- **[Elexon BMRS](https://bmrs.elexon.co.uk)** — physical notifications, balancing acceptances, declared limits, LoLP and de-rated margin
- **[NESO data portal](https://www.neso.energy/data-portal)** — Capacity Market notices and registers

Licensed under [MIT](LICENSE).
