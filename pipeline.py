import pandas as pd
import numpy as np
import logging
import os
import json
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
    PROCESSED_DATA_DIR, RAW_DATA_DIR, DEFAULT_SIGNAL_THRESHOLD, SAVE_OUTPUTS_DEFAULT
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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


def build_features_pipeline(version: str = CURRENT_VERSION):
    """
    Build features dataset from raw data by calling the actual data pipeline functions.

    Args:
        version: Version string for experiment tracking
    """
    logger.info(f"Building features pipeline for version {version}")

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
        features_df = build_features(processed_df)

        logger.info(f"Features pipeline completed successfully. Final shape: {features_df.shape}")

    except Exception as e:
        logger.error(f"Features pipeline failed: {str(e)}")
        raise


def save_model(model, metadata: dict):
    """
    Save trained model and metadata.

    Args:
        model: Trained model object
        metadata: Dictionary with model metadata
    """
    try:
        import joblib
    except ImportError:
        logger.error("joblib not available for model saving")
        return

    # Update metadata with timestamp
    metadata['saved_at'] = datetime.now().isoformat()

    # Save model
    model_path = MODEL_FILE
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    logger.info(f"Model saved to {model_path}")

    # Save metadata
    metadata_path = MODEL_METADATA_FILE
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    logger.info(f"Model metadata saved to {metadata_path}")


def load_model(version: str = CURRENT_VERSION):
    """
    Load trained model from disk.

    Args:
        version: Version string for path resolution

    Returns:
        Loaded model object or None if not found
    """
    try:
        import joblib
    except ImportError:
        logger.error("joblib not available for model loading")
        return None

    model_path = MODEL_FILE
    if not model_path.exists():
        logger.warning(f"Model file not found: {model_path}")
        return None

    model = joblib.load(model_path)
    logger.info(f"Model loaded from {model_path}")
    return model


def save_outputs(predictions_df: pd.DataFrame, signals: np.ndarray, pnl_series: np.ndarray):
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

    PREDICTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    predictions_df[["time", "actual_spread", "predicted_spread"]].to_csv(PREDICTIONS_FILE, index=False)
    logger.info(f"Predictions saved to {PREDICTIONS_FILE}")

    signals_df.to_csv(SIGNALS_FILE, index=False)
    logger.info(f"Signals saved to {SIGNALS_FILE}")

    pd.DataFrame({'time': timestamps, 'pnl': pnl_series}).to_csv(PNL_FILE, index=False)
    logger.info(f"PnL saved to {PNL_FILE}")


def save_metrics(model_metrics: dict, trading_metrics: dict):
    """
    Save performance metrics to JSON file.

    Args:
        model_metrics: Dictionary with model performance metrics
        trading_metrics: Dictionary with trading performance metrics
    """
    metrics = {
        'timestamp': datetime.now().isoformat(),
        'model_performance': model_metrics,
        'trading_performance': trading_metrics
    }

    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(METRICS_FILE, 'w') as f:
        json.dump(metrics, f, indent=2, default=str)

    logger.info(f"Metrics saved to {METRICS_FILE}")


def run_full_pipeline(execution_mode: str = "full") -> dict:
    """
    Run the complete electricity trading pipeline from data to backtest results.

    Args:
        execution_mode: Execution mode - 'full', 'features', or 'model'
            - 'full': Run complete pipeline from data ingestion
            - 'features': Skip data ingestion, use processed data
            - 'model': Skip to model training using saved features

    Returns:
        Dictionary with pipeline results and metrics
    """
    logger.info(f"Starting pipeline execution in {execution_mode} mode")

    # Ensure directories exist
    ensure_directories()

    results = {}
    results['timestamp'] = datetime.now().isoformat()
    results['execution_mode'] = execution_mode
    results['signal_threshold'] = DEFAULT_SIGNAL_THRESHOLD

    try:
        # Step 1: Data preparation (varies by execution mode)
        if execution_mode == "full":
            logger.info("Full mode: Building features from raw data")
            build_features_pipeline()

        elif execution_mode == "features":
            logger.info("Features mode: Using existing processed data")
            processed_data = load_processed_data()
            if processed_data is None:
                raise FileNotFoundError("Processed data not found. Run in 'full' mode first.")
            # Build features from processed data
            build_features(processed_data)

        elif execution_mode == "model":
            logger.info("Model mode: Using existing features")
            # Features should exist from previous runs

        else:
            raise ValueError(f"Invalid execution_mode: {execution_mode}. Must be 'full', 'features', or 'model'")

        # Step 2: Train model (always executed)
        logger.info("Step 2: Training model")
        model, predictions_df, X_test = train_model(
            features_path=str(FEATURES_DATASET),
            model_type="xgboost",
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
            threshold=DEFAULT_SIGNAL_THRESHOLD,
        )
        schedule_df, signals = build_daily_schedule(
            predicted_spread=predictions_df["predicted_spread"].values,
            signals=raw_signals,
            timestamps=predictions_df["time"].values,
            top_n=5,
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
        )

        results['pnl_series'] = pnl_series
        results['trading_metrics'] = trading_metrics

        # Step 5: Calculate model metrics
        logger.info("Step 5: Calculating model metrics")
        from sklearn.metrics import mean_absolute_error, mean_squared_error
        mae  = mean_absolute_error(predictions_df["actual_spread"], predictions_df["predicted_spread"])
        rmse = np.sqrt(mean_squared_error(predictions_df["actual_spread"], predictions_df["predicted_spread"]))

        ts = predictions_df["time"].values
        model_metrics = {
            'mae':               mae,
            'rmse':              rmse,
            'test_period_start': str(pd.to_datetime(ts[0],  utc=True)),
            'test_period_end':   str(pd.to_datetime(ts[-1], utc=True)),
            'test_n_periods':    int(len(predictions_df)),
        }
        results['model_metrics'] = model_metrics

        # Step 6: Save outputs
        if SAVE_OUTPUTS_DEFAULT:
            logger.info("Step 6: Saving outputs")
            save_model(model, {
                'model_type':       'xgboost',
                'signal_threshold': DEFAULT_SIGNAL_THRESHOLD,
                'n_features':       X_test.shape[1],
                'n_samples':        len(X_test),
                'features':         list(X_test.columns),
                'execution_mode':   execution_mode,
            })

            save_outputs(predictions_df, signals, pnl_series)
            save_metrics(model_metrics, trading_metrics)

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
        print("\nOUTPUTS SAVED:")
        print(f"  Model:       {MODEL_FILE}")
        print(f"  Predictions: {PREDICTIONS_FILE}")
        print(f"  Signals:     {SIGNALS_FILE}")
        print(f"  PnL:         {PNL_FILE}")
        print(f"  Metrics:     {METRICS_FILE}")

    print("=" * 60)


def load_experiment_results(version: str = CURRENT_VERSION) -> dict:
    """
    Load saved experiment results for analysis.

    Args:
        version: Version string to load

    Returns:
        Dictionary with loaded results
    """
    logger.info(f"Loading experiment results for version {version}")

    results = {'version': version}

    try:
        # Load metrics
        if METRICS_FILE.exists():
            with open(METRICS_FILE, 'r') as f:
                metrics_data = json.load(f)
            results['metrics'] = metrics_data

        # Load model
        model = load_model(version)
        if model:
            results['model'] = model

        # Load predictions
        if PREDICTIONS_FILE.exists():
            pred_df = pd.read_csv(PREDICTIONS_FILE)
            results['predictions_df'] = pred_df

        # Load signals
        if SIGNALS_FILE.exists():
            signals_df = pd.read_csv(SIGNALS_FILE)
            results['signals_df'] = signals_df

        # Load PnL
        if PNL_FILE.exists():
            pnl_df = pd.read_csv(PNL_FILE)
            results['pnl_df'] = pnl_df

        logger.info(f"Loaded results for version {version}")
        return results

    except Exception as e:
        logger.error(f"Failed to load results for version {version}: {str(e)}")
        return {}


if __name__ == "__main__":
    # Run the pipeline when script is executed directly
    results = run_full_pipeline()
    print(f"\nPipeline completed for version {results.get('version', 'unknown')}. Results keys: {list(results.keys())}")