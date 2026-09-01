# Research

The study this repository was built to run, and the board that presents it.

The framework lives at the repo root (`src/`, `fleet/`, `live/`);
everything here uses it. The dependency runs one way only — no framework module,
and nothing the dashboard serves, imports anything from this directory — so the
study can be read on its own and changed without touching production code. The
one exception is `tests/test_figexport.py`, which covers `figexport.py` because
the figures it writes end up on a printed board and a silent regression there is
expensive.

```
research/
├── notebooks/    the study, 01 to 10, in dependency order
├── analysis/     robustness checks too slow or too narrow for a notebook
├── poster/       the A0 board — layout source, tracked inputs, build script
├── figures/      notebook figure exports        (derived, gitignored)
└── outputs/      analysis CSVs, pickles, digest (derived, gitignored)
```

## The notebooks

Two strands. **01 to 03** evaluate trading strategies against a backtest: they
are the framework proving itself. **04 to 10** are a study of the real GB battery
fleet, and they are best read in order, because each one interrogates the one
before it.

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

The short version of the argument: 04 asks, 05 measures, 06 supplies the
denominator, 07 challenges, 08 re-measures, 09 reconciles, 10 corrects.

## analysis/

Robustness checks that support the study but do not belong in a notebook —
either because they re-fetch history and take minutes, or because they answer a
single narrow question. Each reuses the notebooks' own definitions, so a check
cannot quietly measure something different from what it is checking.

| | |
|---|---|
| `acceptances_delivery_window.py` | Top-decile delivery over a pinned window, computed from notifications alone and again corrected by acceptances, so the difference is the answer. |
| `acceptances_full_history.py` | The same correction across the whole 2018–2026 window, which state-of-charge integration needs. Several minutes on a warm cache. |
| `acceptances_under_scarcity.py` | Acceptances during operator scarcity, where the expected sign is the opposite of the top-decile-load case. Measured rather than assumed. |
| `mels_bound_sensitivity.py` | Does notebook 09's flat-mean availability bound carry its headline, or does a per-period bound move it? |
| `robustness_checks.py` | The remaining offline checks: normalisation, tightness rules, and the sensitivity sweeps behind the board's caveats. |

Run any of them from anywhere:

```bash
python research/analysis/robustness_checks.py
```

## Running any of this

**The notebooks cannot be re-run from a clone.** They read a processed store
built from NESO, Elexon and ENTSO-E feeds that is roughly 18 GB and is not in
the repository. Rebuild it first with `scripts/build_stress_store.py` and
`scripts/backfill_market_data.py`, which will take hours and an ENTSO-E API key.

That is also why notebook **outputs are committed**. They are the only way to
read the study without rebuilding the data, they render on GitHub, and
`build_digest.py` extracts the digest's charts directly from them.

For the same reason the poster's inputs are tracked while the bulk of
`figures/` is not — see [`poster/README.md`](poster/README.md).

```bash
make poster    # compile both A0 variants
make digest    # rebuild the notebook digest from stored outputs
```
