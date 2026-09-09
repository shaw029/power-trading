# Power Trading

An end-to-end quantitative trading framework for the GB wholesale electricity
market: day-ahead virtual positioning against imbalance, hybrid intraday
execution, and battery dispatch optimised by LP with rolling-horizon
re-optimisation — validated on a 2018 backtest and benchmarked live against the
real GB battery fleet.

**[Live GB BESS benchmark →](https://power-trading-live-gb-bess.streamlit.app)** — the battery engine running on this week's
GB market data.

![Virtual strategy](research/notebooks/assets/equity_curve.png)
![Battery dispatch in the DA market](research/notebooks/assets/bess_strategy_showcase.png)

---

## Layout

```
src/          strategy machinery — LP dispatch, ML models, features, backtest
fleet/        the GB battery fleet: who exists, what they did
live/         live GB feeds, classification, settlement
dashboard/    two Streamlit apps: backtest replay, live benchmark
research/     the study — notebooks 01-10, robustness checks, the A0 poster
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

**Virtual** — ML-proxied residual-load mispricing against the EPEX day-ahead
auction. Features pinned to the D-1 10:30 pre-auction vintage, with every lagged
series offset far enough (48 h) that its source period closed before the auction
the position was committed at — a property `build_features` asserts on the frame
it writes rather than claiming in prose. Walk-forward validation on sliding
200-day windows, with the **last 60 market days held out entirely** and never
shown to any selection step. Exposure capped at the top-5 highest-conviction
periods per direction per day. The selected configuration takes imbalance
settlement as its exit, with the TP/SL gate off — so there is no passive slice
to size, and hedge ratio and gate are one decision rather than two. Swept
separately inside the gate-on archetype, passive share trades P&L against
Sharpe rather than dominating: see notebook 02.

**BESS** — Day-ahead schedule solved by LP (PuLP/HiGHS) against an ML price
forecast, settling against the actual cleared price, so forecast quality drives
PnL. Degradation is priced into the objective, not deducted afterwards. SOC
carries across days. The intraday stage walks the day period by period: the
current settlement period is priced at its **observed** MID, the still-unseen
future at a hurdled DA proxy, and only the visible period is executed and locked
before rolling forward — so new information genuinely arrives at each step and
the day settles at ≈ 0 imbalance.

The **market-allocation lever** (`da_commit_fraction`) partitions both power and
the daily cycle budget between the auction and the intraday stage. Partitioning
energy as well as power is what makes the reservation real; notebook 03 sweeps
the frontier to find what the optimal constant split would have been.

### What the backtest actually shows

The only figure quoted as out-of-sample is the untouched 60-day holdout. Model,
signal and execution parameters are all chosen by reading the development folds,
so the development curve is an artefact of that search, not evidence.

| | Development (90 days, used for selection) | **Holdout (60 days, untouched)** |
|---|---:|---:|
| Executed trades | 456 | **329** |
| Net PnL | £50,101 | **£29,173** |
| 95% CI on net PnL | — | **£5 to £57,526** |
| Sharpe (daily % returns) | 7.48 | **5.40** |
| 95% CI on Sharpe | — | **0.56 to 10.83** |
| Max drawdown | — | **£12,236** |
| Traded volume / fees | — | 6,012 MWh / £6,012 |

Intervals are a percentile bootstrap over **market days** — 10,000 replicates,
seed 7 — computed by [`src/evaluation/holdout_report.py`](src/evaluation/holdout_report.py),
not by hand. The resampling unit matters: a market day is what the strategy
commits at, so resampling settlement periods would break the book and
understate the spread.

**Read the intervals, not the point estimates.** Sixty days is far too short to
pin anything: the bootstrap interval on net P&L runs from roughly **breakeven**
to £57,526, and on Sharpe from 0.56 to 10.83. A point estimate quoted without
that range would be the single most misleading number on this page. And a large part of
the result is not model skill at all — the mean cash-out-minus-auction spread in
this sample is −£2.04/MWh, so a control that simply shorts the same periods the
model selects earns £7,225 (Sharpe 1.72) on the same holdout. The model's claim
is the distance between those, on one 60-day window, in a single 2018 regime.

**Everything priced off MID is an idealised execution study.** The Market Index
Price is a volume-weighted average of completed trades, not a quote anyone can
hit, and one value per settlement period carries no path — so a stop is
triggered and filled off the same number. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

→ Commercial model, asset state machine and PnL decomposition in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#5-phase-3-physical-asset-bess-optimisation).

---

## Research

**Strategy — does it make money, and where does the money come from?**

| | | |
|---|---|---|
| **01** | DA positioning | Model shootout, walk-forward calibration on a development period with an explicit stability check, execution sweep under liquidity and risk constraints, and a single scoring of the frozen configuration on an untouched 60-day holdout |
| **02** | Hybrid execution | Hedge-ratio sweep across the full 0–1 range, endpoints included, on the development split only, ranked by one stated criterion. Net PnL falls monotonically with passive share while Sharpe peaks near 0.40 — a real trade-off rather than the flat band previously claimed, and a peak too small (+0.25 Sharpe on 90 days) to justify the £7k of P&L it costs |
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

> **Residual load was recomputed in September 2026.** ITSDO is already net of
> embedded solar, so the previous formula subtracted solar a second time. On the
> poster window that moved the top-decile threshold from 23,343.6 MW to
> 24,800.9 MW and replaced 81 of 288 top-decile half-hours. Figures derived from
> that classification have been regenerated; see each notebook's own metrics
> export for the current values.

All ten notebooks, the robustness checks behind them and the A0 board:
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

- [x] **Phase 1 — DA positioning engine.** Walk-forward validated XGBoost on residual-load mispricing, with signal gating, execution constraints and dynamic sizing.
- [x] **Phase 2 — Intraday execution.** Hybrid passive-MID / active-TP-SL engine with configurable hedge ratio and per-period stop-loss cap.
- [x] **Phase 3 — Physical asset optimisation.** LP day-ahead scheduling plus rolling-horizon intraday re-optimisation, SOC tracking, asymmetric efficiencies, priced degradation, and the market-allocation lever. Validated against the live GB benchmark and the real fleet.
- [ ] **Phase 4 — Stochastic optimisation and MID forecasting (planned).** Replace the constant `da_commit_fraction` with a two-stage scenario LP; replace the DA-price proxy for unseen periods with a genuine updating MID forecast; then reformulate the replan as a multi-stage stochastic programme, producing dispatch robust to forecast error rather than point-optimal against a single forecast.

---

## Data

- **[Nord Pool data portal](https://data.nordpoolgroup.com)** — GB (N2EX) day-ahead prices for the live benchmark (recent ~60 days, no key)
- **[ENTSO-E Transparency Platform](https://transparency.entsoe.eu)** — GB day-ahead prices for the historical backtest
- **[Elexon BMRS](https://bmrs.elexon.co.uk)** — physical notifications, balancing acceptances, declared limits, LoLP and de-rated margin
- **[NESO data portal](https://www.neso.energy/data-portal)** — Capacity Market notices and registers

Licensed under [MIT](LICENSE).
