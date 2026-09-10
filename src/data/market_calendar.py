"""Shared London market-day grids and strict native-period aggregation."""

import pandas as pd


def market_day_grid(day, freq: str = "1h") -> pd.DatetimeIndex:
    date = pd.Timestamp(day).date()
    start = pd.Timestamp(date).tz_localize("Europe/London")
    end = (pd.Timestamp(date) + pd.Timedelta(days=1)).tz_localize("Europe/London")
    return pd.date_range(start, end, freq=freq, inclusive="left").tz_convert("UTC")


def complete_resample(values, freq: str = "1h", native_freq: str = "30min"):
    """Average only complete native bins; one missing half-hour invalidates an hour."""
    values = values.copy()
    values.index = pd.DatetimeIndex(pd.to_datetime(values.index, utc=True))
    if values.index.has_duplicates:
        raise ValueError("Duplicate source timestamps cannot establish complete coverage")
    if values.empty:
        return values
    if not (values.index == values.index.floor(native_freq)).all():
        raise ValueError("Source timestamps must align to the native grid")
    ratio = pd.Timedelta(freq) / pd.Timedelta(native_freq)
    if ratio < 1 or ratio != int(ratio):
        raise ValueError("Output frequency must be an integer multiple of native frequency")
    result = values.resample(freq).mean()
    return result.where(values.resample(freq).count() == int(ratio))


def complete_market_days(values, freq: str = "1h") -> dict:
    """Return indexed complete days; callers must join forecasts by timestamp."""
    result = {}
    for day, group in values.groupby(values.index.tz_convert("Europe/London").date):
        expected = market_day_grid(day, freq)
        group = group.reindex(expected)
        if not group.isna().any().any():
            result[day] = group
    return result
