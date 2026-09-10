# Research audit fixes — 10 September 2026

Applied to the project reviewed at `1c9d7c1`. The canonical experiment is now
`s4_n15_t30_vm00_tc10`, selected by notebook 01 on development data only.

| Finding | Resolution and evidence |
|---|---|
| Stale demand features | Rebuilt from the cached raw archive. Saved demand has zero non-null values where fresh preprocessing is missing and zero finite-value differences. Shared-feature provenance matches the current code, configuration and raw manifest. |
| Holdout used in selection | Candidates reserve 60 market days with holdout prediction disabled. Family baselines and the XGBoost grid compete on development MAE. Only the frozen choice evaluates the reserved tail. Previously examined data are labelled retrospective evaluation. |
| Empty-day capital halt | Settlements enter available equity by dated availability before every auction check, including empty days and delivery-date gaps. Regression tests reproduce and prevent the bypass. |
| Ex-post quantity sizing | The default sizing reference is fixed at £50/MWh before the auction. Cleared DA price changes no longer change committed MWh. An optional reference-price array must represent pre-auction inputs. |
| Training availability | Labels require settlement-period end plus a one-hour publication assumption before the auction decision, including static validation. This is a research timing convention, not proof of historical publication vintage. |
| Naive control | Uses the same fresh feature/price artifact, exact comparison timestamps, dated books, cost settings and sizing convention. |
| BESS replay mismatch | Pipeline, notebook and replay app share strict native-period aggregation and London market-day indices. Native dispatch prices and fold forecasts are persisted. Notebook 03 asserts identical dates and daily PnL against the pipeline ledger. Missing inputs use training-fold median imputation, explicitly flagged. |
| Live cache and coverage | Recent raw Elexon/Nord Pool/fleet day files expire after 15 minutes within a five-day provisional window. Partial MID coverage is detected before averaging and propagated to displayed settlement results. The existing live policy benchmark uses explicitly validated 24-hour UTC days. |
| Documentation and policy | Corrected selection rules, feature definitions, metric labels, chart scopes and bootstrap limitations. Duration frontiers visibly disclose daily 50% SOC resets with unpriced inventory transfers. Poster remains one page. |

Rebuilt outcomes:

- Linear regression wins development MAE. The signal choice is top 15 per
  direction, £3/MWh threshold, zero volatility multiplier and £1/MWh fees.
- Development: £113,699.65 net PnL; Sharpe 5.01.
- Retrospective evaluation: £44,542.48 net PnL; Sharpe 4.42. Conditional 95%
  intervals are −£24,358 to £112,361 and −0.43 to 10.11 respectively. Both
  include zero; the experiment does not establish a reliable trading edge.
- Every hybrid candidate breaches the capital floor. Notebook 02 reports no
  eligible hybrid, retaining a rejected candidate only as a diagnostic.
- BESS replay: 95 complete days, £128,144.50 net PnL (see the saved ledger for
  precision). Of 7,200 half-hour forecast rows, 1,066 use training-fold median
  imputation. Skipped dates are assumed idle for carried SOC; uncertainty in
  pre-auction opening inventory is not simulated. The day count fell from 104
  after zero-volume market-index periods stopped being read as £0 prices (below):
  those periods now fail coverage instead of supplying a phantom price.

## Follow-up, 10 September 2026

| Finding | Resolution and evidence |
|---|---|
| Market index £0 prints | Elexon reports `price: 0.0` with `volume: 0.0` when no qualifying trade occurred in a settlement period. The processor read `price` and ignored `volume`, so "no trades" entered the series as a £0 clearing price — visible as the MID collapse on 2018-11-29. Across the 2018 APXMIDP feed the correspondence is exact: 212 zero-volume records, all priced £0.00, and no zero-volume record carrying a real price. Three genuine £0 prints with real volume exist, so the test is on volume, not on the price being zero. Zero-volume periods now return NaN, which the live adapter already records via `mid_is_proxy`. Thirteen such periods fell inside the canonical traded window and seven carried a live signal; they did not affect the published headline because the canonical configuration runs with the TP/SL gate off, but they were live in the gate-on archetypes and the BESS intraday engine. |
| Fleet volume chart sign | A balancing segment is signed against the direction it moves, so cutting notified charging renders the charge segment *above* the axis. The arithmetic was right — notified plus balancing equals delivered — but the axis claimed "charge shown negative" and the hover gave a bare signed number, so a cancelled 80 MWh of charging read as 80 MWh of charging. Axis and hover now name the direction ("Balancing removed 80 MWh of charging"); four tests pin both the stack arithmetic and the wording. |
| Notebook 02 read as all-negative | Four of five archetypes lose money because they all run the take-profit/stop-loss gate; `Full Imbalance Exposure` does not, and returns £113,700. The notebook now decomposes that single binary choice: the gate costs £117,921 on this signal, of which £83,235 is spread crossing at £2/MWh per intraday exit. The hedge-ratio sweep varies passive share *within* the gate-on archetype, so every point of it inherits that cost first. |

Validation: all three notebooks executed successfully with regenerated figures;
659 tests passed and one optional local-config test skipped. After the last BESS
price-artifact change, all 71 relevant pipeline/chart/dashboard tests passed.
Black checked Python sources, flake8 passed, and mypy passed across 94 source files.
The poster was compiled and visually checked as one A0 page. Notebook 03's replay
matches the pipeline's daily PnL within numerical solver tolerance.

The live dashboard's fetch and settlement behavior was tested locally with mocks;
the deployed Streamlit app was not accessed or redeployed. The policy calculations
were not re-estimated: their disclosed inventory assumptions changed. Historical
raw archives and the global processed dataset are preserved. Generated experiment
artifacts remain gitignored; the selected manifest identifies the current run.

Reproduce with notebook 01, `main.py --config configs/config.example.yaml --mode
bess`, then notebooks 02 and 03. `scripts/execute_research_notebook.py` runs a
notebook in process; `scripts/refresh_research_summary.py` refreshes README metrics
and its equity image from the selected artifacts. The original raw archives are
required; the public endpoints may no longer serve every historical date.
