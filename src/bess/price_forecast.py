import pandas as pd


def ml_da_forecast(model, features: pd.DataFrame) -> list[float]:
    """Forecast day-ahead prices using a trained ML model.

    Args:
        model: Trained estimator with a .predict() method.
        features: DataFrame of pre-auction feature columns for the target
                  settlement periods (one row per period).

    Returns:
        Predicted day-ahead prices, one per row in features.
    """
    return model.predict(features).tolist()  # type: ignore[no-any-return]
