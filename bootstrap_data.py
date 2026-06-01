"""Download 3 days of sample data from all configured sources."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from dotenv import load_dotenv

load_dotenv()

end_date = date.today()
start_date = end_date - timedelta(days=3)
os.environ["START_DATE"] = str(start_date)
os.environ["END_DATE"] = str(end_date)

from src.utils.config import ensure_directories  # noqa: E402
from src.data.download import (  # noqa: E402
    fetch_demand_forecast,
    fetch_wind_forecast,
    fetch_generation_actual,
    fetch_day_ahead_price,
    fetch_market_index_price,
    fetch_demand_actual,
    fetch_imbalance_price,
    fetch_neso_ndfd,
)

ensure_directories()

FETCHERS: list[tuple[str, Callable[..., "pd.DataFrame"]]] = [
    ("demand_forecast", fetch_demand_forecast),
    ("wind_forecast", fetch_wind_forecast),
    ("generation_actual", fetch_generation_actual),
    ("day_ahead_price", fetch_day_ahead_price),
    ("market_index_price", fetch_market_index_price),
    ("demand_actual", fetch_demand_actual),
    ("imbalance_price", fetch_imbalance_price),
    ("neso_ndfd", fetch_neso_ndfd),
]

if __name__ == "__main__":
    print(f"Bootstrapping data for {start_date} to {end_date} ...")
    for name, fetch_fn in FETCHERS:
        try:
            df = fetch_fn()
            print(f"  {name}: {len(df)} rows")
        except Exception as e:
            print(f"  {name}: FAILED — {e}")
    print("Done.")
