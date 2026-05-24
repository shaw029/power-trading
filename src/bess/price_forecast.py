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
            last_day = price_history[-1]
            if not last_day:
                raise ValueError("Cannot forecast: price history contains empty days")
            forecast.append(sum(last_day) / len(last_day))
    return forecast
