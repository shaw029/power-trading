import glob
import json
import pandas as pd
import requests
import logging
import os
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
from src.utils.config import (
    START_DATE, END_DATE,
    ELEXON_BASE_URL, ELEXON_API_KEY,
    ENTSOE_BASE_URL, ENTSOE_API_KEY,
    NESO_BASE_URL, NESO_NDFD_RESOURCE_ID,
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

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

os.makedirs(RAW_DATA_DIR, exist_ok=True)


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


def _load_raw_records_from_file(filepath: str) -> list:
    with open(filepath, "r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
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
                "format": "json"
            }
            logger.info(f"Downloading {dataset} for publish window {params['publishDateTimeFrom']} to {params['publishDateTimeTo']}")
        elif dataset in ["FUELHH"]:
            settlement_date = current_date.strftime("%Y-%m-%d")
            params = {
                "settlementDateFrom": settlement_date,
                "settlementDateTo": settlement_date,
                "format": "json"
            }
            logger.info(f"Downloading {dataset} for settlement date {settlement_date}")
        elif dataset == "MID":
            params = {
                "from": current_date.strftime("%Y-%m-%dT00:00:00Z"),
                "to": next_date.strftime("%Y-%m-%dT00:00:00Z"),
                "format": "json"
            }
            logger.info(f"Downloading MID for {params['from']} to {params['to']}")
        else:
            raise ValueError(f"Unknown dataset: {dataset}")

        if ELEXON_API_KEY:
            params["apiKey"] = ELEXON_API_KEY

        url = base_url
        page = 1
        while url:
            request_params = params if url == base_url else None
            response = requests.get(url, params=request_params, headers={"Accept": "application/json"}, timeout=30)
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


def _normalize_elexon_ndfd(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize Elexon NDFD (demand forecast) data.
    
    Column mapping:
    - time: startTime (delivery time)
    - forecast_time: publishTime (forecast issue time)
    - value: quantity
    """
    df = df.copy()

    if "forecastDate" not in df.columns:
        raise ValueError(f"forecastDate column missing for Elexon NDFD. Available: {df.columns}")
    if "publishTime" not in df.columns:
        raise ValueError(f"publishTime missing for Elexon NDFD. Available: {df.columns}")
    if "demand" not in df.columns:
        raise ValueError(f"demand column missing for Elexon NDFD. Available: {df.columns}")

    df["value"] = df["demand"]

    # convert forecastDate → datetime
    df["time"] = pd.to_datetime(df["forecastDate"])
    df["time"] = df["time"].dt.tz_localize("UTC")

    df["forecast_time"] = pd.to_datetime(df["publishTime"], utc=True)

    # --- CLEAN ---
    df = df[df["time"].notna()]
    df = df.sort_values(["time", "forecast_time"])
    df = df.drop_duplicates(subset=["time", "forecast_time", "value"])

    return df[["time", "forecast_time", "value"]]


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
        
        # Check if files already exist
        if _chunk_has_raw_files("NESO_NDFD", date_str):
            logger.info(f"Skipping NESO_NDFD {date_iso} (already exists)")
            current_date += timedelta(days=1)
            continue
        
        logger.info(f"Fetching NESO_NDFD {date_iso}")
        
        try:
            # Fetch data for this day with pagination
            all_records = []
            offset = 0
            limit = 50000
            page = 1
            
            while True:
                query = f'SELECT * FROM "{NESO_NDFD_RESOURCE_ID}" WHERE "TARGETDATE" = \'{date_iso}\' ORDER BY "_id" LIMIT {limit} OFFSET {offset}'
                
                params = {"sql": query}
                response = requests.get(NESO_BASE_URL, params=params, timeout=60)
                response.raise_for_status()
                
                data = response.json()
                
                if not data.get("success"):
                    raise ValueError(f"NESO API error: {data.get('error', 'Unknown error')}")
                
                records = data.get("result", {}).get("records", [])
                
                if not records:
                    break
                
                # Save this page immediately
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


def read_neso_ndfd(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Read cached NESO NDFD JSON files and combine into DataFrame.
    Expects files at: data/raw/NESO_NDFD/NESO_NDFD_YYYYMMDD_page_*.json
    """
    dataset_dir = _raw_dataset_dir("NESO_NDFD")
    if not os.path.isdir(dataset_dir):
        raise ValueError(f"No cached files found for NESO_NDFD")
    
    files = sorted(glob.glob(os.path.join(dataset_dir, "NESO_NDFD_*_page_*.json")))
    if not files:
        raise ValueError(f"No cached raw files found for NESO_NDFD")
    
    all_records = []
    for filepath in files:
        with open(filepath, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
        
        # Extract records from payload["result"]["records"]
        records = payload.get("result", {}).get("records", [])
        all_records.extend(records)
    
    if not all_records:
        raise ValueError(f"No records found in cached NESO_NDFD files")
    
    df = pd.DataFrame(all_records)
    return df


def fetch_neso_sql(resource_id: str, date_filter: str | None = None) -> pd.DataFrame:
    """
    Fetch data from NESO CKAN DataStore API using SQL query with pagination.
    
    Args:
        resource_id: CKAN resource ID
        date_filter: Optional date filter in format 'YYYY-MM-DD' for TARGETDATE column
    
    Returns:
        Concatenated DataFrame from all pages
    """
    logger.info(f"Fetching NESO resource {resource_id}")
    
    all_records = []
    offset = 0
    limit = 50000
    
    while True:
        if date_filter:
            query = f'SELECT * FROM "{resource_id}" WHERE "TARGETDATE" = \'{date_filter}\' ORDER BY "_id" LIMIT {limit} OFFSET {offset}'
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
    
    df = pd.DataFrame(all_records)
    return df


def _normalize_neso_ndfd(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize NESO NDFD (day-ahead demand forecast) data.
    
    Expects columns like:
    - FORECASTDEMAND (numeric demand)
    - PUBLISHTIME or FORECASTTIME (issue time)
    - DELIVERYTIME or STARTTIME (delivery time)
    
    Optional columns (preserved for feature engineering):
    - CARDINALPOINT → cardinal_point
    - CP_TYPE → cp_type
    - CP_ST_TIME → block_start
    - CP_END_TIME → block_end
    """
    df = df.copy()
    
    # Create lowercase column mapping for case-insensitive lookup
    col_lower = {col.lower(): col for col in df.columns}
    
    # Get value column (FORECASTDEMAND)
    if "forecastdemand" in col_lower:
        df["value"] = pd.to_numeric(df[col_lower["forecastdemand"]], errors="coerce")
    else:
        raise ValueError(f"forecastdemand column not found. Available: {df.columns.tolist()}")
    
    # Get delivery/start time column
    time_col = None
    for name in ["deliverytime", "starttime", "time", "cp_st_time", "targetdate"]:
        if name in col_lower:
            time_col = col_lower[name]
            break
    
    if not time_col:
        raise ValueError(f"No delivery/start time column found. Available: {df.columns.tolist()}")
    
    df["time"] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    
    # Get forecast/publish time column
    forecast_col = None
    for name in ["publishtime", "forecasttime", "publishedtime"]:
        if name in col_lower:
            forecast_col = col_lower[name]
            break
    
    if forecast_col:
        df["forecast_time"] = pd.to_datetime(df[forecast_col], utc=True, errors="coerce")
    else:
        # If no forecast_time, use delivery time
        logger.warning("No forecast/publish time column found. Falling back to using delivery time.")
        df["forecast_time"] = df["time"]
    
    # Clean and deduplicate
    df = df[df["time"].notna()]
    df = df[df["forecast_time"].notna()]
    df = df.sort_values(["time", "forecast_time"])
    df = df.drop_duplicates(subset=["time", "forecast_time", "value"])
    
    # --- Preserve optional columns for feature engineering ---
    
    # List of required columns (always returned)
    output_cols = ["time", "forecast_time", "value"]
    
    # Optional columns to preserve if they exist in input
    optional_mappings = {
        "cardinalpoint": "cardinal_point",
        "cp_type": "cp_type",
        "cp_st_time": "block_start",
        "cp_end_time": "block_end",
    }
    
    for input_name_lower, output_name in optional_mappings.items():
        if input_name_lower in col_lower:
            input_col = col_lower[input_name_lower]
            df[output_name] = df[input_col]
            output_cols.append(output_name)
    
    # Keep extra columns (cardinal points, block info) for feature engineering,
    # but core pipeline relies only on time/forecast_time/value
    return df[output_cols]


def fetch_neso_ndfd() -> pd.DataFrame:
    """
    Fetch NESO day-ahead demand forecast using daily chunking.
    Downloads via CKAN SQL API with date range from START_DATE to END_DATE.
    
    Returns:
        DataFrame with columns: time, forecast_time, value (UTC datetime)
    """
    logger.info("Fetching NESO NDFD via daily chunking")
    
    # Download fresh data for date range
    download_neso_ndfd_daily(START_DATE, END_DATE)
    
    # Read cached data
    df = read_neso_ndfd(START_DATE, END_DATE)
    logger.info(f"Read {len(df)} rows from NESO NDFD cache")
    
    # Ensure numeric conversion for FORECASTDEMAND
    for col in df.columns:
        if col.lower() == "forecastdemand":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # Normalize
    df = _normalize_neso_ndfd(df)
    logger.info(f"Normalized NESO NDFD: {len(df)} records")
    
    return df


def fetch_neso_ndfd_api(resource_id: str | None = None) -> pd.DataFrame:
    """
    Fetch entire NESO day-ahead demand forecast via CKAN SQL API without daily chunking or caching.

    NOTE: This fetches the full dataset in one go and may be slow or fail for large
    date ranges. It is kept for debugging or specific use cases.
    Prefer `fetch_neso_ndfd()` for robust, cached, daily-chunked downloads.
    
    Args:
        resource_id: CKAN resource ID (defaults to NESO_NDFD_RESOURCE_ID from config)
    
    Returns:
        DataFrame with columns: time, forecast_time, value (UTC datetime)
    """
    if resource_id is None:
        resource_id = NESO_NDFD_RESOURCE_ID
    
    logger.info("Fetching NESO NDFD via API (non-cached)")
    
    df = fetch_neso_sql(resource_id)
    logger.info(f"Fetched {len(df)} rows from NESO API")
    
    # Ensure numeric conversion for FORECASTDEMAND
    for col in df.columns:
        if col.lower() == "forecastdemand":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df = _normalize_neso_ndfd(df)
    logger.info(f"Normalized NESO NDFD: {len(df)} records")
    
    return df


def fetch_neso_ndfd_from_csv(csv_path=NESO_NDFD_CSV) -> pd.DataFrame:
    """
    Fetch NESO NDFD from local CSV file.
    
    Args:
        csv_path: Path to CSV file
    
    Returns:
        DataFrame with columns: time, forecast_time, value (UTC datetime)
    """
    logger.info(f"Fetching NESO NDFD from CSV: {csv_path}")
    
    df = pd.read_csv(csv_path)
    logger.info(f"Loaded {len(df)} rows from CSV")
    
    # Ensure numeric conversion for FORECASTDEMAND
    for col in df.columns:
        if col.lower() == "forecastdemand":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df = _normalize_neso_ndfd(df)
    logger.info(f"Normalized NESO NDFD: {len(df)} records")
    
    return df


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


def _fetch_entsoe_dataset(document_type: str, domain: str, raw_name: str, extra_params: dict | None = None) -> pd.DataFrame:
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
        
        # Check if response is XML (starts with "<")
        if not response.text.strip().startswith("<"):
            logger.error("Expected XML response but got HTML/text")
            logger.error("Response preview: %s", response.text[:500])
            raise ValueError("ENTSO-E API returned HTML instead of XML")
        
        # Parse XML (don't save XML; daily JSON files will be saved from fetch_day_ahead_price)
        root = ET.fromstring(response.text)
        
        # Extract data from XML structure
        # Helper to strip namespace
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

                            records.append({
                                "time": record_time,
                                "value": value
                            })
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


def fetch_demand_forecast(source: str | None = None) -> pd.DataFrame:
    """
    Fetch demand forecast data from specified source.
    
    Args:
        source: Data source - "ELEXON", "NESO_API", or "NESO_CSV"
               If None, uses DEFAULT_DEMAND_FORECAST_SOURCE from config
    
    Returns:
        DataFrame with columns: time, forecast_time, value (UTC datetime)
    """
    if source is None:
        source = DEFAULT_DEMAND_FORECAST_SOURCE
    
    if source == "ELEXON":
        logger.info("Fetching demand forecast data (NDFD via ELEXON)")
        df = fetch_elexon_dataset("NDFD", START_DATE, END_DATE)
        df = _normalize_elexon_ndfd(df)
        logger.info(f"Demand forecast: {len(df)} records")
        return df
    
    elif source == "NESO_API":
        logger.info("Fetching demand forecast data (NDFD via NESO API with daily chunking)")
        df = fetch_neso_ndfd()
        logger.info(f"Demand forecast: {len(df)} records")
        return df
    
    elif source == "NESO_CSV":
        logger.info("Fetching demand forecast data (NDFD via NESO CSV)")
        df = fetch_neso_ndfd_from_csv()
        logger.info(f"Demand forecast: {len(df)} records")
        return df
    
    else:
        raise ValueError(f"Unknown source: {source}. Must be 'ELEXON', 'NESO_API', or 'NESO_CSV'")


def fetch_wind_forecast_from_csv(csv_path=WIND_FORECAST_CSV) -> pd.DataFrame:
    """Load wind forecast from a local CSV (columns: dataset, publishTime, startTime, generation)."""
    logger.info(f"Loading wind forecast from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    for col in ("startTime", "publishTime"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    logger.info(f"Wind forecast: {len(df)} records")
    return df


def fetch_wind_forecast(source: str | None = None) -> pd.DataFrame:
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
        df = fetch_elexon_dataset("WINDFOR", START_DATE, END_DATE)
        logger.info(f"Wind forecast: {len(df)} records")
        return df
    raise ValueError(f"Unknown source '{source}'. Must be 'ELEXON' or 'CSV'")


def fetch_generation_actual_from_csv(csv_path=GENERATION_ACTUAL_CSV) -> pd.DataFrame:
    """Load generation mix from a local CSV (columns: dataset, publishTime, startTime, settlementDate, settlementPeriod, fuelType, generation)."""
    logger.info(f"Loading generation actual from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    for col in ("startTime", "publishTime"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    logger.info(f"Generation mix: {len(df)} records")
    return df


def fetch_generation_actual(source: str | None = None) -> pd.DataFrame:
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
        df = fetch_elexon_dataset("FUELHH", START_DATE, END_DATE)
        logger.info(f"Generation mix: {len(df)} records")
        return df
    raise ValueError(f"Unknown source '{source}'. Must be 'ELEXON' or 'CSV'")


def fetch_day_ahead_price_from_csv(csv_path=DAY_AHEAD_PRICE_CSV) -> pd.DataFrame:
    """Load day-ahead price from a local CSV (columns: time, value)."""
    logger.info(f"Loading day-ahead price from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    logger.info(f"Day-ahead price: {len(df)} records")
    return df


def fetch_day_ahead_price(source: str | None = None) -> pd.DataFrame:
    """
    Fetch day-ahead electricity price data.
    source: "ENTSOE" (default) or "CSV"
    Returns DataFrame with columns: time, value.
    """
    if source is None:
        source = DEFAULT_DAY_AHEAD_PRICE_SOURCE
    if source == "CSV":
        return fetch_day_ahead_price_from_csv()
    if source != "ENTSOE":
        raise ValueError(f"Unknown source '{source}'. Must be 'ENTSOE' or 'CSV'")

    logger.info("Fetching day-ahead prices from ENTSO-E")

    all_dfs = []

    current = pd.to_datetime(START_DATE)
    end = pd.to_datetime(END_DATE)

    while current < end:
        next_day = current + pd.Timedelta(days=1)

        date_str = current.strftime("%Y%m%d")
        daily_file = os.path.join(RAW_DATA_DIR, "entsoe_day_ahead_price", f"entsoe_day_ahead_price_{date_str}.json")

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
        utc_start  = market_day.normalize().tz_convert("UTC")
        utc_end    = (market_day.normalize() + pd.Timedelta(days=1)).tz_convert("UTC")
        params_override = {
            "periodStart": utc_start.strftime("%Y%m%d%H%M"),
            "periodEnd":   utc_end.strftime("%Y%m%d%H%M"),
        }

        try:
            df_chunk = _fetch_entsoe_dataset(
                "A44",
                "10YGB----------A",
                "entsoe_day_ahead_price",
                extra_params=params_override
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
    """Load market index data from a local CSV (columns: dataset, startTime, dataProvider, settlementDate, settlementPeriod, price, volume)."""
    logger.info(f"Loading market index price from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    if "startTime" in df.columns:
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    logger.info(f"Market index: {len(df)} records")
    return df


def fetch_market_index_price(source: str | None = None) -> pd.DataFrame:
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
            df = fetch_elexon_dataset("MID", START_DATE, END_DATE)
            if df.empty:
                logger.warning("MID dataset returned no data; skipping market_index_price feature")
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.warning("MID dataset unavailable (%s); skipping market_index_price feature", e)
            return pd.DataFrame()
    raise ValueError(f"Unknown source '{source}'. Must be 'ELEXON' or 'CSV'")


def fetch_demand_actual_from_csv(csv_path=DEMAND_ACTUAL_CSV) -> pd.DataFrame:
    """Load actual demand from a local CSV (columns: dataset, publishTime, startTime, settlementDate, settlementPeriod, demand)."""
    logger.info(f"Loading demand actual from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    for col in ("startTime", "publishTime"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    logger.info(f"Demand actual: {len(df)} records")
    return df


def fetch_demand_actual(source: str | None = None) -> pd.DataFrame:
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
            df = fetch_elexon_dataset("ITSDO", START_DATE, END_DATE)
            if df.empty:
                logger.warning("ITSDO returned no data; skipping demand_actual feature")
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.warning("ITSDO unavailable (%s); skipping demand_actual feature", e)
            return pd.DataFrame()
    raise ValueError(f"Unknown source '{source}'. Must be 'ELEXON' or 'CSV'")


def fetch_imbalance_price_from_csv(csv_path=IMBALANCE_PRICE_CSV) -> pd.DataFrame:
    """Load imbalance price from a local CSV (columns: startTime, systemBuyPrice, systemSellPrice, netImbalanceVolume, settlementDate, settlementPeriod, ...)."""
    logger.info(f"Loading imbalance price from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    if "startTime" in df.columns:
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    logger.info(f"Imbalance price: {len(df)} records")
    return df


def fetch_imbalance_price(source: str | None = None) -> pd.DataFrame:
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

    download_b1770(START_DATE, END_DATE)

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
