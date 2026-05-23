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


def save_bess_outputs(results_df: pd.DataFrame, config: dict, paths: dict):
    trading_dir = paths["trading_dir"]
    trading_dir.mkdir(parents=True, exist_ok=True)

    results_df.to_csv(trading_dir / "pnl.csv", index=False)
    logger.info(f"BESS PnL saved to {trading_dir / 'pnl.csv'}")

    net = results_df["net_pnl"]
    avg_daily = float(net.mean())
    std_daily = float(net.std(ddof=1)) if len(net) > 1 else 0.0
    sharpe = (avg_daily / std_daily) * np.sqrt(365) if std_daily > 0 else 0.0

    cumulative = net.cumsum()
    max_drawdown = float((cumulative - cumulative.cummax()).min())

    bess_cfg = config["bess"]
    total_degradation = float(results_df["degradation_cost"].sum())
    throughput = total_degradation / bess_cfg["degradation_cost_per_mwh"] if bess_cfg["degradation_cost_per_mwh"] > 0 else 0.0
    total_cycles = throughput / (2 * bess_cfg["capacity_mwh"])

    metrics = {
        "total_da_revenue": float(results_df["da_revenue"].sum()),
        "total_intraday_pnl": float(results_df["intraday_pnl"].sum()),
        "total_imbalance_pnl": float(results_df["imbalance_pnl"].sum()),
        "total_degradation_cost": total_degradation,
        "total_net_pnl": float(net.sum()),
        "total_cycles": float(total_cycles),
        "avg_daily_net_pnl": avg_daily,
        "sharpe_ratio": float(sharpe),
        "max_drawdown": max_drawdown,
    }

    with open(trading_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    logger.info(f"BESS metrics saved to {trading_dir / 'metrics.json'}")


def _run_bess_pipeline(config: dict) -> dict:
    from src.bess.bess_asset import BESSAsset
    from src.bess.da_optimizer import optimize_da_schedule
    from src.bess.intraday_manager import run_intraday_session

    bess_cfg = config["bess"]
    bess_paths_config = {**config, "strategy": "bess"}
    paths = setup_experiment_paths(bess_paths_config)

    results = {
        "timestamp": datetime.now().isoformat(),
        "mode": "bess",
        "paths": paths,
    }

    logger.info("BESS pipeline: loading and processing price data")
    da_processed = process_day_ahead_price(fetch_day_ahead_price())
    mid_processed = process_market_index_price(fetch_market_index_price())
    imb_processed = process_imbalance_price(fetch_imbalance_price())

    prices = (
        da_processed.resample("1h").mean()
        .join(mid_processed.resample("1h").mean())
        .join(imb_processed[["system_buy_price"]].resample("1h").mean())
        .dropna()
    )

    asset = BESSAsset(
        capacity_mwh=bess_cfg["capacity_mwh"],
        power_mw=bess_cfg["power_mw"],
        round_trip_efficiency=bess_cfg["round_trip_efficiency"],
        degradation_cost_per_mwh=bess_cfg["degradation_cost_per_mwh"],
        initial_soc_pct=bess_cfg["initial_soc_pct"],
    )

    daily_results = []
    for date, day_df in prices.groupby(prices.index.date):
        if len(day_df) != 24:
            continue
        asset.reset()
        da_prices = day_df["day_ahead_price"].tolist()
        schedule = optimize_da_schedule(da_prices, asset)
        result = run_intraday_session(
            da_schedule=schedule,
            da_prices=da_prices,
            mid_prices=day_df["mid_price"].tolist(),
            imbalance_prices=day_df["system_buy_price"].tolist(),
            asset=asset,
            config=bess_cfg,
        )
        daily_results.append({
            "date": date,
            "da_revenue": result["da_revenue"],
            "intraday_pnl": result["intraday_pnl"],
            "imbalance_pnl": result["imbalance_pnl"],
            "degradation_cost": result["total_degradation_cost"],
            "net_pnl": result["net_pnl"],
        })

    results_df = pd.DataFrame(daily_results)
    save_bess_outputs(results_df, config, paths)
    results["results_df"] = results_df

    logger.info("BESS pipeline completed successfully")
    return results


def _run_virtual_pipeline(config: dict | None = None) -> dict:
    signal_threshold     = config["signal"]["threshold"]                              if config else DEFAULT_SIGNAL_THRESHOLD
    top_n                = config["signal"]["top_n"]                                  if config else 5
    transaction_cost     = config["signal"].get("transaction_cost", 0.0)              if config else 0.0
    baseline_hedge_ratio = config.get("execution", {}).get("baseline_hedge_ratio", 0.50) if config else 0.50
    take_profit_pct      = config.get("execution", {}).get("take_profit_pct", 0.90)      if config else 0.90
    stop_loss_price_delta = config.get("execution", {}).get("stop_loss_price_delta", 5.00) if config else 5.00
    slippage             = config.get("execution", {}).get("slippage", 0.50)             if config else 0.50
    model_type       = config["model"]["type"]         if config else "xgboost"
    model_params     = config["model"]["hyperparameters"] if config else None
    val_type         = config["validation"]["type"]    if config else "walk_forward"
    wf_train_days    = config["validation"]["train_days"] if config else 200
    wf_test_days     = config["validation"]["test_days"]  if config else 30
    wf_step_days     = config["validation"]["step_days"]  if config else 30

    paths = setup_experiment_paths(config)

    results = {
        "timestamp": datetime.now().isoformat(),
        "mode": "virtual",
        "signal_threshold": signal_threshold,
        "paths": paths,
    }

    try:
        logger.info("Virtual pipeline: building features from raw data")
        build_features_pipeline(features_save_path=paths["features_file"])

        logger.info("Training model")
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

        logger.info("Generating trading signals")
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

        logger.info("Running backtest")
        pnl_series, trading_metrics = run_backtest(
            signals=signals,
            da_prices=predictions_df["day_ahead_price"].values,
            system_sell_price=predictions_df["system_sell_price"].values,
            system_buy_price=predictions_df["system_buy_price"].values,
            timestamps=predictions_df["time"].values,
            cost_per_trade=transaction_cost,
            mid_prices=predictions_df["mid_price"].values,
            predicted_spreads=predictions_df["predicted_spread"].values,
            baseline_hedge_ratio=baseline_hedge_ratio,
            take_profit_pct=take_profit_pct,
            stop_loss_price_delta=stop_loss_price_delta,
            slippage=slippage,
        )

        results['pnl_series'] = pnl_series
        results['trading_metrics'] = trading_metrics

        logger.info("Calculating model metrics")
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

        if SAVE_OUTPUTS_DEFAULT:
            logger.info("Saving outputs")
            save_model(model, {
                'model_type':       model_type,
                'signal_threshold': signal_threshold,
                'n_features':       X_test.shape[1],
                'n_samples':        len(X_test),
                'features':         list(X_test.columns),
                'mode':             'virtual',
            }, paths)

            save_outputs(predictions_df, signals, pnl_series, paths)
            save_metrics(model_metrics, trading_metrics, paths)

        logger.info("Virtual pipeline completed successfully")
        print_pipeline_results(results)

        return results

    except Exception as e:
        logger.error(f"Virtual pipeline failed: {str(e)}")
        raise


def run_full_pipeline(mode: str = "virtual", config: dict | None = None) -> dict:
    """Run the trading pipeline.

    Args:
        mode:   'virtual' (ML spread-trading), 'bess' (battery storage), or 'all'.
        config: Experiment config dict loaded from YAML.
    """
    logger.info(f"Starting pipeline in '{mode}' mode")
    ensure_directories()

    if mode == "virtual":
        return _run_virtual_pipeline(config)
    elif mode == "bess":
        return _run_bess_pipeline(config)
    elif mode == "all":
        virtual_results = _run_virtual_pipeline(config)
        bess_results = _run_bess_pipeline(config)
        return {"virtual": virtual_results, "bess": bess_results}
    else:
        raise ValueError(f"Invalid mode: {mode}. Must be 'virtual', 'bess', or 'all'.")


def print_pipeline_results(results: dict):
    print("\n" + "=" * 60)
    print(f"ELECTRICITY TRADING PIPELINE RESULTS  (mode: {results['mode']})")
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
    results = run_full_pipeline()