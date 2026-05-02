import os
from pathlib import Path

# ============================================================================
# PROJECT ROOT  (defined first so .env can be loaded before anything else)
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Load .env if present — never committed, copy from .env.example to get started
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

# --- Experiment settings (override in .env for local runs) ---
START_DATE               = os.environ.get("START_DATE",               "2018-01-01")
END_DATE                 = os.environ.get("END_DATE",                 "2019-01-01")
CURRENT_VERSION          = os.environ.get("CURRENT_VERSION",          "v1")
DEFAULT_SIGNAL_THRESHOLD = float(os.environ.get("DEFAULT_SIGNAL_THRESHOLD", "5.0"))

# --- API Keys (Elexon BMRS v1 and NESO CKAN are open — no key required) ---
ELEXON_API_KEY = os.environ.get("ELEXON_API_KEY", "")
ENTSOE_API_KEY = os.environ.get("ENTSOE_API_KEY", "")  # register at transparency.entsoe.eu

# API Base URLs
ELEXON_BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
NESO_BASE_URL   = "https://api.neso.energy/api/3/action/datastore_search_sql"

# NESO CKAN Resource IDs
NESO_NDFD_RESOURCE_ID = "9847e7bb-986e-49be-8138-717b25933fbb"  # Day-ahead demand forecast

# --- Data sources (override in .env to switch between API and local CSV) ---
DEFAULT_DEMAND_FORECAST_SOURCE   = os.environ.get("DEFAULT_DEMAND_FORECAST_SOURCE",   "NESO_API")  # "ELEXON" | "NESO_API" | "NESO_CSV"
DEFAULT_WIND_FORECAST_SOURCE     = os.environ.get("DEFAULT_WIND_FORECAST_SOURCE",     "ELEXON")    # "ELEXON" | "CSV"
DEFAULT_GENERATION_ACTUAL_SOURCE = os.environ.get("DEFAULT_GENERATION_ACTUAL_SOURCE", "ELEXON")    # "ELEXON" | "CSV"
DEFAULT_DAY_AHEAD_PRICE_SOURCE   = os.environ.get("DEFAULT_DAY_AHEAD_PRICE_SOURCE",   "ENTSOE")    # "ENTSOE" | "CSV"
DEFAULT_MARKET_INDEX_SOURCE      = os.environ.get("DEFAULT_MARKET_INDEX_SOURCE",      "ELEXON")    # "ELEXON" | "CSV"
DEFAULT_DEMAND_ACTUAL_SOURCE     = os.environ.get("DEFAULT_DEMAND_ACTUAL_SOURCE",     "ELEXON")    # "ELEXON" | "CSV"
DEFAULT_IMBALANCE_PRICE_SOURCE   = os.environ.get("DEFAULT_IMBALANCE_PRICE_SOURCE",   "ELEXON")    # "ELEXON" | "CSV"

# Default pipeline settings
SAVE_OUTPUTS_DEFAULT = True

# ============================================================================
# PATH CONFIGURATION
# ============================================================================

DATA_DIR    = PROJECT_ROOT / "data"
MODELS_DIR  = PROJECT_ROOT / "models"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# Raw data paths (not versioned)
RAW_DATA_DIR       = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# CSV paths for local-file sources (generate once via API, then reuse)
NESO_NDFD_CSV         = RAW_DATA_DIR / "neso_ndfd.csv"
WIND_FORECAST_CSV     = RAW_DATA_DIR / "wind_forecast.csv"
GENERATION_ACTUAL_CSV = RAW_DATA_DIR / "generation_actual.csv"
DAY_AHEAD_PRICE_CSV   = RAW_DATA_DIR / "day_ahead_price.csv"
MARKET_INDEX_CSV      = RAW_DATA_DIR / "market_index_price.csv"
DEMAND_ACTUAL_CSV     = RAW_DATA_DIR / "demand_actual.csv"
IMBALANCE_PRICE_CSV   = RAW_DATA_DIR / "imbalance_price.csv"

# Versioned paths
VERSIONED_DATA_DIR   = DATA_DIR    / CURRENT_VERSION
VERSIONED_MODELS_DIR = MODELS_DIR  / CURRENT_VERSION
VERSIONED_OUTPUTS_DIR = OUTPUTS_DIR / CURRENT_VERSION
FEATURES_DIR         = DATA_DIR / "features" / CURRENT_VERSION

# File paths
FEATURES_DATASET    = FEATURES_DIR         / "features_dataset.parquet"
MODEL_FILE          = VERSIONED_MODELS_DIR  / "model.joblib"
MODEL_METADATA_FILE = VERSIONED_MODELS_DIR  / "metadata.json"
PREDICTIONS_FILE    = VERSIONED_OUTPUTS_DIR / "predictions.csv"
SIGNALS_FILE        = VERSIONED_OUTPUTS_DIR / "signals.csv"
PNL_FILE            = VERSIONED_OUTPUTS_DIR / "pnl.csv"
METRICS_FILE        = VERSIONED_OUTPUTS_DIR / "metrics.json"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def ensure_directories():
    """Create all necessary directories if they don't exist."""
    for directory in [
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        FEATURES_DIR,
        VERSIONED_MODELS_DIR,
        VERSIONED_OUTPUTS_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
