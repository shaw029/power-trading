import logging
import os
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ============================================================================
# PROJECT ROOT  (defined first so .env can be loaded before anything else)
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.parent

_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

# ============================================================================
# CONFIGURATION
# ============================================================================

CURRENT_VERSION = os.environ.get("CURRENT_VERSION", "v1")
DEFAULT_SIGNAL_THRESHOLD = float(os.environ.get("DEFAULT_SIGNAL_THRESHOLD", "5.0"))

# --- API Keys ---
ELEXON_API_KEY = os.environ.get("ELEXON_API_KEY", "")
ENTSOE_API_KEY = os.environ.get("ENTSOE_API_KEY", "")

# API Base URLs
ELEXON_BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
NESO_BASE_URL = "https://api.neso.energy/api/3/action/datastore_search_sql"

# NESO CKAN Resource IDs
NESO_NDFD_RESOURCE_ID = "9847e7bb-986e-49be-8138-717b25933fbb"

# Legacy constants — kept for downstream imports until download.py is migrated
START_DATE = "2018-01-01"
END_DATE = "2019-01-01"
DEFAULT_DEMAND_FORECAST_SOURCE = "NESO_API"
DEFAULT_WIND_FORECAST_SOURCE = "ELEXON"
DEFAULT_GENERATION_ACTUAL_SOURCE = "ELEXON"
DEFAULT_DAY_AHEAD_PRICE_SOURCE = "ENTSOE"
DEFAULT_MARKET_INDEX_SOURCE = "ELEXON"
DEFAULT_DEMAND_ACTUAL_SOURCE = "ELEXON"
DEFAULT_IMBALANCE_PRICE_SOURCE = "ELEXON"

# Default pipeline settings
SAVE_OUTPUTS_DEFAULT = True

# ============================================================================
# PATH CONFIGURATION
# ============================================================================

DATA_DIR = PROJECT_ROOT / "data"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

RAW_DATA_DIR = Path(os.environ.get("RAW_DATA_DIR", "")) if os.environ.get("RAW_DATA_DIR") else DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# CSV paths for local-file sources
NESO_NDFD_CSV = RAW_DATA_DIR / "neso_ndfd.csv"
WIND_FORECAST_CSV = RAW_DATA_DIR / "wind_forecast.csv"
GENERATION_ACTUAL_CSV = RAW_DATA_DIR / "generation_actual.csv"
DAY_AHEAD_PRICE_CSV = RAW_DATA_DIR / "day_ahead_price.csv"
MARKET_INDEX_CSV = RAW_DATA_DIR / "market_index_price.csv"
DEMAND_ACTUAL_CSV = RAW_DATA_DIR / "demand_actual.csv"
IMBALANCE_PRICE_CSV = RAW_DATA_DIR / "imbalance_price.csv"

# Versioned fallback paths
VERSIONED_FEATURES_DIR = ARTIFACTS_DIR / CURRENT_VERSION / "features"
VERSIONED_MODELS_DIR   = ARTIFACTS_DIR / CURRENT_VERSION / "model"
VERSIONED_TRADING_DIR  = ARTIFACTS_DIR / CURRENT_VERSION / "trading"

FEATURES_DATASET  = VERSIONED_FEATURES_DIR / "features.parquet"
MODEL_FILE        = VERSIONED_MODELS_DIR   / "model.joblib"
MODEL_METADATA_FILE = VERSIONED_MODELS_DIR / "metadata.json"
PREDICTIONS_FILE  = VERSIONED_TRADING_DIR  / "predictions.csv"
SIGNALS_FILE      = VERSIONED_TRADING_DIR  / "signals.csv"
PNL_FILE          = VERSIONED_TRADING_DIR  / "pnl.csv"
METRICS_FILE      = VERSIONED_TRADING_DIR  / "metrics.json"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def ensure_directories():
    """Create base data directories. Artifact dirs are created on-demand by save functions."""
    for directory in [RAW_DATA_DIR, PROCESSED_DATA_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


# ============================================================================
# YAML CONFIG LOADING & VALIDATION
# ============================================================================

_VALID_STRATEGY_TYPES = ("virtual", "bess")

_BESS_DEFAULTS = {
    "capacity_mwh": 100.0,
    "power_mw": 50.0,
    "charge_efficiency": 0.94,
    "discharge_efficiency": 0.94,
    "degradation_cost_per_mwh": 5.00,
    "initial_soc_pct": 0.50,
    "min_soc_pct": 0.10,
    "max_soc_pct": 0.90,
    "resolution_h": 1.0,
    "soc_drift_tolerance": 0.05,
    "target_daily_cycles": None,
    "margin_buy": 0.0,
    "margin_sell": 0.0,
}

_FIXED_SOURCE_KEYS = (
    "wind_source",
    "generation_source",
    "day_ahead_price_source",
    "market_index_source",
    "demand_actual_source",
    "imbalance_source",
)

_FIXED_SOURCE_DEFAULTS = {
    "wind_source": "ELEXON",
    "generation_source": "ELEXON",
    "day_ahead_price_source": "ENTSOE",
    "market_index_source": "ELEXON",
    "demand_actual_source": "ELEXON",
    "imbalance_source": "ELEXON",
}

_ALLOWED_SOURCES = {"ELEXON", "ENTSOE", "NESO_API", "CSV"}


def load_config(path: str | Path) -> dict:
    """Load and validate a YAML experiment config."""
    with open(path) as f:
        config = yaml.safe_load(f)

    return validate_config(config)


def validate_config(config: dict) -> dict:
    """Validate config dict, applying defaults for optional sections."""
    config.setdefault("strategy_type", "virtual")

    if config["strategy_type"] not in _VALID_STRATEGY_TYPES:
        raise ValueError(
            f"Invalid strategy_type '{config['strategy_type']}'. "
            f"Must be one of {list(_VALID_STRATEGY_TYPES)}."
        )

    if config["strategy_type"] == "bess":
        bess = config.get("bess", {})
        for key, default in _BESS_DEFAULTS.items():
            bess.setdefault(key, default)
        # The intraday engine reuses the execution slippage as its per-MWh
        # execution-cost buffer. The pipeline passes the bess block alone to
        # run_intraday_session, so surface the top-level execution.slippage (or
        # its default) inside the bess config; without this the engine always
        # fell back to its hard-coded 0.50 default regardless of the YAML.
        bess.setdefault("execution", {})
        bess["execution"].setdefault(
            "slippage", config.get("execution", {}).get("slippage", 0.50)
        )
        config["bess"] = bess

    # ── data.periods ────────────────────────────────────────────────────
    data = config.get("data")
    if not data or not data.get("periods"):
        raise ValueError("config must include a non-empty 'data.periods' list.")

    periods = data["periods"]
    if not isinstance(periods, list) or len(periods) == 0:
        raise ValueError("'data.periods' must be a non-empty list.")

    parsed_periods: list[tuple[datetime, datetime]] = []
    for i, p in enumerate(periods):
        for field in ("start", "end", "demand_source"):
            if field not in p:
                raise ValueError(f"data.periods[{i}] is missing required field '{field}'.")

        try:
            start_dt = datetime.strptime(str(p["start"]), "%Y-%m-%d")
            end_dt = datetime.strptime(str(p["end"]), "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"data.periods[{i}] has an invalid date: {exc}") from exc

        if start_dt >= end_dt:
            raise ValueError(f"data.periods[{i}]: start ({p['start']}) must be before end ({p['end']}).")

        if str(p["demand_source"]) not in _ALLOWED_SOURCES:
            raise ValueError(
                f"data.periods[{i}]: demand_source '{p['demand_source']}' "
                f"not in {sorted(_ALLOWED_SOURCES)}."
            )

        parsed_periods.append((start_dt, end_dt))

    # Check for overlapping periods
    sorted_periods = sorted(parsed_periods, key=lambda t: t[0])
    for j in range(1, len(sorted_periods)):
        prev_end = sorted_periods[j - 1][1]
        curr_start = sorted_periods[j][0]
        if curr_start < prev_end:
            raise ValueError(
                f"data.periods overlap: a period ending {prev_end.date()} "
                f"overlaps with one starting {curr_start.date()}."
            )

    # ── fixed data sources ──────────────────────────────────────────────
    for key in _FIXED_SOURCE_KEYS:
        if key not in data:
            data[key] = _FIXED_SOURCE_DEFAULTS[key]
            logger.warning("'data.%s' not set — defaulting to '%s'.", key, data[key])
        elif str(data[key]) not in _ALLOWED_SOURCES:
            raise ValueError(
                f"data.{key} '{data[key]}' not in {sorted(_ALLOWED_SOURCES)}."
            )

    return config


# ============================================================================
# CONFIG ACCESSORS
# ============================================================================


def get_periods(config: dict) -> list[dict[str, str]]:
    """Return the list of period dicts from a validated config."""
    periods: list[dict[str, str]] = config["data"]["periods"]
    return periods


def get_sources(config: dict) -> dict:
    """Return fixed (non-period) data sources as a flat dict, applying defaults where absent."""
    data = config.get("data", {})
    return {key: data.get(key, _FIXED_SOURCE_DEFAULTS[key]) for key in _FIXED_SOURCE_KEYS}
