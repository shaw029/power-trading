import pandas as pd
import numpy as np
import logging
import os
import json
import joblib
from pathlib import Path
from datetime import datetime

# Import our custom modules
from src.data.download import (
    fetch_demand_forecast, fetch_wind_forecast, fetch_generation_actual,
    fetch_day_ahead_price, fetch_market_index_price, fetch_demand_actual, fetch_imbalance_price,
)
from src.data.preprocess import (
    merge_all,
    process_generation_mix, process_imbalance_price, process_day_ahead_price,
    process_market_index_price, process_demand_actual,
    process_wind_forecast, process_demand_forecast,
)
from src.features.build_features import build_features
from src.models.train import train_model
from src.models.signal import generate_signal, build_daily_schedule, compute_penalty_buffer
from src.backtest.engine import run_backtest
from src.utils.config import (
    ensure_directories, FEATURES_DATASET, MODEL_FILE, PREDICTIONS_FILE,
    SIGNALS_FILE, PNL_FILE, METRICS_FILE, MODEL_METADATA_FILE, CURRENT_VERSION,
    PROCESSED_DATA_DIR, RAW_DATA_DIR, DEFAULT_SIGNAL_THRESHOLD, SAVE_OUTPUTS_DEFAULT,
    PROJECT_ROOT, VERSIONED_FEATURES_DIR, VERSIONED_MODELS_DIR, VERSIONED_TRADING_DIR,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def setup_experiment_paths(config: dict | None = None) -> dict:
    """Return a dict of Path objects for all experiment artifacts.

    Paths follow a three-tier structure under artifacts/:
        artifacts/{strategy}/{run_name}/features/  — engineered features
        artifacts/{strategy}/{run_name}/model/     — model + metadata
        artifacts/{strategy}/{run_name}/trading/   — predictions, signals, pnl, metrics

    When config is None, falls back to the static versioned paths from config.py.
    """
    if config is None:
        return {
            "features_dir":     VERSIONED_FEATURES_DIR,
            "model_dir":        VERSIONED_MODELS_DIR,
            "trading_dir":      VERSIONED_TRADING_DIR,
            "features_file":    FEATURES_DATASET,
            "model_file":       MODEL_FILE,
            "metadata_file":    MODEL_METADATA_FILE,
            "predictions_file": PREDICTIONS_FILE,
            "signals_file":     SIGNALS_FILE,
            "pnl_file":         PNL_FILE,
            "metrics_file":     METRICS_FILE,
        }

    strategy = config["strategy"]
    run_name = config["run_name"]
    run_dir      = PROJECT_ROOT / "artifacts" / strategy / run_name
    features_dir = run_dir / "features"
    model_dir    = run_dir / "model"
    trading_dir  = run_dir / "trading"
    return {
        "features_dir":     features_dir,
        "model_dir":        model_dir,
        "trading_dir":      trading_dir,
        "features_file":    features_dir / "features.parquet",
        "model_file":       model_dir    / "model.joblib",
        "metadata_file":    model_dir    / "metadata.json",
        "predictions_file": trading_dir  / "predictions.csv",
        "signals_file":     trading_dir  / "signals.csv",
        "pnl_file":         trading_dir  / "pnl.csv",
        "metrics_file":     trading_dir  / "metrics.json",
    }


def load_processed_data(version: str = CURRENT_VERSION) -> pd.DataFrame:
    """
    Load processed data from disk.

    Args:
        version: Version string (not used for processed data as it's not versioned)

    Returns:
        DataFrame with processed data or None if not found
    """
    processed_file = PROCESSED_DATA_DIR / "processed_data.parquet"

    if not processed_file.exists():
        logger.warning(f"Processed data file not found: {processed_file}")
        return None

    logger.info(f"Loading processed data from {processed_file}")
    df = pd.read_parquet(processed_file)
    logger.info(f"Loaded processed data with shape: {df.shape}")
    return df


def build_features_pipeline(features_save_path=None):
    logger.info("Building features from raw data")

    try:
        # Step 1: Download raw data
        logger.info("Step 1: Downloading raw data")

        wind_df = fetch_wind_forecast()
        demand_df = fetch_demand_forecast()
        generation_df = fetch_generation_actual()
        price_df = fetch_day_ahead_price()
        mid_df = fetch_market_index_price()
        itsdo_df = fetch_demand_actual()
        b1770_df = fetch_imbalance_price()

        # Step 2: Preprocess and merge
        logger.info("Step 2: Preprocessing and merging data")

        generation_processed = process_generation_mix(generation_df)
        b1770_processed      = process_imbalance_price(b1770_df)
        price_processed      = process_day_ahead_price(price_df)
        mid_processed        = process_market_index_price(mid_df)
        itsdo_processed      = process_demand_actual(itsdo_df)
        wind_processed       = process_wind_forecast(wind_df)
        demand_processed     = process_demand_forecast(demand_df)

        processed_df = merge_all(
            generation_mix     = generation_processed,
            imbalance_price    = b1770_processed,
            day_ahead_price    = price_processed,
            market_index_price = mid_processed,
            demand_actual      = itsdo_processed,
            wind_forecast      = wind_processed,
            demand_forecast    = demand_processed,
        )

        # Step 3: Build features
        logger.info("Step 3: Building features")
        features_df = build_features(processed_df, save_path=features_save_path)

        logger.info(f"Features pipeline completed successfully. Final shape: {features_df.shape}")

    except Exception as e:
        logger.error(f"Features pipeline failed: {str(e)}")
        raise


def save_model(model, metadata: dict, paths: dict):
    metadata['saved_at'] = datetime.now().isoformat()
    paths["model_dir"].mkdir(parents=True, exist_ok=True)
    joblib.dump(model, paths["model_file"])
    logger.info(f"Model saved to {paths['model_file']}")
    with open(paths["metadata_file"], 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    logger.info(f"Model metadata saved to {paths['metadata_file']}")


def load_model(paths: dict | None = None):
    """Load trained model from the path specified in paths, or the default static path."""
    model_path = paths["model_file"] if paths else MODEL_FILE
    if not model_path.exists():
        logger.warning(f"Model file not found: {model_path}")
        return None
    model = joblib.load(model_path)
    logger.info(f"Model loaded from {model_path}")
    return model


def save_outputs(predictions_df: pd.DataFrame, signals: np.ndarray, pnl_series: np.ndarray, paths: dict):
    timestamps = predictions_df["time"].values

    _ts = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))
    _london = _ts.tz_convert("Europe/London")
    auction_times = (_london.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=11)).tz_convert("UTC")

    signals_df = pd.DataFrame({
        'auction_time':     auction_times,
        'delivery_time':    timestamps,
        'predicted_spread': predictions_df["predicted_spread"].values,
        'signal':           signals,
        'direction':        pd.array(signals, dtype=int),
    })
    signals_df['direction'] = signals_df['direction'].map({1: 'BUY', -1: 'SELL', 0: 'NEUTRAL'})

    paths["trading_dir"].mkdir(parents=True, exist_ok=True)
    predictions_df[["time", "actual_spread", "predicted_spread"]].to_csv(paths["predictions_file"], index=False)
    logger.info(f"Predictions saved to {paths['predictions_file']}")

    signals_df.to_csv(paths["signals_file"], index=False)
    logger.info(f"Signals saved to {paths['signals_file']}")

    pd.DataFrame({'time': timestamps, 'pnl': pnl_series}).to_csv(paths["pnl_file"], index=False)
    logger.info(f"PnL saved to {paths['pnl_file']}")


def save_metrics(model_metrics: dict, trading_metrics: dict, paths: dict):
    metrics = {
        'timestamp': datetime.now().isoformat(),
        'model_performance': model_metrics,
        'trading_performance': trading_metrics,
    }
    paths["trading_dir"].mkdir(parents=True, exist_ok=True)
    with open(paths["metrics_file"], 'w') as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info(f"Metrics saved to {paths['metrics_file']}")


def run_full_pipeline(execution_mode: str = "full", config: dict | None = None) -> dict:
    """Run the complete electricity trading pipeline from data to backtest results.

    Args:
        execution_mode: 'full', 'features', or 'model'
        config:         Optional experiment config dict loaded from a YAML file.
                        When provided, drives model hyperparams, validation strategy,
                        signal thresholds, and output paths.  Falls back to defaults
                        from config.py when None.
    """
    logger.info(f"Starting pipeline execution in {execution_mode} mode")
    ensure_directories()

    # --- settings from config (or defaults) ---
    signal_threshold  = config["signal"]["threshold"]                       if config else DEFAULT_SIGNAL_THRESHOLD
    top_n             = config["signal"]["top_n"]                           if config else 5
    transaction_cost  = config["signal"].get("transaction_cost", 0.0)       if config else 0.0
    model_type       = config["model"]["type"]         if config else "xgboost"
    model_params     = config["model"]["hyperparameters"] if config else None
    val_type         = config["validation"]["type"]    if config else "walk_forward"
    wf_train_days    = config["validation"]["train_days"] if config else 200
    wf_test_days     = config["validation"]["test_days"]  if config else 30
    wf_step_days     = config["validation"]["step_days"]  if config else 30

    paths = setup_experiment_paths(config)

    results = {}
    results['timestamp'] = datetime.now().isoformat()
    results['execution_mode'] = execution_mode
    results['signal_threshold'] = signal_threshold
    results['paths'] = paths

    try:
        # Step 1: Data preparation (varies by execution mode)
        if execution_mode == "full":
            logger.info("Full mode: Building features from raw data")
            build_features_pipeline(features_save_path=paths["features_file"])

        elif execution_mode == "features":
            logger.info("Features mode: Using existing processed data")
            processed_data = load_processed_data()
            if processed_data is None:
                raise FileNotFoundError("Processed data not found. Run in 'full' mode first.")
            build_features(processed_data, save_path=paths["features_file"])

        elif execution_mode == "model":
            logger.info("Model mode: Using existing features")
            # Features should exist from previous runs

        else:
            raise ValueError(f"Invalid execution_mode: {execution_mode}. Must be 'full', 'features', or 'model'")

        # Step 2: Train model (always executed)
        logger.info("Step 2: Training model")
        model, predictions_df, X_test = train_model(
            features_path=str(paths["features_file"]),
            model_type=model_type,
            model_params=model_params,
            validation_type=val_type,
            wf_train_days=wf_train_days,
            wf_test_days=wf_test_days,
            wf_step_days=wf_step_days,
        )

        results['model'] = model
        results['predictions_df'] = predictions_df
        results['X_test'] = X_test

        # Step 3: Compute penalty buffer, generate signals, apply Top-5 daily schedule
        logger.info("Step 3: Generating trading signals")
        penalty_buffer = compute_penalty_buffer(
            system_buy_price=predictions_df["system_buy_price"].values,
            system_sell_price=predictions_df["system_sell_price"].values,
        )
        raw_signals = generate_signal(
            predicted_spread=predictions_df["predicted_spread"].values,
            penalty_buffer=penalty_buffer,
            threshold=signal_threshold,
        )
        schedule_df, signals = build_daily_schedule(
            predicted_spread=predictions_df["predicted_spread"].values,
            signals=raw_signals,
            timestamps=predictions_df["time"].values,
            top_n=top_n,
        )

        results['signals'] = signals
        results['schedule_df'] = schedule_df

        # Step 4: Run backtest
        logger.info("Step 4: Running backtest")
        pnl_series, trading_metrics = run_backtest(
            signals=signals,
            da_prices=predictions_df["day_ahead_price"].values,
            system_sell_price=predictions_df["system_sell_price"].values,
            system_buy_price=predictions_df["system_buy_price"].values,
            timestamps=predictions_df["time"].values,
            cost_per_trade=transaction_cost,
        )

        results['pnl_series'] = pnl_series
        results['trading_metrics'] = trading_metrics

        # Step 5: Calculate model metrics
        logger.info("Step 5: Calculating model metrics")
        from sklearn.metrics import mean_absolute_error, mean_squared_error
        mae  = mean_absolute_error(predictions_df["actual_spread"], predictions_df["predicted_spread"])
        rmse = np.sqrt(mean_squared_error(predictions_df["actual_spread"], predictions_df["predicted_spread"]))

        actual    = predictions_df["actual_spread"].values
        predicted = predictions_df["predicted_spread"].values
        directional_accuracy = float(np.mean(np.sign(actual) == np.sign(predicted)))

        ts = predictions_df["time"].values
        model_metrics = {
            'mae':                  mae,
            'rmse':                 rmse,
            'directional_accuracy': directional_accuracy,
            'test_period_start':    str(pd.to_datetime(ts[0],  utc=True)),
            'test_period_end':      str(pd.to_datetime(ts[-1], utc=True)),
            'test_n_periods':       int(len(predictions_df)),
        }
        results['model_metrics'] = model_metrics

        # Step 6: Save outputs
        if SAVE_OUTPUTS_DEFAULT:
            logger.info("Step 6: Saving outputs")
            save_model(model, {
                'model_type':       model_type,
                'signal_threshold': signal_threshold,
                'n_features':       X_test.shape[1],
                'n_samples':        len(X_test),
                'features':         list(X_test.columns),
                'execution_mode':   execution_mode,
            }, paths)

            save_outputs(predictions_df, signals, pnl_series, paths)
            save_metrics(model_metrics, trading_metrics, paths)

        # Step 7: Print results
        logger.info("Pipeline completed successfully")
        print_pipeline_results(results)

        return results

    except Exception as e:
        logger.error(f"Pipeline failed with error: {str(e)}")
        raise


def print_pipeline_results(results: dict):
    print("\n" + "=" * 60)
    print(f"ELECTRICITY TRADING PIPELINE RESULTS  (mode: {results['execution_mode']})")
    print("=" * 60)

    mm = results['model_metrics']
    tm = results['trading_metrics']
    ds = tm.get('daily_summary', {})

    print("\nMODEL PERFORMANCE  (spread prediction, £/MWh):")
    print(f"  MAE:           {mm['mae']:.2f}")
    print(f"  RMSE:          {mm['rmse']:.2f}")

    print("\nACCOUNT:")
    print(f"  Starting:      £{tm['starting_capital']:>12,.0f}")
    print(f"  Final:         £{tm['final_capital']:>12,.0f}  ({tm['total_return_pct']:+.1%})")

    print("\nTRADING PERFORMANCE:")
    print(f"  Total PnL:     £{tm['total_pnl']:>12,.2f}")
    print(f"  Active trades:  {tm['n_trades']:>11,}")
    print(f"  Win rate:       {tm['win_rate']:>11.1%}")
    print(f"  Profit factor:  {tm['profit_factor']:>11.2f}")
    print(f"  Sharpe ratio:   {tm['sharpe_ratio']:>11.3f}")
    print(f"  Max drawdown:  £{tm['max_drawdown']:>12,.2f}")
    print(f"  Avg win:       £{tm['avg_win']:>12,.2f}")
    print(f"  Avg loss:      £{tm['avg_loss']:>12,.2f}")
    if tm.get('halted_at_period') is not None:
        print(f"  *** Simulation halted at period {tm['halted_at_period']} (drawdown limit) ***")

    if ds:
        print("\nDAILY PnL SUMMARY:")
        print(f"  Mean daily:    £{ds['mean_daily_pnl']:>12,.0f}")
        print(f"  Std daily:     £{ds['std_daily_pnl']:>12,.0f}")
        print(f"  Best day:      £{ds['best_day_pnl']:>12,.0f}")
        print(f"  Worst day:     £{ds['worst_day_pnl']:>12,.0f}")
        print(f"  Pos/Neg days:   {ds['positive_days']} / {ds['negative_days']}  (of {ds['total_days']})")

    sig = tm['signal_distribution']
    print("\nSIGNAL DISTRIBUTION (after Top-5 filter):")
    print(f"  Long:    {sig['long']}")
    print(f"  Short:   {sig['short']}")
    print(f"  Neutral: {sig['neutral']}")

    if 'schedule_df' in results and not results['schedule_df'].empty:
        sched = results['schedule_df']
        print(f"\nDAILY BIDDING SCHEDULE ({len(sched)} trade slots across {sched['market_date'].nunique()} days):")
        print(sched.head(10).to_string(index=False))
        if len(sched) > 10:
            print(f"  … ({len(sched) - 10} more rows)")

    if SAVE_OUTPUTS_DEFAULT:
        p = results.get('paths', {})
        print("\nOUTPUTS SAVED:")
        print(f"  Model:       {p.get('model_file',       MODEL_FILE)}")
        print(f"  Predictions: {p.get('predictions_file', PREDICTIONS_FILE)}")
        print(f"  Signals:     {p.get('signals_file',     SIGNALS_FILE)}")
        print(f"  PnL:         {p.get('pnl_file',         PNL_FILE)}")
        print(f"  Metrics:     {p.get('metrics_file',     METRICS_FILE)}")

    print("=" * 60)


def load_experiment_results(config: dict | None = None) -> dict:
    """Load saved experiment artifacts from the config-driven paths (or static defaults)."""
    paths = setup_experiment_paths(config)
    results = {}

    try:
        if paths["metrics_file"].exists():
            with open(paths["metrics_file"]) as f:
                results['metrics'] = json.load(f)

        model = load_model(paths)
        if model:
            results['model'] = model

        if paths["predictions_file"].exists():
            results['predictions_df'] = pd.read_csv(paths["predictions_file"])

        if paths["signals_file"].exists():
            results['signals_df'] = pd.read_csv(paths["signals_file"])

        if paths["pnl_file"].exists():
            results['pnl_df'] = pd.read_csv(paths["pnl_file"])

        logger.info(f"Loaded results from {paths['trading_dir']}")
        return results

    except Exception as e:
        logger.error(f"Failed to load results: {str(e)}")
        return {}


if __name__ == "__main__":
    # Run the pipeline when script is executed directly
    results = run_full_pipeline()
    print(f"\nPipeline completed for version {results.get('version', 'unknown')}. Results keys: {list(results.keys())}")