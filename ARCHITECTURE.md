# Architecture

## Strategy

The GB electricity market has two settlement layers. The **day-ahead auction** (EPEX SPOT GB, closes ~11:00 AM on Day-1) fixes a price `P_DA` for each 30-min period. Parties that deviate from their position settle at the **System Sell Price** (SSP) if long, or **System Buy Price** (SBP) if short.

The model predicts `SSP − DA_price` for each period. A positive prediction favours buying at auction and settling long; a negative prediction favours selling at auction and settling short.

## Forecast Features

Wind and demand forecasts are pivoted into two families:

- **Rolling snapshots** — the latest published forecast at 1h, 3h, 6h, 12h, 24h before each delivery period.
- **Auction-day snapshots** — the latest forecast available at fixed clock times (D-2 noon, D-1 midnight, D-1 07:00, D-1 10:30). The 10:30 vintage is the final pre-auction view and carries the most predictive weight.

All cutoff arithmetic runs in UTC after deriving the GB market date in Europe/London so that DST transitions don't create gaps.

## Leakage Prevention

The auction closes at 11:00 AM Day-1. No same-day actuals (demand, generation, imbalance volume) appear in the feature set. Lagged actuals use a minimum 48-period (24 h) offset to ensure nothing from the target day leaks in.

## Signal Logic

Two filters before a trade fires:

1. **Penalty buffer** — a 7-day rolling mean of `SBP − SSP`, lagged 48 h, estimates the expected round-trip imbalance cost. The signal threshold is `max(0, penalty_buffer) + 5.0 £/MWh`. This prevents the model acting when the spread edge is smaller than the settlement cost.

2. **Top-5 schedule** — from the periods that pass the confidence filter, only the 5 highest `|predicted_spread|` slots per direction per market day are kept. This reflects the realistic constraint that a non-asset trader submits a small number of targeted bids (max 10 trades/day).

## Backtest Design

The backtest simulates a funded account rather than a fixed notional. Position size is `(current_capital × 2%) / DA_price`, so it scales with equity growth and shrinks after drawdowns. A max-drawdown halt at 80% of starting capital stops the simulation if the strategy loses severely — consistent with how a real desk would manage risk.
