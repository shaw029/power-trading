# Execution strategy construction with book risk limits

The original rule allocated 2% reference notional to each signalled half-hour.
Across many correlated periods and overlapping unsettled books, that could produce
large losses before the next auction had observable settlement information. The
20% initial-capital floor then stopped the account permanently. Simply widening
that floor would not address the allocation problem.

The new experiment retains the entry signals, execution costs and final floor,
and adds a common prospective book-risk policy. It also separates a **pure partial
intraday hedge** from a hedge whose remaining position uses TP/SL.

## Declared policy

`configs/execution_risk_study.yaml` specifies the research policy; it is not a
replacement for notebook 01's selected configuration.

- **Stress loss per gross MWh:** £50 adverse price movement + £1 fee + £2 execution
  friction = £53. The same conservative charge applies to every exit. There is
  no diversification or hedge credit, and no claim that £50 bounds actual prices.
- **Daily new-book budget:** 1% of equity observable at the auction. At £50,000,
  £500 / £53 allows approximately 9.43 MWh across the whole book, allocated
  pro rata to the original proposed quantities.
- **Outstanding budget:** 2% of available equity across unsettled books. Each
  commitment reserves its entry stress allocation until its assumed publication
  time. New orders can use only the remaining capacity. A drop in equity cannot
  retrospectively cancel old commitments.
- **Soft drawdown control:** use the running peak of observable settled equity.
  Reduce the daily budget linearly after 5% drawdown, reaching 25% of normal size
  at 15%. Size can recover with observable equity. This rule never looks at PnL
  from an unpublished book.
- **Hard floor:** retain the existing halt at 20% below initial capital. An extreme
  move beyond the stress scenario can still trigger it. Tests explicitly cover this.

This follows the general position-sizing principle of deriving quantity from an
account loss budget and loss per unit. [CME's position-sizing explanation](https://www.cmegroup.com/education/courses/trade-and-risk-management/proper-position-size)
describes that principle for executable stops; here the denominator is an explicit
**stress scenario**, because the available market index cannot support a real stop
order simulation. These particular thresholds are illustrative research choices,
not universal industry standards or fitted optimal values.

## Research protocol

The four original overlays and five pure hedge ratios receive the same policy.
The pure hedge ratios are 0%, 25%, 50%, 75% and 100% intraday; the remaining slice
settles at imbalance and has TP/SL disabled. No winner or new risk parameters are
selected by these replays. We retain each result, including losses.

The policy was designed after these data had been inspected. Development and the
previously examined evaluation segment are replayed separately with £50,000
starting accounts, plus one continuous full replay. None is a fresh validation
sample. The continuous result is not the sum of the independently reset accounts.

All variants skip exactly the same 43 signalled periods lacking a required price.
The complete replay retains all 150 market dates, with 148 dates containing
common-price observations and eligible books. The two unavailable dates are not
filled with fabricated execution prices. All managed variants execute all 1,911
remaining signals, incur no budget pauses and trade through 31 December 2018.
The common-price baseline therefore differs from earlier headline backtests that
allowed missing MID observations to fall back to imbalance.

## Results: continuous historical replay

| Original exit overlay | Net PnL | Daily-return Sharpe | Max peak drawdown | Completed |
|---|---:|---:|---:|---|
| Full imbalance | £4,420 | 4.94 | -0.96% | True |
| Systematic intraday unwind | £-1,806 | -3.91 | -4.23% | True |
| Conditional TP/SL | £1,257 | 1.97 | -1.59% | True |
| 50/50 with TP/SL remainder | £-297 | -0.56 | -2.15% | True |

| Pure hedge | Net PnL | Daily-return Sharpe | Max peak drawdown | Completed |
|---|---:|---:|---:|---|
| 0% intraday / 100% imbalance | £4,420 | 4.94 | -0.96% | True |
| 25% intraday / 75% imbalance | £2,796 | 3.82 | -1.11% | True |
| 50% intraday / 50% imbalance | £1,218 | 2.05 | -1.27% | True |
| 75% intraday / 25% imbalance | £-316 | -0.62 | -1.94% | True |
| 100% intraday / 0% imbalance | £-1,806 | -3.91 | -4.23% | True |

The daily book and outstanding caps cause the sizing reduction in this sample.
Observed drawdowns remain below 5%, so the soft drawdown multiplier stays at one.
It is a tested contingency, not an explanation for the observed improvement.

Completing a replay is an operational outcome, not evidence of an economic edge.
Systematic intraday unwinding still loses money, and the 50/50 TP/SL overlay loses
money over the continuous replay. The pure 50/50 hedge remains profitable in that
replay, but full imbalance still earns more. Smaller exposure and reduced PnL
volatility are useful risk outcomes even when they reduce total expected profit.

The tables cover the **complete saved historical replay through
31 December**, with 150 observed market dates. The saved predictions have no coverage for 21 October
to 1 November; no trades are fabricated in that interval. This is
separate from the two missing common-price dates within the saved evaluation
window. The script report includes the two separately reset splits. Notebook 02
now isolates fixed-volume hedge payoffs and is a different experiment.

## Practical limits and reproduction

MID is a historical index of qualifying trades, not a quote executable at the
strategy's chosen timestamp. The TP/SL comparison remains an index-based research
proxy. [Elexon's index definition](https://bscdocs.elexon.co.uk/category-3-documents/market-index-definition-statement)
describes its aggregation. Collateral calls, funding, depth, minimum order sizes
and historical publication vintages remain outside this model. Fractional MWh
allocations are permitted, so a deployable version must enforce product lot sizes.

A prospective extension would estimate adverse-move scenarios from information
available before each auction and assess them across stress regimes, while retaining
hard exposure caps. Timestamped executable intraday data are needed to assess a
real dynamic exit policy. A fresh chronological sample is needed before judging
whether a revised policy generalises.

Run `python scripts/run_execution_risk_study.py` from the repository root. The script writes `execution_risk_study.json` next to the
selected run's trading artifacts; it does not export images. The JSON
contains policy inputs, coverage, all replay results and per-auction risk ledgers.
The engine's optional `book_risk_policy` argument leaves the original API behavior
unchanged when omitted.

Risk tests cover gross book limits, pending reservations,
publication timing, unavailable future PnL, drawdown sizing and the hard halt.

## Audit of the 20 August loss day

The cached APXMIDP, imbalance and day-ahead prices were checked against all 48
half-hour backtest inputs. Every price matched exactly. All 48 APXMIDP records
had positive volume (minimum 75 MWh), with no conflicting duplicate prices or
missing settlement periods. There is no day-specific corruption established by
these checks; they verify the cached sources and transformations, not independent
historical vintages.

The selected schedule contained 15 shorts. At 17:00 UTC, for example, DA was
£90/MWh, MID £160.01/MWh and imbalance £42.13911/MWh. Buying back at the intraday
proxy therefore locked in a loss while settlement later favoured the short.
At one MWh per selected signal, that day's net PnL was −£276.16 for full imbalance
and −£535.05 for full intraday unwind. The day remains in every comparison.
