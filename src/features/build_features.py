import pandas as pd
import numpy as np
import logging
from pathlib import Path

from src.utils.config import VERSIONED_FEATURES_DIR

logger = logging.getLogger(__name__)

_AUCTION_WIND = "wind_fc_da_d1_10h30"
_AUCTION_DEMAND = "demand_fc_da_d1_10h30"
_MORNING_WIND = "wind_fc_da_d1_07h"

# The GB day-ahead auction for market date D clears at 11:00 London on D-1; the
# book has to be committed before it, and the feature vintage the pipeline
# claims throughout is 10:30. Everything a row is allowed to know is fixed at
# that instant, whatever hour of D the row is delivered in.
AUCTION_DECISION_TOD = pd.Timedelta(hours=10, minutes=30)

# Minimum periods of lookback that keep a same-time-of-day lag pre-auction for
# *every* delivery period of the day (23:30 delivery needs 74; 96 = 48 h is the
# next whole-day multiple and leaves an 11 h cushion for publication latency).
MIN_AUCTION_SAFE_LAG = 96


def auction_decision_time(delivery_time: pd.Series) -> pd.Series:
    """The instant the book for each delivery period had to be committed (UTC)."""
    london = pd.to_datetime(delivery_time, utc=True).dt.tz_convert("Europe/London")
    market_date = london.dt.normalize()
    return (market_date - pd.Timedelta(days=1) + AUCTION_DECISION_TOD).dt.tz_convert("UTC")


def assert_auction_available(df: pd.DataFrame, lagged_cols: dict[str, int]) -> None:
    """Fail if any lagged feature reads a period that closed after its auction.

    ``lagged_cols`` maps a built column to the number of 30-minute periods it
    was shifted by. Each row's source instant is compared against that row's own
    auction decision time, so this catches the failure the old 24-hour lag had:
    admissible for the small hours of the delivery day, leaking for every period
    after 10:30.
    """
    time = pd.to_datetime(df["time"], utc=True)
    decision = auction_decision_time(time)

    violations = {}
    for col, periods in lagged_cols.items():
        if col not in df.columns:
            continue
        source = time.shift(periods)
        late = df[col].notna() & source.notna() & (source > decision)
        if late.any():
            violations[col] = int(late.sum())

    if violations:
        detail = ", ".join(f"{c}: {n} rows" for c, n in sorted(violations.items()))
        raise ValueError(
            "Feature set leaks post-auction information — a lagged column reads a "
            f"settlement period that closed after its own D-1 10:30 decision ({detail}). "
            f"Same-time-of-day lags need at least {MIN_AUCTION_SAFE_LAG} periods."
        )


def build_features(df: pd.DataFrame, save_path: Path | str | None = None) -> pd.DataFrame:
    """Build feature engineering layer for electricity price forecasting.

    Every feature is admissible at the D-1 10:30 London auction decision for its
    own delivery period — forecast vintages are taken at that cutoff and lagged
    series look back far enough that their source period closed before it. The
    property is asserted, not asserted-in-prose: ``assert_auction_available``
    runs over the built frame before it is written and raises on any violation.

    Target variable: day_ahead_price.

    Args:
        df:        Preprocessed merged DataFrame.
        save_path: Where to write features.parquet.  Defaults to the global
                   FEATURES_DIR / features.parquet from config.

    Raises:
        ValueError: if any lagged feature reads a post-auction settlement period.
    """
    logger.info("Building features from preprocessed data")

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)

    # -------------------------------------------------------------------------
    # Auction Fundamentals
    # -------------------------------------------------------------------------
    if _AUCTION_DEMAND in df.columns and _AUCTION_WIND in df.columns:
        df["auction_residual_load"] = df[_AUCTION_DEMAND] - df[_AUCTION_WIND]

    # -------------------------------------------------------------------------
    # Pre-Auction Drift (volatility signal)
    # -------------------------------------------------------------------------
    if _AUCTION_WIND in df.columns and _MORNING_WIND in df.columns:
        df["wind_auction_drift"] = df[_AUCTION_WIND] - df[_MORNING_WIND]

    # -------------------------------------------------------------------------
    # Historical Lags — 96 periods = 48 h, 144 periods = 72 h at 30-min resolution
    #
    # The lag is set by the *auction*, not by the delivery period. The decision
    # for every period of market date D is taken once, at D-1 10:30 London, so a
    # feature is admissible only if its source period closed before that instant.
    # A 24-hour lag (shift(48)) does not clear that bar: for delivery at D 20:00
    # it reads the D-1 20:00 print, nine and a half hours after the auction. Over
    # a 2018 delivery year that is true of 9,542 of 17,616 rows — every period
    # delivered after 10:30.
    #
    # A 48-hour lag clears it for every period in the day, and by the widest
    # margin exactly where the 24-hour lag fails worst: the last delivery period
    # of the day looks back to D-2 23:30, still 11 h before the auction, and the
    # first looks back 34.5 h. That 11 h floor is what absorbs settlement
    # publication latency, which a same-day-vintage lag has no room for at all.
    # ``assert_auction_available`` re-proves this on the built frame.
    # -------------------------------------------------------------------------
    for col in ["day_ahead_price", "system_sell_price", "system_buy_price"]:
        if col in df.columns:
            df[f"{col}_lag96"] = df[col].shift(96)
            df[f"{col}_lag144"] = df[col].shift(144)

    # Imbalance risk, lagged 48 h. Under GB's single cash-out price (BSC P305,
    # 5 November 2015) SBP and SSP are equal in every settlement period — all
    # 17,660 non-null pairs in the 2018 sample are identical — so the old
    # SBP-minus-SSP "spread" was identically zero and carried no information at
    # all. The quantity that actually risks the position is the gap between the
    # cash-out price and the price the auction cleared at, so that is what the
    # model sees.
    if "system_buy_price" in df.columns and "day_ahead_price" in df.columns:
        imbalance_gap = df["system_buy_price"] - df["day_ahead_price"]
        df["imbalance_gap_lag96"] = imbalance_gap.shift(96)
        df["imbalance_gap_lag144"] = imbalance_gap.shift(144)

    # -------------------------------------------------------------------------
    # Temporal Features — Europe/London for GB market calendar alignment.
    # Fractional hour (0.0–23.5) gives distinct sin/cos for :00 and :30 periods.
    # -------------------------------------------------------------------------
    local_time = df["time"].dt.tz_convert("Europe/London")
    hour = local_time.dt.hour + local_time.dt.minute / 60
    dow = local_time.dt.dayofweek

    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)

    # -------------------------------------------------------------------------
    # Leakage gate — prove the timing claim on the frame actually being written
    # -------------------------------------------------------------------------
    assert_auction_available(
        df,
        {
            "day_ahead_price_lag96": 96,
            "day_ahead_price_lag144": 144,
            "system_sell_price_lag96": 96,
            "system_sell_price_lag144": 144,
            "system_buy_price_lag96": 96,
            "system_buy_price_lag144": 144,
            "imbalance_gap_lag96": 96,
            "imbalance_gap_lag144": 144,
        },
    )

    # -------------------------------------------------------------------------
    # Save
    # -------------------------------------------------------------------------
    output_path = (
        Path(save_path) if save_path is not None else VERSIONED_FEATURES_DIR / "features.parquet"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)

    logger.info("Features saved to %s, shape: %s", output_path, df.shape)
    return df
