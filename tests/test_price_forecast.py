import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from src.bess.price_forecast import ml_da_forecast


class TestMlDaForecast:
    def test_returns_list_of_predictions(self) -> None:
        model = MagicMock()
        model.predict.return_value = np.array([10.0, 20.0, 30.0])
        features = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        result = ml_da_forecast(model, features)
        assert result == [10.0, 20.0, 30.0]

    def test_calls_model_predict(self) -> None:
        model = MagicMock()
        model.predict.return_value = np.array([5.0])
        features = pd.DataFrame({"x": [42]})
        ml_da_forecast(model, features)
        model.predict.assert_called_once()

    def test_returns_24_elements_for_24_rows(self) -> None:
        model = MagicMock()
        model.predict.return_value = np.arange(24, dtype=float)
        features = pd.DataFrame({"col": range(24)})
        result = ml_da_forecast(model, features)
        assert len(result) == 24

    def test_empty_features_returns_empty(self) -> None:
        model = MagicMock()
        model.predict.return_value = np.array([])
        features = pd.DataFrame({"a": pd.Series([], dtype=float)})
        result = ml_da_forecast(model, features)
        assert result == []

    def test_preserves_prediction_values(self) -> None:
        model = MagicMock()
        expected = [42.5, -3.0, 100.1]
        model.predict.return_value = np.array(expected)
        features = pd.DataFrame({"f1": [1, 2, 3]})
        result = ml_da_forecast(model, features)
        assert result == pytest.approx(expected)
