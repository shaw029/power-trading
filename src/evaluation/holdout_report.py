"""Retrospective evaluation scoring and conditional day-bootstrap intervals.

The reserved 2018 tail is excluded from the current selection procedure but has
been inspected in earlier research. Intervals resample observed cash PnL and
account returns independently by market day; they do not rerun compounding,
risk halts, selection or serial dependence. The always-short control retains
model-selected timestamps and is a directional, not model-free, control.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.backtest.engine import run_backtest

logger = logging.getLogger(__name__)

#: Resampling settings. Fixed here rather than passed in, so a quoted interval
#: always refers to the same procedure.
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 7
CONFIDENCE = (2.5, 97.5)

#: Trading days per year. Power markets clear every calendar day.
ANNUALISATION_DAYS = 365


def _daily_returns(pnl: np.ndarray, timestamps, starting_capital: float) -> pd.Series:
    """Daily percentage returns on the equity each book was sized against.

    Position size scales with equity, so cash P&L is not stationary: £500 early
    and £500 at three times the capital are different results.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True)).tz_convert("Europe/London")
    daily = pd.Series(pnl, index=idx.normalize()).groupby(level=0).sum()
    opening = starting_capital + daily.cumsum().shift(1).fillna(0.0)
    return (daily / opening).replace([np.inf, -np.inf], np.nan).dropna()


def bootstrap_interval(daily: pd.Series, starting_capital: float) -> dict:
    """Percentile bootstrap over market days for total P&L and annualised Sharpe.

    Days are resampled with replacement because a market day is the unit the
    strategy commits at — resampling individual settlement periods would break
    the book structure and understate the spread.
    """
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    returns = (daily / (starting_capital + daily.cumsum().shift(1).fillna(0.0))).to_numpy()
    cash = daily.to_numpy()

    sharpes, pnls = [], []
    for _ in range(BOOTSTRAP_REPLICATES):
        draw = rng.integers(0, len(cash), len(cash))
        r = returns[draw]
        sharpes.append(
            float(r.mean() / r.std() * np.sqrt(ANNUALISATION_DAYS)) if r.std() > 0 else 0.0
        )
        pnls.append(float(cash[draw].sum()))

    lo, hi = CONFIDENCE
    return {
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "resample_unit": "market day",
        "sharpe_ci": (float(np.percentile(sharpes, lo)), float(np.percentile(sharpes, hi))),
        "pnl_ci": (float(np.percentile(pnls, lo)), float(np.percentile(pnls, hi))),
    }


def always_short_control(frame: pd.DataFrame, **backtest_kwargs) -> dict:
    """The same periods, same sizing, but every position shorted.

    Not a strawman: the unconditional cash-out-minus-auction spread is negative
    in this sample, so this earns money with no forecast. It is the bar the
    model has to clear, and quoting strategy P&L without it overstates the
    contribution of the forecast.
    """
    signals = np.where(frame["signal"].to_numpy() != 0, -1, 0)
    _, metrics = run_backtest(
        signals=signals,
        da_prices=frame["day_ahead_price"].to_numpy(),
        system_sell_price=frame["system_sell_price"].to_numpy(),
        system_buy_price=frame["system_buy_price"].to_numpy(),
        timestamps=frame["time"].to_numpy(),
        **backtest_kwargs,
    )
    return {"total_pnl": metrics["total_pnl"], "sharpe_ratio": metrics["sharpe_ratio"]}


def score_holdout(
    frame: pd.DataFrame,
    starting_capital: float = 50_000.0,
    **backtest_kwargs,
) -> dict:
    """Score one frozen configuration on the holdout, once, with its interval.

    Args:
        frame: holdout rows only, carrying time, signal, the three price columns
               and predicted_spread. Passing development rows here would defeat
               the purpose of the split.
        starting_capital: opening equity.
        **backtest_kwargs: execution settings of the frozen configuration —
               these must match what selection chose, not be re-tuned here.

    Returns:
        Point estimates, the bootstrap interval and its settings, and the
        always-short control on the same periods.
    """
    pnl, metrics = run_backtest(
        signals=frame["signal"].to_numpy(),
        da_prices=frame["day_ahead_price"].to_numpy(),
        system_sell_price=frame["system_sell_price"].to_numpy(),
        system_buy_price=frame["system_buy_price"].to_numpy(),
        timestamps=frame["time"].to_numpy(),
        starting_capital=starting_capital,
        **backtest_kwargs,
    )

    idx = pd.DatetimeIndex(pd.to_datetime(frame["time"], utc=True)).tz_convert("Europe/London")
    daily = pd.Series(pnl, index=idx.normalize()).groupby(level=0).sum()

    report = {
        "days": int(len(daily)),
        "n_trades": int(metrics["n_trades"]),
        "total_pnl": float(metrics["total_pnl"]),
        "gross_pnl": float(metrics["gross_pnl"]),
        "total_transaction_costs": float(metrics["total_transaction_costs"]),
        "total_position_mwh": float(metrics["total_position_mwh"]),
        "sharpe_ratio": float(metrics["sharpe_ratio"]),
        "max_drawdown": float(metrics["max_drawdown"]),
        "win_rate": float(metrics["win_rate"]),
        "positive_days": int((daily > 0).sum()),
        **bootstrap_interval(daily, starting_capital),
        "always_short_control": always_short_control(
            frame, starting_capital=starting_capital, **backtest_kwargs
        ),
    }

    logger.info(
        "Holdout: %d days, %d trades, PnL £%.0f, Sharpe %.2f (95%% CI %.2f–%.2f)",
        report["days"],
        report["n_trades"],
        report["total_pnl"],
        report["sharpe_ratio"],
        *report["sharpe_ci"],
    )
    return report
