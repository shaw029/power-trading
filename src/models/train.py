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


def _fit_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    model_type: str = "xgboost",
    model_params: dict | None = None,
):
    """Build and fit a model. Returns the fitted estimator."""
    p = model_params or {}
    if model_type == "xgboost":
        try:
            from xgboost import XGBRegressor

            model = XGBRegressor(
                n_estimators=p.get("n_estimators", 300),
                max_depth=p.get("max_depth", 5),
                learning_rate=p.get("learning_rate", 0.05),
                subsample=p.get("subsample", 0.8),
                colsample_bytree=p.get("colsample_bytree", 0.8),
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

    if model_type == "linear_regression":
        from sklearn.linear_model import LinearRegression

        model = LinearRegression()

    logger.info("Training %s on %d rows", model_type, len(X_train))
    model.fit(X_train, y_train)
    return model


def _make_predictions_df(
    test_df: pd.DataFrame,
    y_test: pd.Series,
    predictions: np.ndarray,
    actual_col: str = "actual_spread",
    predicted_col: str = "predicted_spread",
) -> pd.DataFrame:
    result = {
        "time": test_df["time"] if "time" in test_df.columns else pd.RangeIndex(len(y_test)),
        actual_col: y_test.values,
        predicted_col: predictions,
    }
    for col in ("day_ahead_price", "mid_price", "system_sell_price", "system_buy_price"):
        if col in test_df.columns:
            result[col] = test_df[col].ffill().values if col == "mid_price" else test_df[col].values
    return pd.DataFrame(result)


def train_with_validation(
    df: pd.DataFrame,
    features: list[str],
    target_col: str,
    validation_type: str = "static",
    model_type: str = "xgboost",
    model_params: dict | None = None,
    wf_train_days: int = 200,
    wf_test_days: int = 30,
    wf_step_days: int = 30,
    actual_col: str = "actual_spread",
    predicted_col: str = "predicted_spread",
) -> tuple:
    """Split df, fit model(s), and return out-of-sample predictions.

    Args:
        df:             NaN-free DataFrame with features, target, and price columns.
        features:       Feature column names.
        target_col:     Target column name.
        validation_type: "static" (80/20 day-based split) or "walk_forward".
        model_type:     "xgboost" or "random_forest".
        wf_train_days:  Walk-forward training window in market days.
        wf_test_days:   Walk-forward test window in market days.
        wf_step_days:   Days to advance each fold.

    Returns:
        (predictions_df, model, X_test)

        predictions_df — all out-of-sample rows with columns:
                         time, actual_spread, predicted_spread,
                         day_ahead_price, system_sell_price, system_buy_price
        model          — last fitted estimator
        X_test         — last test feature matrix (for metadata / feature importance)
    """
    if validation_type == "static":
        market_day = (
            pd.to_datetime(df["time"], utc=True)
            .dt.tz_convert("Europe/London")
            .dt.normalize()
        )
        dates = sorted(market_day.unique())
        split_idx = int(len(dates) * 0.8)
        train_dates = set(dates[:split_idx])
        test_dates = set(dates[split_idx:])

        train_df = df[market_day.isin(train_dates)].reset_index(drop=True)
        test_df = df[market_day.isin(test_dates)].reset_index(drop=True)

        logger.info(
            "Static split — train: %d rows (%d days) | test: %d rows (%d days)",
            len(train_df), len(train_dates), len(test_df), len(test_dates),
        )

        model = _fit_model(train_df[features], train_df[target_col], model_type, model_params)
        predictions = model.predict(test_df[features])
        return (
            _make_predictions_df(test_df, test_df[target_col], predictions, actual_col, predicted_col),
            model,
            test_df[features],
        )

    elif validation_type == "walk_forward":
        from src.evaluation.splitter import walk_forward_split

        folds: list[pd.DataFrame] = []
        model = None
        X_test_last = None

        for fold_idx, (train_df, test_df) in enumerate(
            walk_forward_split(df, wf_train_days, wf_test_days, wf_step_days)
        ):
            X_train = train_df[features]
            y_train = train_df[target_col]
            X_test = test_df[features]
            y_test = test_df[target_col]

            model = _fit_model(X_train, y_train, model_type, model_params)
            predictions = model.predict(X_test)

            fold_mae = mean_absolute_error(y_test, predictions)
            logger.info(
                "Fold %d — train: %d rows | test: %d rows | MAE: %.2f £/MWh",
                fold_idx + 1, len(train_df), len(test_df), fold_mae,
            )

            folds.append(_make_predictions_df(test_df, y_test, predictions, actual_col, predicted_col))
            X_test_last = X_test

        if not folds:
            raise ValueError(
                f"walk_forward_split produced no folds — "
                f"wf_train_days={wf_train_days} + wf_test_days={wf_test_days} "
                f"exceeds the available date range"
            )

        logger.info("Walk-forward complete: %d folds", len(folds))
        predictions_df = (
            pd.concat(folds, ignore_index=True)
            .sort_values("time")
            .reset_index(drop=True)
        )
        return predictions_df, model, X_test_last

    else:
        raise ValueError(
            f"Unknown validation_type {validation_type!r}. Use 'static' or 'walk_forward'."
        )


def train_model(
    features_path: str | None = None,
    model_type: str = "xgboost",
    model_params: dict | None = None,
    validation_type: str = "static",
    wf_train_days: int = 200,
    wf_test_days: int = 30,
    wf_step_days: int = 30,
) -> tuple:
    """Load features, prepare data, and run train_with_validation.

    Returns:
        (model, predictions_df, X_test)

        predictions_df — DataFrame with columns:
                         time, actual_spread, predicted_spread,
                         day_ahead_price, system_sell_price, system_buy_price
        X_test         — last test feature matrix (for metadata / feature importance)
    """
    logger.info(
        "Starting model training — target: system_sell_price − day_ahead_price [%s]",
        validation_type,
    )

    if features_path is None:
        features_path = str(FEATURES_DATASET)

    if not os.path.exists(features_path):
        raise FileNotFoundError(f"Features file not found: {features_path}")

    df = pd.read_parquet(features_path)
    df = df.sort_values("time").reset_index(drop=True)
    logger.info("Loaded %d rows, %s → %s", len(df), df["time"].min(), df["time"].max())

    if "system_sell_price" not in df.columns or "day_ahead_price" not in df.columns:
        raise ValueError("Features dataset must contain system_sell_price and day_ahead_price")

    df["target_pnl_long"] = df["system_sell_price"] - df["day_ahead_price"]

    features = [c for c in _FEATURE_COLS if c in df.columns]
    missing = [c for c in _FEATURE_COLS if c not in df.columns]
    if missing:
        logger.warning("Missing feature columns (skipped): %s", missing)
    logger.info("Using %d features: %s", len(features), features)

    valid = ~(df[features].isna().any(axis=1) | df["target_pnl_long"].isna())
    df_valid = df[valid].reset_index(drop=True)
    logger.info("After NaN drop: %d rows remain (dropped %d)", len(df_valid), (~valid).sum())

    predictions_df, model, X_test = train_with_validation(
        df=df_valid,
        features=features,
        target_col="target_pnl_long",
        validation_type=validation_type,
        model_type=model_type,
        model_params=model_params,
        wf_train_days=wf_train_days,
        wf_test_days=wf_test_days,
        wf_step_days=wf_step_days,
    )

    mae = mean_absolute_error(predictions_df["actual_spread"], predictions_df["predicted_spread"])
    rmse = np.sqrt(mean_squared_error(predictions_df["actual_spread"], predictions_df["predicted_spread"]))
    logger.info("Overall — MAE: %.2f £/MWh | RMSE: %.2f £/MWh", mae, rmse)

    if hasattr(model, "feature_importances_"):
        importances = sorted(zip(features, model.feature_importances_), key=lambda x: -x[1])
        logger.info("Top-5 features: %s", importances[:5])

    return model, predictions_df, X_test


def train_da_price_model(
    features_path: str | None = None,
    model_type: str = "xgboost",
    model_params: dict | None = None,
    validation_type: str = "walk_forward",
    wf_train_days: int = 200,
    wf_test_days: int = 30,
    wf_step_days: int = 30,
) -> tuple:
    """Train an ML model to predict day-ahead prices from pre-auction features.

    Returns:
        (model, predictions_df, X_test)

        predictions_df — out-of-sample rows with columns:
                         time, actual_da_price, predicted_da_price,
                         plus any auxiliary price columns present in the dataset.
        model          — last fitted estimator
        X_test         — last test feature matrix
    """
    logger.info(
        "Starting DA price model training — target: day_ahead_price [%s]",
        validation_type,
    )

    if features_path is None:
        features_path = str(FEATURES_DATASET)

    if not os.path.exists(features_path):
        raise FileNotFoundError(f"Features file not found: {features_path}")

    df = pd.read_parquet(features_path)
    df = df.sort_values("time").reset_index(drop=True)
    logger.info("Loaded %d rows, %s → %s", len(df), df["time"].min(), df["time"].max())

    if "day_ahead_price" not in df.columns:
        raise ValueError("Features dataset must contain day_ahead_price")

    features = [c for c in _FEATURE_COLS if c in df.columns]
    missing = [c for c in _FEATURE_COLS if c not in df.columns]
    if missing:
        logger.warning("Missing feature columns (skipped): %s", missing)
    logger.info("Using %d features: %s", len(features), features)

    valid = ~(df[features].isna().any(axis=1) | df["day_ahead_price"].isna())
    df_valid = df[valid].reset_index(drop=True)
    logger.info("After NaN drop: %d rows remain (dropped %d)", len(df_valid), (~valid).sum())

    predictions_df, model, X_test = train_with_validation(
        df=df_valid,
        features=features,
        target_col="day_ahead_price",
        validation_type=validation_type,
        model_type=model_type,
        model_params=model_params,
        wf_train_days=wf_train_days,
        wf_test_days=wf_test_days,
        wf_step_days=wf_step_days,
        actual_col="actual_da_price",
        predicted_col="predicted_da_price",
    )

    mae = mean_absolute_error(predictions_df["actual_da_price"], predictions_df["predicted_da_price"])
    rmse = np.sqrt(mean_squared_error(predictions_df["actual_da_price"], predictions_df["predicted_da_price"]))
    logger.info("DA price model — MAE: %.2f £/MWh | RMSE: %.2f £/MWh", mae, rmse)

    if hasattr(model, "feature_importances_"):
        importances = sorted(zip(features, model.feature_importances_), key=lambda x: -x[1])
        logger.info("Top-5 features: %s", importances[:5])

    return model, predictions_df, X_test
