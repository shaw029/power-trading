from __future__ import annotations

import pandas as pd
from typing import Generator


def walk_forward_split(
    df: pd.DataFrame,
    train_days: int,
    test_days: int,
    step_days: int,
) -> Generator[tuple[pd.DataFrame, pd.DataFrame], None, None]:
    """Yield (train_df, test_df) pairs in chronological order.

    Windows are defined by GB market days (Europe/London calendar).  The
    training window is train_days long; the test window immediately follows
    for test_days; then the whole window advances by step_days.

    Args:
        df:          DataFrame with a UTC-aware 'time' column, sorted ascending.
        train_days:  Number of market days in the training window.
        test_days:   Number of market days in the test window.
        step_days:   Days to advance the window each iteration.

    Yields:
        (train_df, test_df) with non-overlapping, chronologically ordered rows.
    """
    df = df.sort_values("time").reset_index(drop=True)
    market_day = (
        pd.to_datetime(df["time"], utc=True)
        .dt.tz_convert("Europe/London")
        .dt.normalize()
    )
    dates = sorted(market_day.unique())
    n_dates = len(dates)

    start = 0
    while start + train_days + test_days <= n_dates:
        train_set = set(dates[start : start + train_days])
        test_set = set(dates[start + train_days : start + train_days + test_days])
        yield (
            df[market_day.isin(train_set)].reset_index(drop=True),
            df[market_day.isin(test_set)].reset_index(drop=True),
        )
        start += step_days
