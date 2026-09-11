# Start-date sensitivity: the same strategy from different account inceptions

The experiment restarts each account at £50,000 on the first saved market date
in July, August, September, October and November. Each restart has no earlier
positions, unsettled PnL or capital-floor state. The saved walk-forward forecasts,
entry signals, costs, sizing conventions and exit rules are frozen. We rerun the
engine; we do not merely rebase the original equity curve.

The starts are **23 July, 1 August, 1 September, 1 October and 2 November 2018**.
The requested July and November month beginnings have no saved forecasts.

## Comparisons and coverage

- **20-calendar-day comparison:** the common horizon selected from saved forecast
  date coverage, capped at 30 days, before scoring performance. October's coverage
  ends on 20 October. November has incomplete common-price coverage, marked †;
  its row is therefore a limited-coverage diagnostic.
- **Seven-calendar-day check:** the common horizon with at least one common-price
  observation on every date for all starts. This is too short to establish
  robustness; it checks the direction of the shorter-window comparison.
- **Every start through 31 December:** tests survival and path dependence over
  unequal durations. The endpoints are not a fair ranking of start dates.

Common-price eligibility is shared across strategies: a missing required price
suppresses that period's signal for all variants. Date coverage does not mean
all half-hours have observations. Every row reports calendar days, forecast days,
common-price days and excluded signals. The unscored 21 October–1 November interval
is retained as idle in the saved-signal replay and shaded in the figures. It is
not evidence that a deployed strategy would have chosen to hold cash then.

Returns and Sharpe use London calendar days within each account window, including
explicit idle dates. Short-window Sharpe is descriptive, not reliable evidence of
an edge. Terminal equity below the hard floor is flagged separately: a window can
end before another auction exists at which the delayed capital halt could trigger.

The risk-policy comparisons are the original 2% reference notional per trade and
the previously declared common book-risk policy. The latter was designed after
this historical sample had been inspected. This study selects no new start date,
forecast model, hedge ratio or risk parameter, and is retrospective throughout.

## Does starting in September resolve the problem?

At the original sizing, from 1 September to 31 December:

| Strategy | Net PnL | Return | Capital halt |
|---|---:|---:|---|
| Full imbalance | £131,330 | +262.7% | No |
| Systematic intraday unwind | £-8,105 | -16.2% | Yes |
| Conditional TP/SL | £36,420 | +72.8% | No |
| 50/50 with TP/SL | £-1,910 | -3.8% | No |
| Pure 50/50 hedge | £21,711 | +43.4% | No |

September avoids the August event and changes which accounts survive. It does
not eliminate the underlying vulnerability: systematic intraday unwind still
halts, and the 50/50 TP/SL overlay finishes with a loss despite surviving.
The pure 50/50 hedge and conditional execution finish profitably from this start.
Across the five year-end replays, systematic intraday unwind halts at every
original-sized start. With common book risk limits, all five strategies survive
from all five starts; profitability still varies.

## What this contributes to a strategy-development notebook

The framework showcase and this sensitivity experiment serve different purposes.
Notebook 02 compares fixed-volume exit policies across a common full period; different inception dates are an appendix diagnostic, not substitutes
for the strategy lines. A benchmark need not be profitable to be informative.

The equal-length October window is an example in which conditional intraday exits
outperform holding everything to imbalance. September shows the opposite ranking.
This is evidence to investigate regime-dependent exit decisions, not a reason to
select October for the showcase. A next hypothesis could use information available
at a fixed intraday decision time to estimate remaining cash-out edge and its
uncertainty, then compare holding with executable closing prices and costs. That
hypothesis needs its own chronological validation and appropriate execution data.

## Reproduction and validation

Run `python scripts/run_start_date_study.py` or execute
`research/notebooks/11_start_date_sensitivity.ipynb`. The output folder beside the
selected run's trading artifacts is `start_date_sensitivity/` and contains
`report.json` (including the result table) and `daily_pnl.csv`. Source and data hashes are recorded.
There are 150 runs: five starts, three window definitions, two risk policies and
five execution strategies. Existing notebook 02 and README charts are not modified.

Ninety engine, risk-policy and restart tests passed, including account-state reset,
coverage-selected horizons, missing-month rejection and London DST boundaries.

The three appendix figures are embedded in notebook 11. The script can return
figures in memory to the notebook and does not save PNG copies.
