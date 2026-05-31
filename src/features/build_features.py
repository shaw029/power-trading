import pandas as pd
import numpy as np
import logging
from pathlib import Path

from src.utils.config import VERSIONED_FEATURES_DIR

logger = logging.getLogger(__name__)

_AUCTION_WIND = "wind_fc_da_d1_10h30"
_AUCTION_DEMAND = "demand_fc_da_d1_10h30"
_MORNING_WIND = "wind_fc_da_d1_07h"


def build_features(df: pd.DataFrame, save_path: Path | str | None = None) -> pd.DataFrame:
    """Build feature engineering layer for electricity price forecasting.

    All features use only information available before the 11:00 AM EPEX auction.
    Target variable: day_ahead_price.

    Args:
        df:        Preprocessed merged DataFrame.
        save_path: Where to write features.parquet.  Defaults to the global
                   FEATURES_DIR / features.parquet from config.
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
    for col in ["day_ahead_price", "system_sell_price", "system_buy_price"]:
        if col in df.columns:
            df[f"{col}_lag48"] = df[col].shift(48)
            df[f"{col}_lag96"] = df[col].shift(96)

    # Imbalance spread (SBP − SSP): the cost of being caught short/long in
    # settlement.  Lagged separately because the spread dynamics differ from
    # either leg alone — it is also the quantity the signal gate is calibrated
    # against, so the model should see its own history.
    if "system_buy_price" in df.columns and "system_sell_price" in df.columns:
        spread = df["system_buy_price"] - df["system_sell_price"]
        df["imbalance_spread_lag48"] = spread.shift(48)
        df["imbalance_spread_lag96"] = spread.shift(96)

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
    # Save
    # -------------------------------------------------------------------------
    output_path = Path(save_path) if save_path is not None else VERSIONED_FEATURES_DIR / "features.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)

    logger.info("Features saved to %s, shape: %s", output_path, df.shape)
    return df
