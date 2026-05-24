import pytest

from src.bess.price_forecast import naive_da_forecast


class TestNaiveDaForecast:
    def test_single_day_returns_same_prices(self) -> None:
        history = [[10.0 + h for h in range(24)]]
        forecast = naive_da_forecast(history)
        assert forecast == history[0]

    def test_two_days_returns_mean(self) -> None:
        day1 = [20.0] * 24
        day2 = [40.0] * 24
        forecast = naive_da_forecast([day1, day2])
        assert all(abs(f - 30.0) < 1e-9 for f in forecast)

    def test_lookback_window_limits_history(self) -> None:
        old = [[100.0] * 24 for _ in range(10)]
        recent = [[50.0] * 24 for _ in range(7)]
        forecast = naive_da_forecast(old + recent, lookback=7)
        assert all(abs(f - 50.0) < 1e-9 for f in forecast)

    def test_returns_24_elements(self) -> None:
        history = [[float(h)] * 24 for h in range(5)]
        forecast = naive_da_forecast(history)
        assert len(forecast) == 24

    def test_empty_history_raises(self) -> None:
        with pytest.raises(ValueError):
            naive_da_forecast([])
