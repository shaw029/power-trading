# Research

Two things: the analysis, and the board that presents it.

```
research/
├── notebooks/    01 to 10, in dependency order
│   ├── robustness/   scripts that check what the notebooks claim
│   ├── figexport.py  print-resolution figure export, imported by 04-10
│   └── build_digest.py
└── poster/       the A0 board — layout source, tracked inputs, build script
```

The framework lives at the repo root (`src/`, `fleet/`, `live/`). Everything here
uses it; the dependency runs one way only, so no framework module and nothing the
dashboard serves imports from this directory. The one exception is
`tests/test_figexport.py`, which covers `figexport.py` because the figures it
writes end up on a printed board and a silent regression there is expensive.

Derived output sits inside whatever produces it — `poster/exports`,
`notebooks/_digest`, `notebooks/_outputs`, `notebooks/robustness/_outputs` — and
all of it is gitignored.

## The notebooks

Two strands. **01 to 03** evaluate trading strategies against a backtest: the
framework proving itself. **04 to 10** study the real GB battery fleet, and are
best read in order, because each interrogates the one before it.

| | | |
|---|---|---|
| **01** | Day-ahead positioning backtest | Virtual trading against imbalance. Baseline, model selection, walk-forward calibration, execution limits. |
| **02** | Hybrid execution hedge ratio | Holds 01's entry signals fixed and sweeps the execution layer alone. |
| **03** | BESS dispatch analysis | The battery strategy over 01's window. Much of this became the dashboard's benchmark pages. |
| **04** | Alignment gap | **The research question.** How much profit-optimal battery behaviour coincides with what a resilient system needs, and what does closing the gap cost? |
| **05** | Stress response study | Takes the question to the real fleet, measured against the operator's own scarcity instruments rather than a price proxy. |
| **06** | Fleet coverage census | Reconstructs the GB battery population, because nobody publishes it and 04 and 05 need a denominator before "the fleet" means anything. |
| **07** | Regime shift | **Attacks 05.** Its response-quadrupling is modelled as a trend; this asks whether it is instead a step change at the Open Balancing Platform cutover. |
| **08** | Stress response, modern era | Re-cuts 05 on the post-break window, because 07 showed 05's window spans a structural break. |
| **09** | Model vs fleet | Reconciles 04 and 05, which answered different questions with different rulers and were never comparable. Puts both on one yardstick. |
| **10** | Acceptances | **Corrects 05, 08 and 09.** They measure from Final Physical Notifications, which are plans; the Balancing Mechanism instructs units away from them, and for GB batteries the accepted volume is of the same order as the notified position. |

04 asks, 05 measures, 06 supplies the denominator, 07 challenges, 08 re-measures,
09 reconciles, 10 corrects.

## notebooks/robustness/

Checks on what those notebooks claim. They live here rather than beside the
poster because they test the analysis, not the board: delete the poster and you
would still want to know whether the findings hold. Each reuses the notebooks'
own definitions, so a check cannot quietly measure something different from what
it is checking. They are scripts rather than cells because they re-fetch history
and take minutes.

| | tests |
|---|---|
| `acceptances_delivery_window.py` | Does correcting notifications for Balancing Mechanism acceptances move measured delivery, over a pinned window? |
| `acceptances_full_history.py` | The same correction across 2018–2026, which state-of-charge integration needs. Several minutes on a warm cache. |
| `acceptances_under_scarcity.py` | Does that correction change sign under operator scarcity, where the expectation is the opposite of the top-decile-load case? |
| `mels_bound_sensitivity.py` | Does notebook 09's 85% survive a per-period availability bound instead of a flat mean? |
| `statistical_checks.py` | Break placement, load as a confounder, margin-forecast skill by horizon, and whether the response interval survives event clustering. Writes the board's `stats_metrics.json`. |

Run any of them from anywhere:

```bash
python research/notebooks/robustness/statistical_checks.py
```

## Running any of this

**The notebooks cannot be re-run from a clone.** They read a processed store
built from NESO, Elexon and ENTSO-E feeds that is roughly 18 GB and is not in the
repository. Rebuild it first with `scripts/build_stress_store.py` and
`scripts/backfill_market_data.py` — hours, and an ENTSO-E API key.

That is also why notebook **outputs are committed**: they are the only way to read
the study without rebuilding the data, they render on GitHub, and
`build_digest.py` extracts the digest's charts directly from them. For the same
reason the poster's inputs are tracked while its exports are not — see
[`poster/README.md`](poster/README.md).

```bash
make poster    # compile the A0 board
make digest    # rebuild the digest from stored outputs
```
