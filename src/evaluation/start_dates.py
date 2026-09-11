"""Select account restart windows from coverage alone, before scoring PnL."""

import pandas as pd
from src.backtest.engine import run_backtest_from_dataframe


def replay_account_window(
    frame: pd.DataFrame, start: pd.Timestamp, end_exclusive: pd.Timestamp, **kwargs
) -> tuple:
    """Rerun an empty account on the selected saved forecasts, not a rebased curve."""
    times = pd.to_datetime(frame["time"], utc=True)
    window = frame.loc[times.ge(start) & times.lt(end_exclusive)].copy()
    if window.empty:
        raise ValueError("Account window has no saved forecast observations")
    return run_backtest_from_dataframe(window, **kwargs)


def coverage_start_windows(
    times: pd.Series, requested_starts: list[str], maximum_days: int = 30
) -> tuple[int, list[dict]]:
    """First covered date in each requested month and a common contiguous horizon.

    Coverage means at least one eligible observation on each London market date,
    not a guarantee that all 48/46/50 half-hours have data. A missing requested
    month is an error rather than silently substituting a later month.
    """
    if maximum_days <= 0:
        raise ValueError("maximum_days must be positive")
    dates = pd.DatetimeIndex(pd.to_datetime(times, utc=True)).tz_convert("Europe/London")
    dates = dates.normalize().unique().sort_values()
    covered = set(dates)
    windows = []
    for requested in requested_starts:
        requested_day = pd.Timestamp(requested).tz_localize("Europe/London")
        month_end = requested_day + pd.offsets.MonthBegin(1)
        eligible = dates[(dates >= requested_day) & (dates < month_end)]
        if eligible.empty:
            raise ValueError(f"No covered start in requested month {requested}")
        start = eligible[0]
        contiguous = 0
        while contiguous < maximum_days and start + pd.DateOffset(days=contiguous) in covered:
            contiguous += 1
        windows.append(
            {
                "requested_start": requested,
                "actual_start": start,
                "contiguous_days_up_to_cap": contiguous,
            }
        )
    if not windows:
        raise ValueError("At least one start is required")
    horizon = min(w["contiguous_days_up_to_cap"] for w in windows)
    for window in windows:
        window["equal_end_exclusive"] = window["actual_start"] + pd.DateOffset(days=horizon)
    return horizon, windows
