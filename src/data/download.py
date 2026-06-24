import glob
import json
import re
import pandas as pd
import requests
import logging
import os
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
from src.utils.config import (
    START_DATE,
    END_DATE,
    ELEXON_BASE_URL,
    ELEXON_API_KEY,
    ENTSOE_BASE_URL,
    ENTSOE_API_KEY,
    NORDPOOL_DA_BASE_URL,
    NESO_BASE_URL,
    NESO_NDFD_RESOURCE_ID,
    DEFAULT_DEMAND_FORECAST_SOURCE,
    DEFAULT_WIND_FORECAST_SOURCE,
    DEFAULT_GENERATION_ACTUAL_SOURCE,
    DEFAULT_DAY_AHEAD_PRICE_SOURCE,
    DEFAULT_MARKET_INDEX_SOURCE,
    DEFAULT_DEMAND_ACTUAL_SOURCE,
    DEFAULT_IMBALANCE_PRICE_SOURCE,
    NESO_NDFD_CSV,
    WIND_FORECAST_CSV,
    GENERATION_ACTUAL_CSV,
    DAY_AHEAD_PRICE_CSV,
    MARKET_INDEX_CSV,
    DEMAND_ACTUAL_CSV,
    IMBALANCE_PRICE_CSV,
    RAW_DATA_DIR,
)

logger = logging.getLogger(__name__)

os.makedirs(RAW_DATA_DIR, exist_ok=True)

# Allow-list of known-good NESO CKAN resource IDs and a strict date pattern.
# Both are interpolated into raw datastore_search_sql strings, so they are
# validated before use to close off any SQL-injection vector.
_NESO_ALLOWED_RESOURCE_IDS = {NESO_NDFD_RESOURCE_ID}
_DATE_FILTER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_neso_query_inputs(resource_id: str, date_filter: str | None) -> None:
    """Reject any resource ID or date not on the known-good allow-list/pattern."""
    if resource_id not in _NESO_ALLOWED_RESOURCE_IDS:
        raise ValueError(f"Unknown NESO resource_id: {resource_id!r}")
    if date_filter is not None and not _DATE_FILTER_RE.match(date_filter):
        raise ValueError(f"Invalid date_filter (expected YYYY-MM-DD): {date_filter!r}")


def _save_raw_json(dataset_name: str, filename: str, payload: object) -> None:
    dataset_dir = os.path.join(RAW_DATA_DIR, dataset_name)
    os.makedirs(dataset_dir, exist_ok=True)
    raw_path = os.path.join(dataset_dir, filename)
    with open(raw_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)
    logger.info(f"Saved raw JSON to {raw_path}")


def _raw_dataset_dir(dataset: str) -> str:
    return os.path.join(RAW_DATA_DIR, dataset)


def _raw_json_path(dataset: str, date_str: str, page: int) -> str:
    return os.path.join(_raw_dataset_dir(dataset), f"{dataset}_{date_str}_page_{page}.json")


def _chunk_has_raw_files(dataset: str, date_str: str) -> bool:
    dataset_dir = _raw_dataset_dir(dataset)
    if not os.path.isdir(dataset_dir):
        return False
    return bool(glob.glob(os.path.join(dataset_dir, f"{dataset}_{date_str}_page_*.json")))


def _load_raw_records_from_file(filepath: str) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]  # type: ignore[no-any-return]
    raise ValueError(f"Invalid raw JSON file structure: {filepath}")


def download_elexon_dataset(dataset: str, start_date: str, end_date: str) -> None:
    """
    Download raw Elexon JSON for the requested date range, skipping already cached dates.
    """
    logger.info(f"Downloading Elexon {dataset} from {start_date} to {end_date}")

    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_datetime = datetime.strptime(end_date, "%Y-%m-%d")

    base = ELEXON_BASE_URL.rstrip("/")
    base_url = f"{base}/datasets/{dataset}"

    while current_date <= end_datetime:
        next_date = current_date + timedelta(days=1)
        date_str = current_date.strftime("%Y%m%d")

        if _chunk_has_raw_files(dataset, date_str):
            logger.info(f"Skipping download for {dataset} {date_str}: raw files already present")
            current_date = next_date
            continue

        if dataset in ["NDFD", "WINDFOR", "ITSDO"]:
            params = {
                "publishDateTimeFrom": current_date.strftime("%Y-%m-%dT00:00:00Z"),
                "publishDateTimeTo": next_date.strftime("%Y-%m-%dT00:00:00Z"),
                "format": "json",
            }
            logger.info(
                f"Downloading {dataset} for publish window {params['publishDateTimeFrom']} to {params['publishDateTimeTo']}"  # noqa: E501
            )
        elif dataset in ["FUELHH"]:
            settlement_date = current_date.strftime("%Y-%m-%d")
            params = {
                "settlementDateFrom": settlement_date,
                "settlementDateTo": settlement_date,
                "format": "json",
            }
            logger.info(f"Downloading {dataset} for settlement date {settlement_date}")
        elif dataset == "MID":
            params = {
                "from": current_date.strftime("%Y-%m-%dT00:00:00Z"),
                "to": next_date.strftime("%Y-%m-%dT00:00:00Z"),
                "format": "json",
            }
            logger.info(f"Downloading MID for {params['from']} to {params['to']}")
        else:
            raise ValueError(f"Unknown dataset: {dataset}")

        if ELEXON_API_KEY:
            params["apiKey"] = ELEXON_API_KEY

        url: str | None = base_url
        page = 1
        while url:
            request_params = params if url == base_url else None
            response = requests.get(
                url, params=request_params, headers={"Accept": "application/json"}, timeout=30
            )
            response.raise_for_status()
            payload = response.json()

            raw_path = _raw_json_path(dataset, date_str, page)
            _save_raw_json(dataset, os.path.basename(raw_path), payload)

            if isinstance(payload, dict) and "data" in payload:
                records = payload["data"]
                logger.info(f"  {dataset} {date_str} Page {page}: {len(records)} records")
            else:
                logger.warning(f"Unexpected response structure for {dataset} on {date_str}")
                records = []

            next_url = payload.get("next") if isinstance(payload, dict) else None
            if next_url:
                if next_url.startswith("/"):
                    url = f"{base}{next_url}"
                else:
                    url = next_url
            else:
                url = None
            page += 1

        current_date = next_date


def read_elexon_dataset(dataset: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Read cached Elexon dataset JSON files and normalize them into a DataFrame.
    """
    dataset_dir = _raw_dataset_dir(dataset)
    if not os.path.isdir(dataset_dir):
        raise ValueError(f"No cached files found for dataset {dataset}")

    files = sorted(glob.glob(os.path.join(dataset_dir, f"{dataset}_*_page_*.json")))
    if not files:
        raise ValueError(f"No cached raw files found for dataset {dataset}")

    all_records = []
    for filepath in files:
        all_records.extend(_load_raw_records_from_file(filepath))

    if not all_records:
        raise ValueError(f"No records found in cached files for dataset {dataset}")

    df = pd.json_normalize(all_records, sep="_")

    start_dt = pd.to_datetime(start_date, utc=True)
    end_dt = pd.to_datetime(end_date, utc=True) + timedelta(days=1)
    if "startTime" in df.columns:
        df["time"] = pd.to_datetime(df["startTime"], utc=True, errors="coerce")
        df = df[df["time"].notna()]
        df = df[(df["time"] >= start_dt) & (df["time"] < end_dt)]
        df = df.drop(columns=["time"])

    return df


def fetch_elexon_dataset(dataset: str, start_date: str, end_date: str) -> pd.DataFrame:
    download_elexon_dataset(dataset, start_date, end_date)
    return read_elexon_dataset(dataset, start_date, end_date)


def download_neso_ndfd_daily(start_date: str, end_date: str) -> None:
    """
    Download raw NESO NDFD (day-ahead demand forecast) JSON using daily chunking.
    Follows the same pattern as download_elexon_dataset.
    """
    logger.info(f"Downloading NESO NDFD from {start_date} to {end_date}")

    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_datetime = datetime.strptime(end_date, "%Y-%m-%d")

    while current_date <= end_datetime:
        date_str = current_date.strftime("%Y%m%d")
        date_iso = current_date.strftime("%Y-%m-%d")

        if _chunk_has_raw_files("NESO_NDFD", date_str):
            logger.info(f"Skipping NESO_NDFD {date_iso} (already exists)")
            current_date += timedelta(days=1)
            continue

        logger.info(f"Fetching NESO_NDFD {date_iso}")

        _validate_neso_query_inputs(NESO_NDFD_RESOURCE_ID, date_iso)

        try:
            all_records = []
            offset = 0
            limit = 50000
            page = 1

            while True:
                query = f'SELECT * FROM "{NESO_NDFD_RESOURCE_ID}" WHERE "TARGETDATE" = \'{date_iso}\' ORDER BY "_id" LIMIT {limit} OFFSET {offset}'  # noqa: E501
                params = {"sql": query}
                response = requests.get(NESO_BASE_URL, params=params, timeout=60)
                response.raise_for_status()

                data = response.json()

                if not data.get("success"):
                    raise ValueError(f"NESO API error: {data.get('error', 'Unknown error')}")

                records = data.get("result", {}).get("records", [])

                if not records:
                    break

                page_payload = {"result": {"records": records}}
                page_filename = f"NESO_NDFD_{date_str}_page_{page}.json"
                _save_raw_json("NESO_NDFD", page_filename, page_payload)

                logger.info(f"NESO_NDFD {date_iso} Page {page}: {len(records)} records")

                all_records.extend(records)
                offset += limit
                page += 1

            if all_records:
                logger.info(f"Completed NESO_NDFD {date_iso}")
            else:
                logger.warning(f"No records found for NESO_NDFD {date_iso}")

        except Exception as e:
            logger.error(f"Error downloading NESO_NDFD {date_iso}: {e}")

        current_date += timedelta(days=1)


def read_neso_ndfd() -> pd.DataFrame:
    """
    Read cached NESO NDFD JSON files and combine into DataFrame.
    Expects files at: data/raw/NESO_NDFD/NESO_NDFD_YYYYMMDD_page_*.json
    """
    dataset_dir = _raw_dataset_dir("NESO_NDFD")
    if not os.path.isdir(dataset_dir):
        raise ValueError("No cached files found for NESO_NDFD")

    files = sorted(glob.glob(os.path.join(dataset_dir, "NESO_NDFD_*_page_*.json")))
    if not files:
        raise ValueError("No cached raw files found for NESO_NDFD")

    all_records = []
    for filepath in files:
        with open(filepath, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
        records = payload.get("result", {}).get("records", [])
        all_records.extend(records)

    if not all_records:
        raise ValueError("No records found in cached NESO_NDFD files")

    return pd.DataFrame(all_records)


def fetch_neso_sql(resource_id: str, date_filter: str | None = None) -> pd.DataFrame:
    """
    Fetch data from NESO CKAN DataStore API using SQL query with pagination.
    """
    logger.info(f"Fetching NESO resource {resource_id}")

    _validate_neso_query_inputs(resource_id, date_filter)

    all_records: list[dict] = []
    offset = 0
    limit = 50000

    while True:
        if date_filter:
            query = f'SELECT * FROM "{resource_id}" WHERE "TARGETDATE" = \'{date_filter}\' ORDER BY "_id" LIMIT {limit} OFFSET {offset}'  # noqa: E501
        else:
            query = f'SELECT * FROM "{resource_id}" ORDER BY "_id" LIMIT {limit} OFFSET {offset}'

        params = {"sql": query}
        response = requests.get(NESO_BASE_URL, params=params, timeout=60)
        response.raise_for_status()

        data = response.json()

        if not data.get("success"):
            raise ValueError(f"NESO API error: {data.get('error', 'Unknown error')}")

        records = data.get("result", {}).get("records", [])

        if not records:
            logger.info(f"Fetched {len(all_records)} total records from NESO")
            break

        all_records.extend(records)
        logger.info(f"NESO pagination: offset={offset}, got {len(records)} records")
        offset += limit

    return pd.DataFrame(all_records)


def _normalize_neso_ndfd(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize NESO NDFD (day-ahead demand forecast) data.
    """
    df = df.copy()

    col_lower = {col.lower(): col for col in df.columns}

    if "forecastdemand" in col_lower:
        df["value"] = pd.to_numeric(df[col_lower["forecastdemand"]], errors="coerce")
    else:
        raise ValueError(f"forecastdemand column not found. Available: {df.columns.tolist()}")

    time_col = None
    for name in ["deliverytime", "starttime", "time", "cp_st_time", "targetdate"]:
        if name in col_lower:
            time_col = col_lower[name]
            break

    if not time_col:
        raise ValueError(f"No delivery/start time column found. Available: {df.columns.tolist()}")

    df["time"] = pd.to_datetime(df[time_col], utc=True, errors="coerce")

    forecast_col = None
    for name in ["publishtime", "forecasttime", "publishedtime"]:
        if name in col_lower:
            forecast_col = col_lower[name]
            break

    if forecast_col:
        df["forecast_time"] = pd.to_datetime(df[forecast_col], utc=True, errors="coerce")
    else:
        logger.warning(
            "No forecast/publish time column found. Falling back to using delivery time."
        )
        df["forecast_time"] = df["time"]

    df = df[df["time"].notna()]
    df = df[df["forecast_time"].notna()]
    df = df.sort_values(["time", "forecast_time"])
    df = df.drop_duplicates(subset=["time", "forecast_time", "value"])

    output_cols = ["time", "forecast_time", "value"]
    optional_mappings = {
        "cardinalpoint": "cardinal_point",
        "cp_type": "cp_type",
        "cp_st_time": "block_start",
        "cp_end_time": "block_end",
    }
    for input_name_lower, output_name in optional_mappings.items():
        if input_name_lower in col_lower:
            df[output_name] = df[col_lower[input_name_lower]]
            output_cols.append(output_name)

    return df[output_cols]


def fetch_neso_ndfd(start_date: str = START_DATE, end_date: str = END_DATE) -> pd.DataFrame:
    """
    Fetch NESO day-ahead demand forecast using daily chunking.
    """
    logger.info("Fetching NESO NDFD via daily chunking")

    download_neso_ndfd_daily(start_date, end_date)
    df = read_neso_ndfd()
    logger.info(f"Read {len(df)} rows from NESO NDFD cache")

    for col in df.columns:
        if col.lower() == "forecastdemand":
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = _normalize_neso_ndfd(df)
    logger.info(f"Normalized NESO NDFD: {len(df)} records")
    return df


def fetch_neso_ndfd_from_csv(csv_path=NESO_NDFD_CSV) -> pd.DataFrame:
    """
    Fetch NESO NDFD from local CSV file.
    """
    logger.info(f"Fetching NESO NDFD from CSV: {csv_path}")

    df = pd.read_csv(csv_path)
    logger.info(f"Loaded {len(df)} rows from CSV")

    for col in df.columns:
        if col.lower() == "forecastdemand":
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = _normalize_neso_ndfd(df)
    logger.info(f"Normalized NESO NDFD: {len(df)} records")
    return df


def fetch_demand_forecast(
    source: str | None = None, start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """Fetch demand forecast data from the specified source.

    Args:
        source: "NESO_API" (default) | "ENTSOE" | "CSV"
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).

    Returns:
        DataFrame with columns: time (UTC delivery), forecast_time (UTC issue), value (MW).

    Source notes
    ------------
    NESO_API  — half-hourly, intraday-revised forecasts; best resolution.
    ENTSOE    — hourly, single daily snapshot stamped at D-1 10:30 Europe/London.
                Only the fc_da_d1_1030 static feature is meaningful; rolling
                features will be flat within the day.  Requires ENTSOE_API_KEY.
    CSV       — load from local NESO CSV file (path set in config).
    """
    if source is None:
        source = DEFAULT_DEMAND_FORECAST_SOURCE

    if source == "ENTSOE":
        logger.info("Fetching demand forecast data (Total Load A65 via ENTSO-E)")
        df = fetch_entsoe_demand_forecast(start_date, end_date)
        logger.info(f"Demand forecast: {len(df)} records")
        return df

    elif source == "NESO_API":
        logger.info("Fetching demand forecast data (NDFD via NESO API with daily chunking)")
        df = fetch_neso_ndfd(start_date, end_date)
        logger.info(f"Demand forecast: {len(df)} records")
        return df

    elif source == "CSV":
        logger.info("Fetching demand forecast data (NDFD via NESO CSV)")
        df = fetch_neso_ndfd_from_csv()
        logger.info(f"Demand forecast: {len(df)} records")
        return df

    else:
        raise ValueError(f"Unknown source: {source}. Must be 'NESO_API', 'ENTSOE', or 'CSV'")


def fetch_wind_forecast_from_csv(csv_path=WIND_FORECAST_CSV) -> pd.DataFrame:
    """Load wind forecast from a local CSV (columns: dataset, publishTime, startTime, generation)."""
    logger.info(f"Loading wind forecast from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    for col in ("startTime", "publishTime"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    logger.info(f"Wind forecast: {len(df)} records")
    return df


def fetch_wind_forecast(
    source: str | None = None, start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """
    Fetch wind forecast data (WINDFOR).
    source: "ELEXON" (default) or "CSV"
    Returns raw DataFrame with columns: dataset, publishTime, startTime, generation.
    """
    if source is None:
        source = DEFAULT_WIND_FORECAST_SOURCE
    if source == "CSV":
        return fetch_wind_forecast_from_csv()
    if source == "ELEXON":
        logger.info("Fetching wind forecast data (WINDFOR via Elexon)")
        df = fetch_elexon_dataset("WINDFOR", start_date, end_date)
        logger.info(f"Wind forecast: {len(df)} records")
        return df
    raise ValueError(f"Unknown source '{source}'. Must be 'ELEXON' or 'CSV'")


def fetch_generation_actual_from_csv(csv_path=GENERATION_ACTUAL_CSV) -> pd.DataFrame:
    """Load generation mix from a local CSV (columns: dataset, publishTime, startTime, settlementDate, settlementPeriod, fuelType, generation)."""  # noqa: E501
    logger.info(f"Loading generation actual from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    for col in ("startTime", "publishTime"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    logger.info(f"Generation mix: {len(df)} records")
    return df


def fetch_generation_actual(
    source: str | None = None, start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """
    Fetch full generation mix (FUELHH).
    source: "ELEXON" (default) or "CSV"
    Returns raw DataFrame with columns: dataset, publishTime, startTime,
    settlementDate, settlementPeriod, fuelType, generation.
    """
    if source is None:
        source = DEFAULT_GENERATION_ACTUAL_SOURCE
    if source == "CSV":
        return fetch_generation_actual_from_csv()
    if source == "ELEXON":
        logger.info("Fetching generation mix data (FUELHH via Elexon)")
        df = fetch_elexon_dataset("FUELHH", start_date, end_date)
        logger.info(f"Generation mix: {len(df)} records")
        return df
    raise ValueError(f"Unknown source '{source}'. Must be 'ELEXON' or 'CSV'")


def _save_entsoe_daily(df: pd.DataFrame, dataset_name: str, date_str: str) -> None:
    """
    Save ENTSO-E data as a single JSON file for the given electricity market date.

    GB electricity days run from local midnight to local midnight (Europe/London),
    which in BST means the data starts at 23:00 UTC the previous calendar day.
    Saving all records under the market date (not UTC date) avoids successive fetches
    overwriting each other's boundary hour.
    """
    dataset_dir = os.path.join(RAW_DATA_DIR, dataset_name)
    os.makedirs(dataset_dir, exist_ok=True)

    serializable = df[["time", "value"]].copy()
    serializable["time"] = serializable["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    records = serializable.sort_values("time").to_dict(orient="records")

    file_path = os.path.join(dataset_dir, f"{dataset_name}_{date_str}.json")
    with open(file_path, "w", encoding="utf-8") as fp:
        json.dump({"data": records}, fp, indent=2)

    logger.info(f"Saved ENTSO-E daily file: {file_path}")


def _fetch_entsoe_dataset(
    document_type: str, domain: str, extra_params: dict | None = None
) -> pd.DataFrame:
    logger.info("Fetching ENTSO-E dataset %s for domain %s", document_type, domain)
    params = {
        "documentType": document_type,
        "in_Domain": domain,
        "out_Domain": domain,
    }
    if extra_params:
        params.update(extra_params)
    if ENTSOE_API_KEY:
        params["securityToken"] = ENTSOE_API_KEY

    url = ENTSOE_BASE_URL
    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()

        if "Acknowledgement_MarketDocument" in response.text:
            logger.error("ENTSO-E returned NO DATA")
            logger.error(f"Params used: {params}")
            logger.error(response.text[:500])
            raise ValueError("ENTSO-E returned acknowledgement (no data)")

        if not response.text.strip().startswith("<"):
            logger.error("Expected XML response but got HTML/text")
            logger.error("Response preview: %s", response.text[:500])
            raise ValueError("ENTSO-E API returned HTML instead of XML")

        root = ET.fromstring(response.text)

        def _strip_ns(tag):
            return tag.split("}")[-1] if "}" in tag else tag

        records = []
        for ts in root.iter():
            if _strip_ns(ts.tag) != "TimeSeries":
                continue
            for period in ts:
                if _strip_ns(period.tag) != "Period":
                    continue
                start = None
                for elem in period.iter():
                    if _strip_ns(elem.tag) == "start":
                        start = elem.text
                if not start:
                    continue
                period_start = pd.to_datetime(start, utc=True)
                for point in period:
                    if _strip_ns(point.tag) != "Point":
                        continue
                    position = None
                    price = None
                    for elem in point:
                        tag = _strip_ns(elem.tag)
                        if tag == "position":
                            position = elem.text
                        elif tag in ["price.amount", "quantity"]:
                            price = elem.text
                    if position and price:
                        try:
                            hour_offset = int(position) - 1
                            value = float(price)
                            record_time = period_start + timedelta(hours=hour_offset)
                            records.append({"time": record_time, "value": value})
                        except Exception:
                            continue

        if not records:
            raise ValueError("No valid price records found in ENTSO-E XML response")

        df = pd.DataFrame(records)
        df = df.sort_values("time").drop_duplicates(subset=["time", "value"])
        logger.info(f"Parsed {len(df)} price records from ENTSO-E XML")
        return df

    except requests.RequestException as err:
        logger.error("ENTSO-E API request failed: %s", err)
        raise
    except ET.ParseError as err:
        logger.error("Failed to parse ENTSO-E XML: %s", err)
        raise


def fetch_day_ahead_price_from_csv(csv_path=DAY_AHEAD_PRICE_CSV) -> pd.DataFrame:
    """Load day-ahead price from a local CSV (columns: time, value)."""
    logger.info(f"Loading day-ahead price from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    logger.info(f"Day-ahead price: {len(df)} records")
    return df


def _fetch_nordpool_da_day(market_day: pd.Timestamp) -> pd.DataFrame:
    """Fetch one Nord Pool delivery day of GB (N2EX) day-ahead prices.

    Nord Pool labels each delivery day in CET (``deliveryDateCET``); the entries
    themselves carry explicit UTC ``deliveryStart`` timestamps, so the returned
    frame is UTC-correct and callers stitch consecutive days together to cover a
    London/UTC window. Prices are hourly £/MWh for the ``UK`` area.

    Returns a DataFrame with columns ``time`` (UTC) and ``value`` (£/MWh); empty
    on any error or if the day is unavailable (Nord Pool only serves recent days
    without a subscription).
    """
    date_str = market_day.strftime("%Y%m%d")
    cache_dir = os.path.join(RAW_DATA_DIR, "NORDPOOL_DA")
    daily_file = os.path.join(cache_dir, f"NORDPOOL_DA_{date_str}.json")

    if os.path.exists(daily_file):
        with open(daily_file, encoding="utf-8") as fp:
            records = json.load(fp).get("data", [])
    else:
        params = {
            "date": market_day.strftime("%Y-%m-%d"),
            "market": "N2EX_DayAhead",
            "deliveryArea": "UK",
            "currency": "GBP",
        }
        headers = {"Accept": "application/json", "User-Agent": "power-trading/1.0"}
        resp = requests.get(NORDPOOL_DA_BASE_URL, params=params, headers=headers, timeout=60)
        if resp.status_code != 200 or not resp.content:
            logger.warning("Nord Pool DA %s: HTTP %s (no data)", market_day.date(), resp.status_code)
            return pd.DataFrame(columns=["time", "value"])
        entries = resp.json().get("multiAreaEntries", [])
        records = [
            {"time": e["deliveryStart"], "value": e["entryPerArea"]["UK"]}
            for e in entries
            if "UK" in e.get("entryPerArea", {})
        ]
        os.makedirs(cache_dir, exist_ok=True)
        with open(daily_file, "w", encoding="utf-8") as fp:
            json.dump({"data": records}, fp)
        logger.info("Downloaded Nord Pool DA %s: %d records", market_day.date(), len(records))

    if not records:
        return pd.DataFrame(columns=["time", "value"])
    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df[["time", "value"]]


def fetch_day_ahead_price_nordpool(
    start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """Fetch GB (N2EX) day-ahead prices from Nord Pool over a date range.

    Because Nord Pool delivery days are CET-labelled, the range is fetched
    *inclusive* of ``end_date`` so that the trailing hours of the final UTC day
    are covered; callers slice the exact window they need afterwards.
    """
    logger.info("Fetching day-ahead prices from Nord Pool (N2EX, GB)")
    current = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    all_dfs = []
    while current <= end:
        day = _fetch_nordpool_da_day(current)
        if not day.empty:
            all_dfs.append(day)
        current += pd.Timedelta(days=1)

    if not all_dfs:
        logger.error("No Nord Pool day-ahead data fetched")
        return pd.DataFrame(columns=["time", "value"])
    df = pd.concat(all_dfs, ignore_index=True)
    df = df.sort_values("time").drop_duplicates(subset=["time"])
    df = df[df["time"].notna()]
    logger.info("Nord Pool day-ahead price processed. Shape: %s", df.shape)
    return df[["time", "value"]]


def fetch_day_ahead_price(
    source: str | None = None, start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """
    Fetch day-ahead electricity price data.
    source: "ENTSOE" (default), "NORDPOOL" (live GB), or "CSV"
    Returns DataFrame with columns: time, value.
    """
    if source is None:
        source = DEFAULT_DAY_AHEAD_PRICE_SOURCE
    if source == "CSV":
        return fetch_day_ahead_price_from_csv()
    if source == "NORDPOOL":
        return fetch_day_ahead_price_nordpool(start_date=start_date, end_date=end_date)
    if source != "ENTSOE":
        raise ValueError(f"Unknown source '{source}'. Must be 'ENTSOE', 'NORDPOOL' or 'CSV'")

    logger.info("Fetching day-ahead prices from ENTSO-E")

    all_dfs = []

    current = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    while current < end:
        next_day = current + pd.Timedelta(days=1)

        date_str = current.strftime("%Y%m%d")
        daily_file = os.path.join(
            RAW_DATA_DIR, "entsoe_day_ahead_price", f"entsoe_day_ahead_price_{date_str}.json"
        )

        if os.path.exists(daily_file):
            logger.info(f"Loading cached ENTSO-E {current.date()}")
            try:
                with open(daily_file, encoding="utf-8") as fp:
                    cached = json.load(fp)
                records = cached.get("data", [])
                if records:
                    df_cached = pd.DataFrame(records)
                    df_cached["time"] = pd.to_datetime(df_cached["time"], utc=True)
                    df_cached["value"] = pd.to_numeric(df_cached["value"], errors="coerce")
                    all_dfs.append(df_cached)
            except Exception as e:
                logger.warning(f"Failed to read cached ENTSO-E {current.date()}: {e}")
            current = next_day
            continue

        logger.info(f"Fetching ENTSO-E: {current.date()}")

        # Use Europe/London market-day boundaries so that the BST-transition period
        # (23:00 UTC on the eve of a summer day = local midnight) is included.
        # In winter (GMT) this is identical to the UTC midnight-to-midnight range.
        market_day = pd.Timestamp(current).tz_localize("Europe/London")
        utc_start = market_day.normalize().tz_convert("UTC")
        utc_end = (market_day.normalize() + pd.Timedelta(days=1)).tz_convert("UTC")
        params_override = {
            "periodStart": utc_start.strftime("%Y%m%d%H%M"),
            "periodEnd": utc_end.strftime("%Y%m%d%H%M"),
        }

        try:
            df_chunk = _fetch_entsoe_dataset(
                "A44", "10YGB----------A", extra_params=params_override
            )

            if not df_chunk.empty:
                all_dfs.append(df_chunk)

                # ✅ SAVE IMMEDIATELY (per day)
                _save_entsoe_daily(df_chunk, "entsoe_day_ahead_price", date_str)

            else:
                logger.warning(f"No data returned for {current.date()}")

        except Exception as e:
            logger.warning(f"Skipping {current.date()} due to error: {e}")

        current = next_day

    # ✅ HANDLE CASE: no data at all
    if not all_dfs:
        logger.error("No ENTSO-E data fetched at all")
        return pd.DataFrame(columns=["time", "value"])

    df = pd.concat(all_dfs, ignore_index=True)
    df = df.sort_values("time").drop_duplicates(subset=["time"])

    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df[["time", "value"]]
    df = df[df["time"].notna()].sort_values("time")

    logger.info(f"Day-ahead price data processed. Shape: {df.shape}")

    return df


def _fetch_entsoe_load_forecast_day(market_day: pd.Timestamp) -> pd.DataFrame:
    """Fetch ENTSO-E Total Load Forecast (A65) for one GB market day.

    Uses outBiddingZone_Domain (not in_Domain/out_Domain used by price queries).
    Returns a DataFrame with columns: time (UTC), value (MW).
    """
    london_day = (
        market_day.tz_localize("Europe/London") if market_day.tzinfo is None else market_day
    )
    utc_start = london_day.normalize().tz_convert("UTC")
    utc_end = (london_day.normalize() + pd.Timedelta(days=1)).tz_convert("UTC")

    params: dict[str, str] = {
        "documentType": "A65",
        "processType": "A01",
        "outBiddingZone_Domain": "10YGB----------A",
        "periodStart": utc_start.strftime("%Y%m%d%H%M"),
        "periodEnd": utc_end.strftime("%Y%m%d%H%M"),
    }
    if ENTSOE_API_KEY:
        params["securityToken"] = ENTSOE_API_KEY

    response = requests.get(ENTSOE_BASE_URL, params=params, timeout=60)
    response.raise_for_status()

    if "Acknowledgement_MarketDocument" in response.text:
        raise ValueError(f"ENTSO-E returned no data for {market_day.date()}")
    if not response.text.strip().startswith("<"):
        raise ValueError("ENTSO-E returned non-XML response")

    root = ET.fromstring(response.text)

    def _strip_ns(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    records = []
    for ts in root.iter():
        if _strip_ns(ts.tag) != "TimeSeries":
            continue
        for period in ts:
            if _strip_ns(period.tag) != "Period":
                continue
            start_text = next(
                (el.text for el in period.iter() if _strip_ns(el.tag) == "start"), None
            )
            resolution_text = next(
                (el.text for el in period.iter() if _strip_ns(el.tag) == "resolution"), None
            )
            if not start_text:
                continue
            period_start = pd.to_datetime(start_text, utc=True)
            resolution_h = 1.0
            if resolution_text == "PT30M":
                resolution_h = 0.5
            elif resolution_text == "PT60M":
                resolution_h = 1.0

            for point in period:
                if _strip_ns(point.tag) != "Point":
                    continue
                position = next((el.text for el in point if _strip_ns(el.tag) == "position"), None)
                quantity = next((el.text for el in point if _strip_ns(el.tag) == "quantity"), None)
                if position and quantity:
                    try:
                        offset_h = (int(position) - 1) * resolution_h
                        record_time = period_start + pd.Timedelta(hours=offset_h)
                        records.append({"time": record_time, "value": float(quantity)})
                    except Exception:
                        continue

    if not records:
        raise ValueError(f"No load forecast records in ENTSO-E XML for {market_day.date()}")

    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("time").drop_duplicates(subset=["time"])


def fetch_entsoe_demand_forecast(
    start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """Fetch ENTSO-E Total Load Forecast (A65) for GB over the configured date range.

    Caches one JSON file per market day under data/raw/entsoe_demand_forecast/.

    forecast_time assumption
    ------------------------
    ENTSO-E does not publish intraday-revised load forecasts the way NESO does —
    it provides a single day-ahead forecast without a per-revision timestamp.
    We therefore stamp every forecast record with **D-1 10:30 Europe/London**,
    which aligns with the pre-auction static snapshot key used in
    process_demand_forecast (fc_da_d1_1030).

    Consequence: rolling forecast features (fc_rel_*) derived from this source
    will not vary intraday.  Only the static D-1 10:30 snapshot is meaningful.
    If intraday resolution matters, use NESO_API instead.
    """
    dataset_name = "entsoe_demand_forecast"
    current = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    all_dfs: list[pd.DataFrame] = []

    while current < end:
        date_str = current.strftime("%Y%m%d")
        daily_file = os.path.join(RAW_DATA_DIR, dataset_name, f"{dataset_name}_{date_str}.json")

        if os.path.exists(daily_file):
            logger.info("Loading cached ENTSO-E demand forecast %s", current.date())
            try:
                with open(daily_file, encoding="utf-8") as fp:
                    cached = json.load(fp)
                records = cached.get("data", [])
                if records:
                    df_cached = pd.DataFrame(records)
                    df_cached["time"] = pd.to_datetime(df_cached["time"], utc=True)
                    df_cached["value"] = pd.to_numeric(df_cached["value"], errors="coerce")
                    all_dfs.append(df_cached)
            except Exception as exc:
                logger.warning("Failed to read cached demand forecast %s: %s", current.date(), exc)
            current += pd.Timedelta(days=1)
            continue

        logger.info("Fetching ENTSO-E demand forecast %s", current.date())
        try:
            df_day = _fetch_entsoe_load_forecast_day(current)
            if not df_day.empty:
                _save_entsoe_daily(df_day, dataset_name, date_str)
                all_dfs.append(df_day)
            else:
                logger.warning("No demand forecast data for %s", current.date())
        except Exception as exc:
            logger.warning("Skipping demand forecast %s: %s", current.date(), exc)

        current += pd.Timedelta(days=1)

    if not all_dfs:
        logger.error("No ENTSO-E demand forecast data fetched")
        return pd.DataFrame(columns=["time", "forecast_time", "value"])

    df = pd.concat(all_dfs, ignore_index=True)
    df = df.sort_values("time").drop_duplicates(subset=["time"])

    # Stamp forecast_time as D-1 10:30 Europe/London for each delivery day.
    delivery_london = df["time"].dt.tz_convert("Europe/London")
    prev_day = delivery_london.dt.normalize() - pd.Timedelta(days=1)
    df["forecast_time"] = (prev_day + pd.Timedelta(hours=10, minutes=30)).dt.tz_convert("UTC")

    logger.info("ENTSO-E demand forecast: %d records", len(df))
    return df[["time", "forecast_time", "value"]]


def download_b1770(start_date: str, end_date: str) -> None:
    """
    Download B1770 system prices (SBP/SSP) from Elexon and cache as daily JSON files.
    Endpoint: /balancing/settlement/system-prices/{settlementDate}
    Skips dates that are already cached.
    """
    dataset = "B1770"
    dataset_dir = os.path.join(RAW_DATA_DIR, dataset)
    os.makedirs(dataset_dir, exist_ok=True)

    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    while current <= end:
        date_str = current.strftime("%Y%m%d")
        date_iso = current.strftime("%Y-%m-%d")
        cache_path = os.path.join(dataset_dir, f"{dataset}_{date_str}_page_1.json")

        if os.path.exists(cache_path):
            logger.info(f"Skipping B1770 {date_iso}: already cached")
            current += timedelta(days=1)
            continue

        url = f"{ELEXON_BASE_URL}/balancing/settlement/system-prices/{date_iso}"
        try:
            response = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
            response.raise_for_status()
            payload = response.json()
            _save_raw_json(dataset, os.path.basename(cache_path), payload)
            records = payload.get("data", payload) if isinstance(payload, dict) else payload
            logger.info(f"Downloaded B1770 {date_iso}: {len(records)} records")
        except Exception as e:
            logger.warning(f"Failed to download B1770 {date_iso}: {e}")

        current += timedelta(days=1)


def fetch_market_index_from_csv(csv_path=MARKET_INDEX_CSV) -> pd.DataFrame:
    """Load market index data from a local CSV (columns: dataset, startTime, dataProvider, settlementDate, settlementPeriod, price, volume)."""  # noqa: E501
    logger.info(f"Loading market index price from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    if "startTime" in df.columns:
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    logger.info(f"Market index: {len(df)} records")
    return df


def fetch_market_index_price(
    source: str | None = None, start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """
    Fetch Market Index Data (MID).
    source: "ELEXON" (default) or "CSV"
    Returns raw DataFrame with columns: startTime, dataProvider, price, volume, etc.
    Provider filtering (APXMIDP) is handled in process_market_index_price.
    """
    if source is None:
        source = DEFAULT_MARKET_INDEX_SOURCE
    if source == "CSV":
        return fetch_market_index_from_csv()
    if source == "ELEXON":
        try:
            df = fetch_elexon_dataset("MID", start_date, end_date)
            if df.empty:
                logger.warning("MID dataset returned no data; skipping market_index_price feature")
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.warning("MID dataset unavailable (%s); skipping market_index_price feature", e)
            return pd.DataFrame()
    raise ValueError(f"Unknown source '{source}'. Must be 'ELEXON' or 'CSV'")


def fetch_demand_actual_from_csv(csv_path=DEMAND_ACTUAL_CSV) -> pd.DataFrame:
    """Load actual demand from a local CSV (columns: dataset, publishTime, startTime, settlementDate, settlementPeriod, demand)."""  # noqa: E501
    logger.info(f"Loading demand actual from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    for col in ("startTime", "publishTime"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    logger.info(f"Demand actual: {len(df)} records")
    return df


def fetch_demand_actual(
    source: str | None = None, start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """
    Fetch actual demand (ITSDO).
    source: "ELEXON" (default) or "CSV"
    Returns raw DataFrame with columns: startTime, settlementDate, settlementPeriod, demand.
    """
    if source is None:
        source = DEFAULT_DEMAND_ACTUAL_SOURCE
    if source == "CSV":
        return fetch_demand_actual_from_csv()
    if source == "ELEXON":
        try:
            df = fetch_elexon_dataset("ITSDO", start_date, end_date)
            if df.empty:
                logger.warning("ITSDO returned no data; skipping demand_actual feature")
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.warning("ITSDO unavailable (%s); skipping demand_actual feature", e)
            return pd.DataFrame()
    raise ValueError(f"Unknown source '{source}'. Must be 'ELEXON' or 'CSV'")


def fetch_imbalance_price_from_csv(csv_path=IMBALANCE_PRICE_CSV) -> pd.DataFrame:
    """Load imbalance price from a local CSV (columns: startTime, systemBuyPrice, systemSellPrice, netImbalanceVolume, settlementDate, settlementPeriod, ...)."""  # noqa: E501
    logger.info(f"Loading imbalance price from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    if "startTime" in df.columns:
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    logger.info(f"Imbalance price: {len(df)} records")
    return df


def fetch_imbalance_price(
    source: str | None = None, start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """
    Fetch B1770 system prices (SBP/SSP/NIV).
    source: "ELEXON" (default) or "CSV"
    Returns raw DataFrame with columns: startTime, systemBuyPrice, systemSellPrice,
    netImbalanceVolume, settlementDate, settlementPeriod, etc.
    """
    if source is None:
        source = DEFAULT_IMBALANCE_PRICE_SOURCE
    if source == "CSV":
        return fetch_imbalance_price_from_csv()
    if source != "ELEXON":
        raise ValueError(f"Unknown source '{source}'. Must be 'ELEXON' or 'CSV'")

    download_b1770(start_date, end_date)

    dataset_dir = os.path.join(RAW_DATA_DIR, "B1770")
    files = sorted(glob.glob(os.path.join(dataset_dir, "B1770_*_page_1.json")))
    if not files:
        logger.warning("No B1770 files found; skipping imbalance_price feature")
        return pd.DataFrame()

    all_records = []
    for f in files:
        with open(f, encoding="utf-8") as fp:
            payload = json.load(fp)
        records = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(records, list):
            all_records.extend(records)

    if not all_records:
        logger.warning("B1770 files contained no records")
        return pd.DataFrame()

    return pd.DataFrame(all_records)

    # """
    # Load day-ahead electricity price data from local CSV (Kaggle proxy).
    # """
    # logger.warning("Using local Kaggle price data (ENTSO-E API disabled)")

    # path = "data/raw/day_ahead_prices.csv"
    # df = pd.read_csv(path)

    # # --- Detect time column ---
    # if "DateTime" in df.columns:
    #     df["time"] = pd.to_datetime(df["DateTime"], utc=True)
    # elif "MTU" in df.columns:
    #     df["time"] = pd.to_datetime(df["MTU"], utc=True)
    # elif "time" in df.columns:
    #     df["time"] = pd.to_datetime(df["time"], utc=True)
    # else:
    #     raise ValueError(f"No time column found. Columns: {df.columns}")

    # # --- Detect price column ---
    # if "Price" in df.columns:
    #     df["value"] = df["Price"]
    # elif "DayAheadPrice" in df.columns:
    #     df["value"] = df["DayAheadPrice"]
    # elif "value" in df.columns:
    #     df["value"] = df["value"]
    # else:
    #     raise ValueError(f"No price column found. Columns: {df.columns}")

    # # --- Clean ---
    # df = df[["time", "value"]]
    # df = df[df["time"].notna()]
    # df = df.sort_values("time").drop_duplicates("time")

    # logger.info(f"Loaded local day-ahead price data. Shape: {df.shape}")
    # return df
