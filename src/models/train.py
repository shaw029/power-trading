import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error
import logging
import os

from src.utils.config import FEATURES_DATASET

logger = logging.getLogger(__name__)

# Pre-auction features — all known by 11:00 AM on Day-1 before the EPEX auction.
# No Day-1 settlement data (system_buy/sell, niv, demand_actual) is included here.
_FEATURE_COLS = [
    "wind_fc_da_d1_10h30",  # wind auction fundamental
    "demand_fc_da_d1_10h30",  # demand auction fundamental
    "auction_residual_load",  # demand_da - wind_da (computed in build_features)
    "wind_auction_drift",  # wind_da_10h30 - wind_da_07h (momentum)
    "day_ahead_price_lag48",  # DA price 24 h ago (last complete day)
    "day_ahead_price_lag96",  # DA price 48 h ago
    "system_sell_price_lag48",  # imbalance sell price 24 h ago
    "system_sell_price_lag96",  # imbalance sell price 48 h ago
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
]

# Penalty buffer: 7 days × 48 half-hours = 336 periods; 48-h lag = 96 periods
_PENALTY_WINDOW = 336
_PENALTY_LAG = 96


def train_model(
    features_path: str | None = None,
    model_type: str = "xgboost",
) -> tuple:
    """Train a model to predict target_pnl_long = system_sell_price - day_ahead_price.

    Returns:
        (model, X_test, y_test, predictions, penalty_buffer_test)

        y_test           — actual spread (£/MWh) for the test set
        predictions      — predicted spread (£/MWh)
        penalty_buffer   — rolling imbalance cost used by generate_signal
    """
    logger.info("Starting model training — target: system_sell_price − day_ahead_price")

    if features_path is None:
        features_path = str(FEATURES_DATASET)

    if not os.path.exists(features_path):
        raise FileNotFoundError(f"Features file not found: {features_path}")

    df = pd.read_parquet(features_path)
    df = df.sort_values("time").reset_index(drop=True)
    logger.info("Loaded %d rows, %s → %s", len(df), df["time"].min(), df["time"].max())

    # ------------------------------------------------------------------
    # Target
    # ------------------------------------------------------------------
    if "system_sell_price" not in df.columns or "day_ahead_price" not in df.columns:
        raise ValueError("Features dataset must contain system_sell_price and day_ahead_price")

    df["target_pnl_long"] = df["system_sell_price"] - df["day_ahead_price"]

    # ------------------------------------------------------------------
    # Penalty buffer (computed from full series before the train/test split
    # to ensure the rolling window uses all available history)
    # ------------------------------------------------------------------
    if "system_buy_price" in df.columns:
        imbalance_spread = df["system_buy_price"] - df["system_sell_price"]
        df["_penalty_buffer"] = (
            imbalance_spread.shift(_PENALTY_LAG).rolling(_PENALTY_WINDOW, min_periods=48).mean()
        )
    else:
        logger.warning("system_buy_price not found — penalty buffer will be zero")
        df["_penalty_buffer"] = 0.0

    # ------------------------------------------------------------------
    # Feature selection
    # ------------------------------------------------------------------
    features = [c for c in _FEATURE_COLS if c in df.columns]
    missing = [c for c in _FEATURE_COLS if c not in df.columns]
    if missing:
        logger.warning("Missing feature columns (skipped): %s", missing)
    logger.info("Using %d features: %s", len(features), features)

    # Drop rows where target or any feature is NaN, then keep a full-column
    # view (df_valid) so we can extract raw prices for the backtest.
    valid = ~(df[features].isna().any(axis=1) | df["target_pnl_long"].isna())
    df_valid = df[valid].reset_index(drop=True)
    X = df_valid[features]
    y = df_valid["target_pnl_long"]
    penalty = df_valid["_penalty_buffer"]
    logger.info("After NaN drop: %d rows remain (dropped %d)", len(df_valid), (~valid).sum())

    # ------------------------------------------------------------------
    # Time-based 80/20 split — no shuffling
    # ------------------------------------------------------------------
    split = int(len(df_valid) * 0.8)
    X_train, X_test = X.iloc[:split].reset_index(drop=True), X.iloc[split:].reset_index(drop=True)
    y_train, y_test = y.iloc[:split].reset_index(drop=True), y.iloc[split:].reset_index(drop=True)
    penalty_test = penalty.iloc[split:].reset_index(drop=True)

    # Raw price series and timestamps for the test window — needed by the backtest engine.
    _test = df_valid.iloc[split:].reset_index(drop=True)
    test_refs = {
        "timestamps": _test["time"].values if "time" in _test.columns else None,
        "da_prices": (
            _test["day_ahead_price"].values if "day_ahead_price" in _test.columns else None
        ),
        "system_sell_price": _test["system_sell_price"].values,
        "system_buy_price": (
            _test["system_buy_price"].values
            if "system_buy_price" in _test.columns
            else np.zeros(len(y_test))
        ),
    }

    logger.info("Train: %d rows | Test: %d rows", len(X_train), len(X_test))

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------
    if model_type == "xgboost":
        try:
            from xgboost import XGBRegressor

            model = XGBRegressor(
                n_estimators=300,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                n_jobs=-1,
                verbosity=0,
            )
        except ImportError:
            logger.warning("XGBoost not available, falling back to RandomForest")
            model_type = "random_forest"

    if model_type == "random_forest":
        from sklearn.ensemble import RandomForestRegressor

        model = RandomForestRegressor(
            n_estimators=200,
            max_depth=8,
            random_state=42,
            n_jobs=-1,
        )

    logger.info("Training %s", model_type)
    model.fit(X_train, y_train)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)
    rmse = np.sqrt(mean_squared_error(y_test, predictions))
    logger.info("Spread prediction — MAE: %.2f £/MWh | RMSE: %.2f £/MWh", mae, rmse)

    if hasattr(model, "feature_importances_"):
        importances = sorted(zip(features, model.feature_importances_), key=lambda x: -x[1])
        logger.info("Top-5 features: %s", importances[:5])

    return model, X_test, y_test, predictions, penalty_test, test_refs
