"""Matched-volume payoff attribution for static intraday hedges.

This is an execution research ledger, not an account simulator. Every admitted
signal has the same MWh quantity; costs follow the engine's entry-volume fee and
intraday-volume crossing-cost convention. One shared price mask keeps every
hedge on identical observations, including the two endpoint controls.
"""

import math

import numpy as np
import pandas as pd

PRICE_COLUMNS = [
    "day_ahead_price",
    "system_sell_price",
    "system_buy_price",
    "mid_price",
]


def fixed_volume_hedges(
    frame: pd.DataFrame,
    hedge_ratios: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0),
    quantity_mwh: float = 1.0,
    fee_per_mwh: float = 1.0,
    crossing_per_mwh: float = 2.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return a half-hour ledger and daily PnL (columns are hedge fractions).

    Dates use Europe/London. Missing-price rows carry no admitted quantity;
    dates with no complete price observations remain NaN, not zero-PnL days.
    Partially priced days contain matched-observation subtotals. Missing dates
    are never invented. Negative electricity prices are valid observations.
    """
    if not np.isfinite(quantity_mwh) or quantity_mwh <= 0:
        raise ValueError("quantity_mwh must be finite and positive")
    if any(not np.isfinite(c) or c < 0 for c in (fee_per_mwh, crossing_per_mwh)):
        raise ValueError("Costs must be finite and nonnegative")
    if not hedge_ratios or len(set(hedge_ratios)) != len(hedge_ratios):
        raise ValueError("Provide distinct hedge ratios")
    if any(not np.isfinite(h) or not 0 <= h <= 1 for h in hedge_ratios):
        raise ValueError("Hedge ratios must lie in [0, 1]")
    if frame.empty:
        raise ValueError("No forecast observations")
    ledger = frame.copy()
    ledger["time"] = pd.to_datetime(ledger["time"], utc=True, errors="raise")
    if ledger["time"].isna().any() or ledger["time"].duplicated().any():
        raise ValueError("Delivery timestamps must be present and unique")
    if not ledger["signal"].isin([-1, 0, 1]).all():
        raise ValueError("Signals must be -1, 0, or 1")
    ledger = ledger.sort_values("time").reset_index(drop=True)
    ledger["market_date"] = ledger["time"].dt.tz_convert("Europe/London").dt.normalize()
    ledger["eligible"] = np.isfinite(ledger[PRICE_COLUMNS].to_numpy(dtype=float)).all(axis=1)
    active = ledger["eligible"] & ledger["signal"].ne(0)
    ledger["entry_mwh"] = active.astype(float) * quantity_mwh
    da, sell, buy, mid = (ledger[c] for c in PRICE_COLUMNS)
    ledger["imbalance_gross"] = np.where(
        active, np.where(ledger["signal"].eq(1), sell - da, da - buy) * quantity_mwh, 0.0
    )
    ledger["intraday_gross"] = np.where(active, ledger["signal"] * (mid - da) * quantity_mwh, 0.0)
    ledger["entry_fee"] = ledger["entry_mwh"] * fee_per_mwh
    daily = pd.DataFrame(index=sorted(ledger["market_date"].unique()))
    daily.index.name = "market_date"
    priced_days = ledger.groupby("market_date")["eligible"].any()
    for h in hedge_ratios:
        name = f"pnl_{h:g}"
        ledger[name] = (
            (1 - h) * ledger["imbalance_gross"]
            + h * ledger["intraday_gross"]
            - ledger["entry_fee"]
            - h * ledger["entry_mwh"] * crossing_per_mwh
        )
        daily[h] = ledger.groupby("market_date")[name].sum().where(priced_days)
    return ledger, daily


def summarise_hedges(daily: pd.DataFrame) -> pd.DataFrame:
    """Cash metrics on priced forecast days; tail mean uses ceil(5% * n).

    Drawdowns include an initial zero-PnL high-water mark and are measured on
    daily research payoffs, not intraday marked positions or account returns.
    """
    rows = []
    for h in daily.columns:
        pnl = daily[h].dropna()
        if len(pnl) < 2:
            raise ValueError("At least two priced dates are needed for daily risk metrics")
        cumulative = pnl.cumsum()
        drawdown = cumulative - cumulative.cummax().clip(lower=0)
        tail_n = max(1, math.ceil(0.05 * len(pnl)))
        rows.append(
            {
                "hedge_ratio": h,
                "priced_days": len(pnl),
                "net_pnl": pnl.sum(),
                "daily_volatility": pnl.std(ddof=1),
                "worst_day": pnl.min(),
                "tail_mean_5pct": pnl.nsmallest(tail_n).mean(),
                "tail_days": tail_n,
                "max_drawdown": drawdown.min(),
                "residual_imbalance_share": 1 - h,
            }
        )
    return pd.DataFrame(rows).set_index("hedge_ratio")
