import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def run_backtest(
    signals: np.ndarray,
    da_prices: np.ndarray,
    system_sell_price: np.ndarray,
    system_buy_price: np.ndarray,
    timestamps=None,
    cost_per_trade: float = 0.1,
    starting_capital: float = 50_000.0,
    risk_pct: float = 0.02,
    max_drawdown_pct: float = 0.20,
) -> tuple:
    """Run backtest for a Day-Ahead Auction vs Imbalance settlement strategy.

    Position sizing is account-based:
        position_mwh = (current_capital × risk_pct) / da_price
    This commits a fixed fraction of current equity per trade at the auction
    price, so position size scales naturally with account growth/decline.

    The simulation halts if the account breaches the maximum drawdown floor:
        floor = starting_capital × (1 − max_drawdown_pct)

    PnL per settlement period (in £, not per-MWh):
        LONG  (signal= 1): (SSP − DA) × position_mwh − cost × position_mwh
        SHORT (signal=-1): (DA − SBP) × position_mwh − cost × position_mwh
        NEUTRAL (0):        0

    Args:
        signals:            1 = Long DA, −1 = Short DA, 0 = Neutral.
        da_prices:          Day-ahead price (£/MWh).
        system_sell_price:  Imbalance SSP (£/MWh).
        system_buy_price:   Imbalance SBP (£/MWh).
        timestamps:         UTC timestamps for daily aggregation (optional).
        cost_per_trade:     Transaction cost (£/MWh of position).
        starting_capital:   Initial account equity (£).
        risk_pct:           Fraction of current equity to commit per trade.
        max_drawdown_pct:   Halt threshold — fraction of starting capital lost.

    Returns:
        (net_pnl, trading_metrics)
        net_pnl — per-period absolute PnL array (£), length == len(signals)
    """
    signals   = np.asarray(signals,           dtype=int)
    da_prices = np.asarray(da_prices,         dtype=float)
    sys_sell  = np.asarray(system_sell_price, dtype=float)
    sys_buy   = np.asarray(system_buy_price,  dtype=float)
    n = len(signals)

    if not (len(da_prices) == len(sys_sell) == len(sys_buy) == n):
        raise ValueError("All input arrays must have the same length")

    # ------------------------------------------------------------------
    # Account-based position sizing loop
    # ------------------------------------------------------------------
    drawdown_floor  = starting_capital * (1.0 - max_drawdown_pct)
    current_capital = starting_capital
    net_pnl         = np.zeros(n, dtype=float)
    halted_at       = None

    for i in range(n):
        if current_capital <= drawdown_floor:
            halted_at = i
            logger.warning(
                "Max drawdown reached at period %d (capital £%.0f ≤ floor £%.0f) — simulation halted",
                i, current_capital, drawdown_floor,
            )
            break

        if signals[i] == 0:
            continue

        # Use abs(da_price) floored at £10 so negative or near-zero prices
        # (which occurred in GB in 2018/2019) don't invert or inflate position size.
        price_denominator = max(abs(da_prices[i]), 10.0)
        position_mwh = (current_capital * risk_pct) / price_denominator

        if signals[i] == 1:
            gross = position_mwh * (sys_sell[i] - da_prices[i])
        else:
            gross = position_mwh * (da_prices[i] - sys_buy[i])

        net         = gross - cost_per_trade * position_mwh
        net_pnl[i]  = net
        current_capital += net

    final_capital    = starting_capital + float(np.sum(net_pnl))
    total_return_pct = (final_capital - starting_capital) / starting_capital

    # ------------------------------------------------------------------
    # Daily aggregation (Europe/London market dates)
    # ------------------------------------------------------------------
    daily_pnl     = None
    daily_summary = {}

    if timestamps is not None:
        ts          = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))
        market_date = ts.tz_convert("Europe/London").normalize()
        daily_pnl   = (
            pd.Series(net_pnl, index=market_date, name="net_pnl")
            .groupby(level=0)
            .sum()
        )
        if len(daily_pnl) > 0:
            daily_summary = {
                "mean_daily_pnl": float(daily_pnl.mean()),
                "std_daily_pnl":  float(daily_pnl.std()),
                "best_day_pnl":   float(daily_pnl.max()),
                "worst_day_pnl":  float(daily_pnl.min()),
                "positive_days":  int((daily_pnl > 0).sum()),
                "negative_days":  int((daily_pnl < 0).sum()),
                "total_days":     int(len(daily_pnl)),
            }

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    active_pnl   = net_pnl[net_pnl != 0]
    total_pnl    = float(np.sum(net_pnl))
    n_active     = int((signals != 0).sum())
    mean_pnl     = float(np.mean(active_pnl)) if len(active_pnl) > 0 else 0.0
    std_pnl      = float(np.std(active_pnl))  if len(active_pnl) > 0 else 0.0

    # Sharpe — daily if available (natural unit for a once-per-day auction decision)
    sharpe_ratio = 0.0
    if daily_pnl is not None and float(daily_pnl.std()) > 0:
        sharpe_ratio = float(daily_pnl.mean() / daily_pnl.std() * np.sqrt(252))
    elif std_pnl > 0:
        sharpe_ratio = float(mean_pnl / std_pnl * np.sqrt(48 * 365))

    # Drawdown on cumulative £ PnL
    cum_pnl      = np.cumsum(net_pnl)
    running_max  = np.maximum.accumulate(cum_pnl)
    drawdowns    = cum_pnl - running_max
    max_drawdown = float(np.min(drawdowns)) if n > 0 else 0.0

    # Win / loss
    win_mask  = net_pnl > 0
    loss_mask = net_pnl < 0
    win_rate  = float(win_mask.sum()) / n_active if n_active > 0 else 0.0
    avg_win   = float(np.mean(net_pnl[win_mask]))  if win_mask.any()  else 0.0
    avg_loss  = float(np.mean(net_pnl[loss_mask])) if loss_mask.any() else 0.0

    sum_wins   = float(np.sum(net_pnl[win_mask]))  if win_mask.any()  else 0.0
    sum_losses = float(np.sum(net_pnl[loss_mask])) if loss_mask.any() else 0.0
    profit_factor = sum_wins / abs(sum_losses) if sum_losses != 0.0 else float("inf")

    n_long    = int((signals ==  1).sum())
    n_short   = int((signals == -1).sum())
    n_neutral = int((signals ==  0).sum())

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    logger.info("Backtest complete (account-based sizing)")
    logger.info("  Starting capital: £%s", f"{starting_capital:>10,.0f}")
    logger.info("  Final capital:    £%s  (%+.1f%%)", f"{final_capital:>10,.0f}", total_return_pct * 100)
    logger.info("  Total PnL:        £%s", f"{total_pnl:>10,.2f}")
    logger.info("  Sharpe:            %.3f",  sharpe_ratio)
    logger.info("  Profit factor:     %.2f",  profit_factor)
    logger.info("  Max drawdown:     £%s", f"{max_drawdown:>10,.2f}")
    logger.info("  Win rate:          %.1f%%", win_rate * 100)
    logger.info("  Active trades:    %d / %d periods", n_active, n)
    if halted_at is not None:
        logger.warning("  Simulation HALTED at period %d of %d", halted_at, n)
    if daily_summary:
        logger.info(
            "  Daily PnL — Mean: £%.0f  Std: £%.0f  Best: £%.0f  Worst: £%.0f  (+%d/-%d days)",
            daily_summary["mean_daily_pnl"], daily_summary["std_daily_pnl"],
            daily_summary["best_day_pnl"],   daily_summary["worst_day_pnl"],
            daily_summary["positive_days"],  daily_summary["negative_days"],
        )

    trading_metrics = {
        "starting_capital":  starting_capital,
        "final_capital":     final_capital,
        "total_return_pct":  total_return_pct,
        "total_pnl":         total_pnl,
        "n_trades":          n_active,
        "win_rate":          win_rate,
        "avg_trade":         mean_pnl,
        "avg_win":           avg_win,
        "avg_loss":          avg_loss,
        "profit_factor":     profit_factor,
        "sharpe_ratio":      sharpe_ratio,
        "max_drawdown":      max_drawdown,
        "halted_at_period":  halted_at,
        "signal_distribution": {
            "long":    n_long,
            "short":   n_short,
            "neutral": n_neutral,
        },
        "daily_summary": daily_summary,
    }

    return net_pnl, trading_metrics


def run_backtest_from_dataframe(
    df: pd.DataFrame,
    signal_col:     str   = "signal",
    da_price_col:   str   = "day_ahead_price",
    sell_price_col: str   = "system_sell_price",
    buy_price_col:  str   = "system_buy_price",
    time_col:       str   = "time",
    cost_per_trade: float = 0.1,
    starting_capital: float = 50_000.0,
    risk_pct: float = 0.02,
    max_drawdown_pct: float = 0.20,
) -> tuple:
    """Convenience wrapper: run backtest from a DataFrame and attach per-period PnL."""
    df         = df.copy().sort_values(time_col).reset_index(drop=True)
    timestamps = df[time_col].values if time_col in df.columns else None

    net_pnl, metrics = run_backtest(
        signals=df[signal_col].values,
        da_prices=df[da_price_col].values,
        system_sell_price=df[sell_price_col].values,
        system_buy_price=df[buy_price_col].values,
        timestamps=timestamps,
        cost_per_trade=cost_per_trade,
        starting_capital=starting_capital,
        risk_pct=risk_pct,
        max_drawdown_pct=max_drawdown_pct,
    )

    df["pnl"] = net_pnl
    return df, metrics
