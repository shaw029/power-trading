def naive_da_forecast(price_history: list[list[float]], lookback: int = 7, n_hours: int = 24) -> list[float]:
    if not price_history:
        raise ValueError("Need at least one day of price history")
    window = price_history[-lookback:]
    forecast = []
    for h in range(n_hours):
        values = [day[h] for day in window if h < len(day)]
        if values:
            forecast.append(sum(values) / len(values))
        else:
            forecast.append(forecast[-1] if forecast else 0.0)
    return forecast
