import pandas as pd
import numpy as np
import logging
import os

from src.utils.config import FEATURES_DIR

logger = logging.getLogger(__name__)

_AUCTION_WIND   = "wind_fc_da_d1_10h30"
_AUCTION_DEMAND = "demand_fc_da_d1_10h30"
_MORNING_WIND   = "wind_fc_da_d1_07h"


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build feature engineering layer for electricity price forecasting.

    All features use only information available before the 11:00 AM EPEX auction.
    Target variable: day_ahead_price.
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
    # Historical Lags (48 periods = 24 h, 96 periods = 48 h at 30-min resolution)
    # -------------------------------------------------------------------------
    for col in ["day_ahead_price", "system_sell_price"]:
        if col in df.columns:
            df[f"{col}_lag48"] = df[col].shift(48)
            df[f"{col}_lag96"] = df[col].shift(96)

    # -------------------------------------------------------------------------
    # Temporal Features — Europe/London for GB market calendar alignment.
    # Fractional hour (0.0–23.5) gives distinct sin/cos for :00 and :30 periods.
    # -------------------------------------------------------------------------
    local_time = df["time"].dt.tz_convert("Europe/London")
    hour = local_time.dt.hour + local_time.dt.minute / 60
    dow  = local_time.dt.dayofweek

    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    df["dow_sin"]  = np.sin(2 * np.pi * dow  / 7)
    df["dow_cos"]  = np.cos(2 * np.pi * dow  / 7)

    # -------------------------------------------------------------------------
    # Save
    # -------------------------------------------------------------------------
    output_dir = FEATURES_DIR
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "features_dataset.parquet")
    df.to_parquet(output_path, index=False)

    logger.info("Features saved to %s, shape: %s", output_path, df.shape)
    return df
