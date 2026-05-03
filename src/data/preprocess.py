"""Preprocessing functions for UK electricity market data.

All functions return a DataFrame with a UTC 30-minute DatetimeIndex named 'time'.
Column naming conventions:
  gen_{FUEL}          generation mix by fuel type  (FUELHH)
  system_buy_price    system buy price             (B1770)
  system_sell_price   system sell price            (B1770)
  niv                 net imbalance volume         (B1770)
  mid_price           market index price, APXMIDP  (MID)
  demand_actual       system demand outturn        (ITSDO)
  wind_fc_rel_{N}h    wind rolling snapshots       (WINDFOR, 24/12/6/3/1h before delivery)
  wind_fc_da_*        wind auction snapshots       (WINDFOR, d-2 noon / d-1 00h/07h/10h30)
  day_ahead_price     day-ahead auction price      (ENTSOE, expanded)
  demand_fc_rel_{N}h  demand rolling snapshots     (NESO NDFD, 24/12/6/3/1h before delivery)
  demand_fc_da_*      demand auction snapshots     (NESO NDFD, d-2 noon / d-1 00h/07h/10h30)
"""

import pandas as pd
import logging

from src.utils.config import PROCESSED_DATA_DIR

logger = logging.getLogger(__name__)

_30MIN = "30min"


def _utc_index(series: pd.Series) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(series, utc=True))
    idx.name = "time"
    return idx


# ---------------------------------------------------------------------------
# 30-min native datasets (settlement-period aligned, use startTime directly)
# ---------------------------------------------------------------------------


def process_imbalance_price(df: pd.DataFrame) -> pd.DataFrame:
    """B1770 → system_buy_price, system_sell_price, niv (30-min native)."""
    df = df.copy()
    df.index = _utc_index(df["startTime"])
    df = df.rename(
        columns={
            "systemBuyPrice": "system_buy_price",
            "systemSellPrice": "system_sell_price",
            "netImbalanceVolume": "niv",
        }
    )
    cols = [c for c in ["system_buy_price", "system_sell_price", "niv"] if c in df.columns]
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[cols].sort_index()
    df = df[~df.index.duplicated(keep="first")]
    logger.info("Imbalance price processed. Shape: %s", df.shape)
    return df


def process_generation_mix(df: pd.DataFrame) -> pd.DataFrame:
    """FUELHH → gen_{FUEL} columns via pivot on fuelType (30-min native)."""
    df = df.copy()
    df["_time"] = pd.to_datetime(df["startTime"], utc=True)
    df = df[df["_time"].notna()]
    df["generation"] = pd.to_numeric(df["generation"], errors="coerce")

    pivoted = df.pivot_table(index="_time", columns="fuelType", values="generation", aggfunc="mean")
    pivoted.index.name = "time"
    pivoted.columns = [f"gen_{c}" for c in pivoted.columns]
    pivoted = pivoted.sort_index()
    pivoted = pivoted[~pivoted.index.duplicated(keep="first")]
    logger.info(
        "Generation mix processed. Shape: %s, fuels: %s", pivoted.shape, list(pivoted.columns)
    )
    return pivoted


def process_market_index_price(df: pd.DataFrame) -> pd.DataFrame:
    """MID → mid_price, APXMIDP provider only (30-min native)."""
    df = df.copy()
    df = df[df["dataProvider"] == "APXMIDP"].copy()
    df.index = _utc_index(df["startTime"])
    df["mid_price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df[["mid_price"]].sort_index()
    df = df[~df.index.duplicated(keep="first")]
    logger.info("Market index price (APXMIDP) processed. Shape: %s", df.shape)
    return df


def process_demand_actual(df: pd.DataFrame) -> pd.DataFrame:
    """ITSDO → demand_actual (30-min native)."""
    df = df.copy()
    df.index = _utc_index(df["startTime"])
    df["demand_actual"] = pd.to_numeric(df["demand"], errors="coerce")
    df = df[["demand_actual"]].sort_index()
    df = df[~df.index.duplicated(keep="first")]
    logger.info("Demand actual processed. Shape: %s", df.shape)
    return df


# ---------------------------------------------------------------------------
# Hourly datasets — upsample / expand to 30-min
# ---------------------------------------------------------------------------

_ROLLING_SNAPSHOTS: dict[str, pd.Timedelta] = {
    "fc_rel_24h": pd.Timedelta("24h"),
    "fc_rel_12h": pd.Timedelta("12h"),
    "fc_rel_6h": pd.Timedelta("6h"),
    "fc_rel_3h": pd.Timedelta("3h"),
    "fc_rel_1h": pd.Timedelta("1h"),
}

# Days before delivery-market-date, clock time in Europe/London
_STATIC_SNAPSHOTS: dict[str, tuple[int, pd.Timedelta]] = {
    "fc_da_d2_noon": (2, pd.Timedelta(hours=12)),
    "fc_da_d1_00h": (1, pd.Timedelta(hours=0)),
    "fc_da_d1_07h": (1, pd.Timedelta(hours=7)),
    "fc_da_d1_10h30": (1, pd.Timedelta(hours=10, minutes=30)),
}


def _build_rolling_snapshots(
    df: pd.DataFrame,
    delivery_col: str,
    publish_col: str,
    value_col: str,
    prefix: str,
) -> pd.DataFrame:
    """Latest forecast N hours before each delivery period (rolling lead times)."""
    frames: list[pd.DataFrame] = []
    for suffix, lag in _ROLLING_SNAPSHOTS.items():
        eligible = df[df[publish_col] <= df[delivery_col] - lag]
        if eligible.empty:
            continue
        snap = (
            eligible.sort_values([delivery_col, publish_col])
            .groupby(delivery_col, as_index=False)
            .last()[[delivery_col, value_col]]
            .rename(columns={delivery_col: "time", value_col: f"{prefix}_{suffix}"})
            .set_index("time")
        )
        frames.append(snap)

    if not frames:
        return pd.DataFrame()

    result = frames[0]
    for frame in frames[1:]:
        result = result.join(frame, how="outer")
    return result


def _build_static_snapshots(
    df: pd.DataFrame,
    delivery_col: str,
    publish_col: str,
    value_col: str,
    prefix: str,
) -> pd.DataFrame:
    """Latest forecast available at fixed pre-auction clock times (Europe/London).

    For delivery period T on market date D (Europe/London midnight boundary),
    the cutoff for each snapshot is: midnight(D, London) - days_back + time_of_day.
    Arithmetic is done in UTC so DST transitions are handled correctly.
    """
    df = df.copy()
    market_midnight_utc = (
        df[delivery_col].dt.tz_convert("Europe/London").dt.normalize().dt.tz_convert("UTC")
    )

    frames: list[pd.DataFrame] = []
    for suffix, (days_back, tod) in _STATIC_SNAPSHOTS.items():
        df["_cutoff"] = market_midnight_utc - pd.Timedelta(days=days_back) + tod
        eligible = df[df[publish_col] <= df["_cutoff"]]
        if eligible.empty:
            continue
        snap = (
            eligible.sort_values([delivery_col, publish_col])
            .groupby(delivery_col, as_index=False)
            .last()[[delivery_col, value_col]]
            .rename(columns={delivery_col: "time", value_col: f"{prefix}_{suffix}"})
            .set_index("time")
        )
        frames.append(snap)

    if not frames:
        return pd.DataFrame()

    result = frames[0]
    for frame in frames[1:]:
        result = result.join(frame, how="outer")
    return result


def process_wind_forecast(df: pd.DataFrame) -> pd.DataFrame:
    """WINDFOR → rolling (fc_rel_*) + static auction (fc_da_*) snapshot columns, 30-min.

    Rolling: latest forecast 1/3/6/12/24 h before each delivery period.
    Static:  latest forecast at d-2 noon, d-1 00h/07h/10h30 (Europe/London).
    """
    df = df.copy()
    df["_time"] = pd.to_datetime(df["startTime"], utc=True)
    df["_pub"] = pd.to_datetime(df["publishTime"], utc=True)
    df = df[df["_time"].notna() & df["_pub"].notna()]
    df["_gen"] = pd.to_numeric(df["generation"], errors="coerce")

    rolling = _build_rolling_snapshots(df, "_time", "_pub", "_gen", "wind")
    static = _build_static_snapshots(df, "_time", "_pub", "_gen", "wind")

    if rolling.empty and static.empty:
        logger.warning("Wind forecast: no snapshot data produced")
        return pd.DataFrame()

    if rolling.empty:
        result = static
    elif static.empty:
        result = rolling
    else:
        result = rolling.join(static, how="outer")

    result.index.name = "time"
    result = result.sort_index().resample(_30MIN).ffill()
    logger.info("Wind forecast processed (30-min snapshots). Shape: %s", result.shape)
    return result


def process_day_ahead_price(df: pd.DataFrame) -> pd.DataFrame:
    """ENTSOE → day_ahead_price expanded from hourly to 30-min.

    Each hourly price maps to both the :00 and :30 settlement periods.
    """
    df = df.copy()
    df["_time"] = pd.to_datetime(df["time"], utc=True)
    df = df[df["_time"].notna()]
    df["day_ahead_price"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.set_index("_time")[["day_ahead_price"]]
    df.index.name = "time"
    df = df[~df.index.duplicated(keep="first")].sort_index()

    # Hourly → 30-min
    df = df.resample(_30MIN).ffill()
    logger.info("Day-ahead price processed (30-min). Shape: %s", df.shape)
    return df


def process_demand_forecast(df: pd.DataFrame) -> pd.DataFrame:
    """NESO NDFD → rolling (fc_rel_*) + static auction (fc_da_*) snapshot columns, 30-min.

    Rolling: latest forecast 1/3/6/12/24 h before each delivery period.
    Static:  latest forecast at d-2 noon, d-1 00h/07h/10h30 (Europe/London).
    """
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["forecast_time"] = pd.to_datetime(df["forecast_time"], utc=True)
    df = df[df["time"].notna() & df["forecast_time"].notna()]
    df["_value"] = pd.to_numeric(df["value"], errors="coerce")

    rolling = _build_rolling_snapshots(df, "time", "forecast_time", "_value", "demand")
    static = _build_static_snapshots(df, "time", "forecast_time", "_value", "demand")

    if rolling.empty and static.empty:
        logger.warning("Demand forecast: no snapshot data produced")
        return pd.DataFrame()

    if rolling.empty:
        result = static
    elif static.empty:
        result = rolling
    else:
        result = rolling.join(static, how="outer")

    result.index.name = "time"
    result = result.sort_index().resample(_30MIN).ffill()
    logger.info("Demand forecast processed (30-min snapshots). Shape: %s", result.shape)
    return result


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge_all(
    generation_mix: pd.DataFrame,
    imbalance_price: pd.DataFrame,
    day_ahead_price: pd.DataFrame,
    market_index_price: pd.DataFrame | None = None,
    demand_actual: pd.DataFrame | None = None,
    wind_forecast: pd.DataFrame | None = None,
    demand_forecast: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Outer join all processed datasets on their UTC 30-min time index.

    Required datasets are positional; optional datasets are keyword-only so
    the pipeline can omit any that failed to download.
    """
    logger.info("Merging all datasets")

    named = {
        "generation_mix": generation_mix,
        "imbalance_price": imbalance_price,
        "day_ahead_price": day_ahead_price,
        "market_index_price": market_index_price,
        "demand_actual": demand_actual,
        "wind_forecast": wind_forecast,
        "demand_forecast": demand_forecast,
    }

    merged = None
    for name, df in named.items():
        if df is None or df.empty:
            logger.warning("Skipping empty dataset: %s", name)
            continue
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(f"{name} must have a DatetimeIndex")
        merged = df if merged is None else merged.join(df, how="outer")

    if merged is None:
        raise ValueError("No data to merge")

    merged = merged.sort_index()
    if merged.index.duplicated().any():
        logger.warning("Removing %d duplicate timestamps", merged.index.duplicated().sum())
        merged = merged[~merged.index.duplicated(keep="first")]

    # --- QA pass ---------------------------------------------------------------

    # 1. Forward-fill day_ahead_price before the mandatory null drop.
    #    process_day_ahead_price already resamples to 30-min, but alignment
    #    gaps from the outer join can leave isolated NaNs.
    if "day_ahead_price" in merged.columns:
        merged["day_ahead_price"] = merged["day_ahead_price"].ffill()

    # 2. Ensure a gapless 30-min UTC grid; forward-fill any structural holes.
    expected_idx = pd.date_range(
        start=merged.index.min(),
        end=merged.index.max(),
        freq=_30MIN,
        tz="UTC",
        name="time",
    )
    n_gaps = len(expected_idx) - len(merged)
    if n_gaps > 0:
        logger.warning("Time index has %d missing 30-min slots — forward-filling", n_gaps)
        merged = merged.reindex(expected_idx).ffill()
    else:
        logger.info("Time index complete: no 30-min gaps detected")

    # 3. Drop rows where day_ahead_price is still null (boundary periods with
    #    no price data at all — these cannot be used as training targets).
    if "day_ahead_price" in merged.columns:
        before = len(merged)
        merged = merged.dropna(subset=["day_ahead_price"])
        dropped = before - len(merged)
        if dropped:
            logger.info("Dropped %d rows with missing day_ahead_price", dropped)

    # 4. Verify _da_ snapshot coverage per market day.
    #    Each static-auction column should have at least one non-null value per
    #    day (the vintage is constant per day by construction in _build_static_snapshots).
    da_cols = [c for c in merged.columns if "_fc_da_" in c]
    if da_cols:
        market_dates = merged.index.tz_convert("Europe/London").normalize()
        days_with_any = merged[da_cols].notna().any(axis=1).groupby(market_dates).any()
        n_missing = int((~days_with_any).sum())
        total_days = int(days_with_any.size)
        if n_missing:
            logger.warning("_da_ snapshots absent for %d of %d market days", n_missing, total_days)
        else:
            logger.info(
                "_da_ snapshot columns verified: all %d market days have coverage (%s)",
                total_days,
                da_cols,
            )

    # 5. Add total_gen_actual (MW) — sum of all gen_ fuel columns.
    #    min_count=1 keeps the result NaN if every fuel column is NaN for that period.
    gen_cols = sorted(c for c in merged.columns if c.startswith("gen_"))
    if gen_cols:
        merged["total_gen_actual"] = merged[gen_cols].sum(axis=1, min_count=1)
        logger.info(
            "total_gen_actual (MW) computed from %d fuel columns: %s",
            len(gen_cols),
            gen_cols,
        )

    # ---------------------------------------------------------------------------

    merged.index.name = "time"
    merged = merged.reset_index()
    logger.info(
        "Merge complete. Shape: %s, range: %s to %s",
        merged.shape,
        merged["time"].min(),
        merged["time"].max(),
    )
    merged.to_parquet(PROCESSED_DATA_DIR / "processed_data.parquet", index=False)
    return merged
