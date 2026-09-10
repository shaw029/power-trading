"""Recent raw feeds are provisional and expire even if the day-file exists."""

import datetime as dt
import os
import time


def cache_is_fresh(path, day, ttl_seconds: int = 900, provisional_days: int = 5) -> bool:
    if not os.path.exists(path):
        return False
    if isinstance(day, str):
        day = dt.datetime.strptime(day.replace("-", ""), "%Y%m%d").date()
    elif isinstance(day, dt.datetime):
        day = day.date()
    age = (dt.datetime.now(dt.timezone.utc).date() - day).days
    return age > provisional_days or time.time() - os.path.getmtime(path) < ttl_seconds
