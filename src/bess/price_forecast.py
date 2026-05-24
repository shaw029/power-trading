def naive_da_forecast(price_history: list[list[float]], lookback: int = 7) -> list[float]:
    if not price_history:
        raise ValueError("Need at least one day of price history")
    window = price_history[-lookback:]
    return [
        sum(day[h] for day in window) / len(window)
        for h in range(24)
    ]
