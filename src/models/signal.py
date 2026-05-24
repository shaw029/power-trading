import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# 7-day rolling window (48 half-hours × 7) with a 48-h lag
_PENALTY_WINDOW = 336
_PENALTY_LAG = 96

# Volatility window matches penalty buffer to keep the two estimates in sync
_VOL_WINDOW = 336
_VOL_LAG = 96


def compute_penalty_buffer(
    system_buy_price: np.ndarray | pd.Series,
    system_sell_price: np.ndarray | pd.Series,
) -> np.ndarray:
    """Rolling 7-day mean of (SBP − SSP), lagged 48 h.

    Estimates the expected round-trip imbalance cost for use as a dynamic
    signal threshold.  Pass the full price series (not just the test window)
    so the rolling window is correctly warmed up from training history.
    """
    buy = pd.Series(np.asarray(system_buy_price, dtype=float))
    sell = pd.Series(np.asarray(system_sell_price, dtype=float))
    return (  # type: ignore[no-any-return]
        (buy - sell)
        .shift(_PENALTY_LAG)
        .rolling(_PENALTY_WINDOW, min_periods=48)
        .mean()
        .values
    )


def compute_volatility_threshold(
    system_buy_price: np.ndarray | pd.Series,
    system_sell_price: np.ndarray | pd.Series,
    window: int = _VOL_WINDOW,
    lag: int = _VOL_LAG,
) -> np.ndarray:
    """Rolling std of the imbalance spread (SBP − SSP), lagged to avoid lookahead.

    Calibrates the signal gate to the recent spread distribution — widening
    the band in volatile regimes so only genuinely exceptional predicted
    edges pass through.  Pass the full price series (training + test) so the
    window is warmed up before the test period begins.

    Args:
        system_buy_price:  SBP series, £/MWh.
        system_sell_price: SSP series, £/MWh.
        window:            Rolling std lookback in half-hour periods (default 336 = 7 days).
        lag:               Shift applied before rolling to prevent lookahead
                           (default 96 = 48 h).

    Returns:
        Float array, same length as inputs.  NaN where the window is not yet
        warmed up.
    """
    buy = pd.Series(np.asarray(system_buy_price, dtype=float))
    sell = pd.Series(np.asarray(system_sell_price, dtype=float))
    return (  # type: ignore[no-any-return]
        (buy - sell)
        .shift(lag)
        .rolling(window, min_periods=48)
        .std()
        .values
    )


def generate_signal(
    predicted_spread: np.ndarray,
    penalty_buffer: np.ndarray,
    threshold: float = 5.0,
    vol_threshold: np.ndarray | None = None,
    vol_multiplier: float = 1.0,
) -> np.ndarray:
    """Generate day-ahead auction signals from a predicted imbalance spread.

    A signal fires only when the predicted edge exceeds the expected cost of
    imbalance settlement (the penalty buffer) plus a volatility-adjusted gate.
    This prevents entries where the spread is unlikely to cover round-trip costs
    and suppresses noise-driven signals in high-volatility regimes.

    Args:
        predicted_spread:  Predicted (SSP − DA price) per settlement period, £/MWh.
        penalty_buffer:    Rolling 7-day mean of (SBP − SSP), lagged 48 h (£/MWh).
                           NaNs are treated as zero (no penalty assumed).
        threshold:         Minimum edge floor, £/MWh.  Acts as a lower bound on
                           the gate regardless of volatility.  Default 5.0.
        vol_threshold:     Rolling std of (SBP − SSP), lagged 48 h (£/MWh), from
                           compute_volatility_threshold().  When supplied, the gate
                           widens with market volatility.  NaNs treated as 0.
        vol_multiplier:    Number of spread std-devs required to fire.  Scales
                           vol_threshold before comparing against `threshold`.
                           Effective gate = max(threshold, vol_multiplier × vol).

    Returns:
        Integer array: 1 = BUY (Long DA), −1 = SELL (Short DA), 0 = NEUTRAL.

    Signal rules:
        gate = clip(penalty_buffer, 0) + max(threshold, vol_multiplier × vol_threshold)
        BUY  if predicted_spread  >  gate
        SELL if predicted_spread  < −gate
    """
    predicted_spread = np.asarray(predicted_spread, dtype=float)
    penalty = np.nan_to_num(np.asarray(penalty_buffer, dtype=float), nan=0.0)

    if len(predicted_spread) != len(penalty):
        raise ValueError(
            f"predicted_spread length {len(predicted_spread)} ≠ "
            f"penalty_buffer length {len(penalty)}"
        )

    if vol_threshold is not None:
        vol = np.nan_to_num(np.asarray(vol_threshold, dtype=float), nan=0.0)
        if len(vol) != len(predicted_spread):
            raise ValueError(
                f"vol_threshold length {len(vol)} ≠ "
                f"predicted_spread length {len(predicted_spread)}"
            )
        dynamic_gate = np.maximum(threshold, vol_multiplier * vol)
    else:
        dynamic_gate = np.full(len(predicted_spread), threshold)

    adjusted = np.clip(penalty, 0.0, None) + dynamic_gate

    signals = np.zeros(len(predicted_spread), dtype=int)
    signals[predicted_spread > adjusted] = 1
    signals[predicted_spread < -adjusted] = -1

    n_long = int((signals == 1).sum())
    n_short = int((signals == -1).sum())
    n_neutral = int((signals == 0).sum())
    total = len(signals)
    logger.info(
        "Raw signals — LONG: %d (%.1f%%)  SHORT: %d (%.1f%%)  NEUTRAL: %d (%.1f%%)",
        n_long,
        n_long / total * 100,
        n_short,
        n_short / total * 100,
        n_neutral,
        n_neutral / total * 100,
    )

    return signals


def build_daily_schedule(
    predicted_spread: np.ndarray,
    signals: np.ndarray,
    timestamps: np.ndarray,
    top_n: int = 5,
) -> tuple:
    """Filter signals to the top-N highest-conviction opportunities per market day.

    Only the `top_n` periods with the largest |predicted_spread| among active
    (non-zero) signals are retained each day.  All other signals are zeroed out.
    This reflects a realistic bidding schedule — a non-asset trader picks a
    small number of high-conviction slots rather than participating in every period.

    Args:
        predicted_spread:  Predicted spread array aligned with signals/timestamps.
        signals:           Raw signal array from generate_signal.
        timestamps:        UTC timestamps aligned with the arrays.
        top_n:             Maximum active trades per market day per direction.
                           E.g. top_n=5 → up to 5 Buys AND 5 Sells per day.

    Returns:
        (schedule_df, filtered_signals)

        schedule_df      — one row per retained trade, columns:
                           market_date, time, direction, predicted_spread
        filtered_signals — signal array with non-top-N entries zeroed out
    """
    predicted_spread = np.asarray(predicted_spread, dtype=float)
    signals = np.asarray(signals, dtype=int)
    ts = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))

    df = pd.DataFrame(
        {
            "time": ts,
            "market_date": ts.tz_convert("Europe/London").normalize(),
            "predicted_spread": predicted_spread,
            "signal": signals,
            "abs_spread": np.abs(predicted_spread),
        }
    )

    # Rank within each (day, direction) group — keep top_n per direction per day
    filtered = np.zeros(len(df), dtype=int)
    for direction in (1, -1):
        mask = df["signal"] == direction
        active = df[mask].copy()
        if active.empty:
            continue
        active["rank"] = active.groupby("market_date")["abs_spread"].rank(
            ascending=False, method="first"
        )
        top_idx = active[active["rank"] <= top_n].index
        filtered[top_idx] = direction

    # Build human-readable schedule
    kept = df.copy()
    kept["final_signal"] = filtered
    schedule = kept[kept["final_signal"] != 0][
        ["market_date", "time", "predicted_spread", "final_signal"]
    ].copy()
    schedule["direction"] = schedule["final_signal"].map({1: "BUY", -1: "SELL"})
    schedule = schedule.drop(columns="final_signal").sort_values(
        ["market_date", "predicted_spread"],
        ascending=[True, False],
    )

    n_retained = int((filtered != 0).sum())
    n_raw = int((signals != 0).sum())
    logger.info(
        "Daily schedule (top-%d per direction): %d → %d active signals retained",
        top_n,
        n_raw,
        n_retained,
    )

    return schedule, filtered


def generate_signal_from_dataframe(
    df: pd.DataFrame,
    pred_col: str = "predicted_spread",
    penalty_col: str = "penalty_buffer",
    vol_col: str = "vol_threshold",
    timestamp_col: str = "time",
    threshold: float = 5.0,
    vol_multiplier: float = 1.0,
    top_n: int | None = None,
) -> pd.DataFrame:
    """Convenience wrapper: generate signals from a DataFrame and attach as a column.

    When `top_n` is set and `timestamp_col` is present, conviction ranking is
    applied via build_daily_schedule so that only the top-N highest-|predicted_spread|
    signals per direction per market day are retained — matching the behaviour of
    the main pipeline.  Without `top_n` (or without timestamps), raw
    threshold-gated signals are returned.

    Args:
        df:            Input DataFrame.
        pred_col:      Column name for predicted spread values.
        penalty_col:   Column name for penalty buffer (optional).
        vol_col:       Column name for volatility threshold (optional).
        timestamp_col: Column name for UTC timestamps, used by top-N ranking.
        threshold:     Static threshold floor, £/MWh.
        vol_multiplier: Scales the volatility-adjusted gate.
        top_n:         Max active trades per direction per day.  Pass None to
                       skip conviction ranking and return all gated signals.
    """
    if pred_col not in df.columns:
        raise KeyError(f"Column '{pred_col}' not found in DataFrame")

    penalty = df[penalty_col].values if penalty_col in df.columns else np.zeros(len(df))
    vol = df[vol_col].values if vol_col in df.columns else None

    df = df.copy()
    raw_signals = generate_signal(
        predicted_spread=df[pred_col].values,
        penalty_buffer=penalty,
        threshold=threshold,
        vol_threshold=vol,
        vol_multiplier=vol_multiplier,
    )

    if top_n is not None and timestamp_col in df.columns:
        _, df["signal"] = build_daily_schedule(
            predicted_spread=df[pred_col].values,
            signals=raw_signals,
            timestamps=df[timestamp_col].values,
            top_n=top_n,
        )
    else:
        df["signal"] = raw_signals

    return df
