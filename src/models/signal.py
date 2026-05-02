import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def generate_signal(
    predicted_spread: np.ndarray,
    penalty_buffer: np.ndarray,
    threshold: float = 5.0,
) -> np.ndarray:
    """Generate day-ahead auction signals from a predicted imbalance spread.

    A signal fires only when the predicted edge exceeds the expected cost of
    imbalance settlement (the penalty buffer) by at least `threshold` £/MWh.
    This prevents entries where the spread is unlikely to cover round-trip costs.

    Args:
        predicted_spread:  Predicted (SSP − DA price) per settlement period, £/MWh.
        penalty_buffer:    Rolling 7-day mean of (SBP − SSP), lagged 48 h (£/MWh).
                           NaNs are treated as zero (no penalty assumed).
        threshold:         Minimum edge above the penalty buffer required to fire,
                           £/MWh.  Default 5.0.

    Returns:
        Integer array: 1 = BUY (Long DA), −1 = SELL (Short DA), 0 = NEUTRAL.

    Signal rules:
        BUY  if predicted_spread  >  clip(penalty_buffer, 0) + threshold
        SELL if predicted_spread  < −(clip(penalty_buffer, 0) + threshold)
    """
    predicted_spread = np.asarray(predicted_spread, dtype=float)
    penalty          = np.nan_to_num(np.asarray(penalty_buffer, dtype=float), nan=0.0)

    if len(predicted_spread) != len(penalty):
        raise ValueError(
            f"predicted_spread length {len(predicted_spread)} ≠ "
            f"penalty_buffer length {len(penalty)}"
        )

    adjusted = np.clip(penalty, 0.0, None) + threshold

    signals = np.zeros(len(predicted_spread), dtype=int)
    signals[predicted_spread >  adjusted] =  1
    signals[predicted_spread < -adjusted] = -1

    n_long    = int((signals ==  1).sum())
    n_short   = int((signals == -1).sum())
    n_neutral = int((signals ==  0).sum())
    total     = len(signals)
    logger.info(
        "Raw signals — LONG: %d (%.1f%%)  SHORT: %d (%.1f%%)  NEUTRAL: %d (%.1f%%)",
        n_long,    n_long    / total * 100,
        n_short,   n_short   / total * 100,
        n_neutral, n_neutral / total * 100,
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
    signals          = np.asarray(signals, dtype=int)
    ts               = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))

    df = pd.DataFrame({
        "time":             ts,
        "market_date":      ts.tz_convert("Europe/London").normalize(),
        "predicted_spread": predicted_spread,
        "signal":           signals,
        "abs_spread":       np.abs(predicted_spread),
    })

    # Rank within each (day, direction) group — keep top_n per direction per day
    filtered = np.zeros(len(df), dtype=int)
    for direction in (1, -1):
        mask   = df["signal"] == direction
        active = df[mask].copy()
        if active.empty:
            continue
        active["rank"] = (
            active
            .groupby("market_date")["abs_spread"]
            .rank(ascending=False, method="first")
        )
        top_idx = active[active["rank"] <= top_n].index
        filtered[top_idx] = direction

    # Build human-readable schedule
    kept     = df.copy()
    kept["final_signal"] = filtered
    schedule = (
        kept[kept["final_signal"] != 0]
        [["market_date", "time", "predicted_spread", "final_signal"]]
        .copy()
    )
    schedule["direction"] = schedule["final_signal"].map({1: "BUY", -1: "SELL"})
    schedule = schedule.drop(columns="final_signal").sort_values(
        ["market_date", "predicted_spread"],
        ascending=[True, False],
    )

    n_retained = int((filtered != 0).sum())
    n_raw      = int((signals != 0).sum())
    logger.info(
        "Daily schedule (top-%d per direction): %d → %d active signals retained",
        top_n, n_raw, n_retained,
    )

    return schedule, filtered


def generate_signal_from_dataframe(
    df: pd.DataFrame,
    pred_col:    str   = "predicted_spread",
    penalty_col: str   = "penalty_buffer",
    threshold:   float = 5.0,
) -> pd.DataFrame:
    """Convenience wrapper: generate signals from a DataFrame and attach as a column."""
    if pred_col not in df.columns:
        raise KeyError(f"Column '{pred_col}' not found in DataFrame")

    penalty = df[penalty_col].values if penalty_col in df.columns else np.zeros(len(df))

    df = df.copy()
    df["signal"] = generate_signal(
        predicted_spread=df[pred_col].values,
        penalty_buffer=penalty,
        threshold=threshold,
    )
    return df
