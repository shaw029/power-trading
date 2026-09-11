"""End-to-end orchestration for both strategies.

Wires the stages together — download, preprocess, features, train, backtest —
and owns the experiment plumbing around them: where a run writes, what it saves,
and how a finished run is read back. The stage implementations live in
``src.data``, ``src.features``, ``src.models``, ``src.backtest`` and ``src.bess``;
nothing here does modelling of its own.

Two strategies run through it. ``_run_virtual_pipeline`` trades day-ahead
positions against imbalance; ``_run_bess_pipeline`` schedules a battery by LP and
re-optimises it intraday. They share the plumbing and almost nothing else.

The entry point is ``main.py``, which supplies the config and the mode. Calling
``run_full_pipeline()`` directly works too, but it then falls back to whatever
``configs/config.yaml`` holds.
"""

from src.data.market_calendar import complete_resample
import pandas as pd
import numpy as np
import logging
import json
import joblib
from datetime import datetime

# Import our custom modules
from src.data.download import (
    fetch_demand_forecast,
    fetch_wind_forecast,
    fetch_generation_actual,
    fetch_day_ahead_price,
    fetch_market_index_price,
    fetch_demand_actual,
    fetch_imbalance_price,
)
from src.data.preprocess import (
    merge_all,
    process_generation_mix,
    process_imbalance_price,
    process_day_ahead_price,
    process_market_index_price,
    process_demand_actual,
    process_wind_forecast,
    process_demand_forecast,
)
from src.features.build_features import build_features
from src.models.train import train_model
from src.models.signal import (
    generate_signal,
    build_daily_schedule,
    compute_execution_buffer,
    compute_volatility_threshold,
)
from src.backtest.engine import run_backtest
from src.utils.config import (
    ensure_directories,
    FEATURES_DATASET,
    MODEL_FILE,
    PREDICTIONS_FILE,
    SIGNALS_FILE,
    PNL_FILE,
    METRICS_FILE,
    MODEL_METADATA_FILE,
    CURRENT_VERSION,
    PROCESSED_DATA_DIR,
    DEFAULT_SIGNAL_THRESHOLD,
    SAVE_OUTPUTS_DEFAULT,
    PROJECT_ROOT,
    VERSIONED_FEATURES_DIR,
    VERSIONED_MODELS_DIR,
    VERSIONED_TRADING_DIR,
    get_periods,
    get_sources,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# A take-profit or stop-loss at or above this is a switch in the "off" position:
# no reachable price triggers it, so the position rides to imbalance settlement.
_GATE_DISABLED = 900.0


def setup_experiment_paths(config: dict | None = None, mode: str | None = None) -> dict:
    """Return a dict of Path objects for all experiment artifacts.

    Layout under artifacts/:
        artifacts/{strategy}/{run_name}/features/        — shared between modes
        artifacts/{strategy}/{run_name}/{mode}/model/    — model + metadata
        artifacts/{strategy}/{run_name}/{mode}/trading/  — predictions, signals, pnl, metrics

    When config is None, falls back to the static versioned paths from config.py.
    """
    if config is None:
        return {
            "features_dir": VERSIONED_FEATURES_DIR,
            "model_dir": VERSIONED_MODELS_DIR,
            "trading_dir": VERSIONED_TRADING_DIR,
            "features_file": FEATURES_DATASET,
            "model_file": MODEL_FILE,
            "metadata_file": MODEL_METADATA_FILE,
            "predictions_file": PREDICTIONS_FILE,
            "signals_file": SIGNALS_FILE,
            "pnl_file": PNL_FILE,
            "metrics_file": METRICS_FILE,
        }

    strategy = config["strategy"]
    run_name = config["run_name"]
    run_dir = PROJECT_ROOT / "artifacts" / strategy / run_name
    features_dir = run_dir / "features"
    mode_dir = run_dir / mode if mode else run_dir
    model_dir = mode_dir / "model"
    trading_dir = mode_dir / "trading"
    return {
        "features_dir": features_dir,
        "model_dir": model_dir,
        "trading_dir": trading_dir,
        "features_file": features_dir / "features.parquet",
        "model_file": model_dir / "model.joblib",
        "metadata_file": model_dir / "metadata.json",
        "predictions_file": trading_dir / "predictions.csv",
        "signals_file": trading_dir / "signals.csv",
        "pnl_file": trading_dir / "pnl.csv",
        "metrics_file": trading_dir / "metrics.json",
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


def build_features_pipeline(config, features_save_path=None):
    logger.info("Building features from raw data")

    periods = get_periods(config)
    sources = get_sources(config)
    full_start = min(str(p["start"]) for p in periods)
    full_end = max(str(p["end"]) for p in periods)

    try:
        # Step 1: Download raw data
        logger.info("Step 1: Downloading raw data")

        wind_df = fetch_wind_forecast(
            source=sources["wind_source"], start_date=full_start, end_date=full_end
        )
        generation_df = fetch_generation_actual(
            source=sources["generation_source"], start_date=full_start, end_date=full_end
        )
        price_df = fetch_day_ahead_price(
            source=sources["day_ahead_price_source"], start_date=full_start, end_date=full_end
        )
        mid_df = fetch_market_index_price(
            source=sources["market_index_source"], start_date=full_start, end_date=full_end
        )
        itsdo_df = fetch_demand_actual(
            source=sources["demand_actual_source"], start_date=full_start, end_date=full_end
        )
        b1770_df = fetch_imbalance_price(
            source=sources["imbalance_source"], start_date=full_start, end_date=full_end
        )

        demand_dfs = []
        for p in periods:
            demand_dfs.append(
                fetch_demand_forecast(
                    source=str(p["demand_source"]),
                    start_date=str(p["start"]),
                    end_date=str(p["end"]),
                )
            )
        demand_df = pd.concat(demand_dfs, ignore_index=True)

        # Step 2: Preprocess and merge
        logger.info("Step 2: Preprocessing and merging data")

        generation_processed = process_generation_mix(generation_df)
        b1770_processed = process_imbalance_price(b1770_df)
        price_processed = process_day_ahead_price(price_df)
        mid_processed = process_market_index_price(mid_df)
        itsdo_processed = process_demand_actual(itsdo_df)
        wind_processed = process_wind_forecast(wind_df)
        demand_processed = process_demand_forecast(demand_df)

        processed_df = merge_all(
            generation_mix=generation_processed,
            imbalance_price=b1770_processed,
            day_ahead_price=price_processed,
            market_index_price=mid_processed,
            demand_actual=itsdo_processed,
            wind_forecast=wind_processed,
            demand_forecast=demand_processed,
        )

        # Step 3: Build features
        logger.info("Step 3: Building features")
        # Data-period end is exclusive; downloader margins are only for source context.
        time = pd.to_datetime(processed_df["time"], utc=True)
        in_period = pd.Series(False, index=processed_df.index)
        for period in periods:
            in_period |= (time >= pd.Timestamp(str(period["start"]), tz="Europe/London")) & (
                time < pd.Timestamp(str(period["end"]), tz="Europe/London")
            )
        processed_df = processed_df[in_period].reset_index(drop=True)
        features_df = build_features(processed_df, save_path=features_save_path)

        logger.info(f"Features pipeline completed successfully. Final shape: {features_df.shape}")

    except Exception as e:
        logger.error(f"Features pipeline failed: {str(e)}")
        raise


def save_model(model, metadata: dict, paths: dict):
    metadata["saved_at"] = datetime.now().isoformat()
    paths["model_dir"].mkdir(parents=True, exist_ok=True)
    joblib.dump(model, paths["model_file"])
    logger.info(f"Model saved to {paths['model_file']}")
    with open(paths["metadata_file"], "w") as f:
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


def save_outputs(
    predictions_df: pd.DataFrame, signals: np.ndarray, pnl_series: np.ndarray, paths: dict
):
    timestamps = predictions_df["time"].values

    _ts = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))
    _london = _ts.tz_convert("Europe/London")
    auction_times = (
        _london.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=11)
    ).tz_convert("UTC")

    signals_df = pd.DataFrame(
        {
            "auction_time": auction_times,
            "delivery_time": timestamps,
            "predicted_spread": predictions_df["predicted_spread"].values,
            "signal": signals,
            "direction": pd.array(signals, dtype=int),
        }
    )
    signals_df["direction"] = signals_df["direction"].map({1: "BUY", -1: "SELL", 0: "NEUTRAL"})

    paths["trading_dir"].mkdir(parents=True, exist_ok=True)
    # Provenance travels with the prediction: which fold produced it, where that
    # fold's training data ended, and whether the row belongs to the development
    # period or the untouched holdout. Without the split column a downstream
    # notebook cannot tell the two apart, and tuning anything on the blended
    # series spends the holdout on the search it exists to be independent of.
    _pred_cols = [
        c
        for c in ("time", "actual_spread", "predicted_spread", "fold_id", "train_end", "split")
        if c in predictions_df.columns
    ]
    predictions_df[_pred_cols].to_csv(paths["predictions_file"], index=False)
    logger.info(f"Predictions saved to {paths['predictions_file']}")

    signals_df.to_csv(paths["signals_file"], index=False)
    logger.info(f"Signals saved to {paths['signals_file']}")

    pd.DataFrame({"time": timestamps, "pnl": pnl_series}).to_csv(paths["pnl_file"], index=False)
    logger.info(f"PnL saved to {paths['pnl_file']}")


def save_metrics(
    model_metrics: dict,
    trading_metrics: dict,
    paths: dict,
    split_metrics: dict | None = None,
):
    """Persist model and trading metrics for one run.

    ``split_metrics`` carries the development and holdout results separately.
    They are saved alongside the blended figures rather than instead of them,
    because a consumer that ranks runs must use ``development`` — the holdout
    exists to be scored once, by the winner, and any selection that reads it has
    spent it.
    """
    metrics = {
        "timestamp": datetime.now().isoformat(),
        "model_performance": model_metrics,
        "trading_performance": trading_metrics,
    }
    if split_metrics:
        metrics["trading_performance_by_split"] = split_metrics
    paths["trading_dir"].mkdir(parents=True, exist_ok=True)
    with open(paths["metrics_file"], "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info(f"Metrics saved to {paths['metrics_file']}")


def save_bess_outputs(results_df: pd.DataFrame, config: dict, paths: dict):
    trading_dir = paths["trading_dir"]
    trading_dir.mkdir(parents=True, exist_ok=True)

    results_df.to_csv(trading_dir / "pnl.csv", index=False)
    logger.info(f"BESS PnL saved to {trading_dir / 'pnl.csv'}")

    net = results_df["net_pnl"]
    avg_daily = float(net.mean())
    daily = (
        pd.Series(net.to_numpy(), index=pd.to_datetime(results_df["date"]))
        .sort_index()
        .asfreq("D", fill_value=0)
    )
    opening_equity = 50_000.0 + daily.cumsum().shift(1, fill_value=0)
    daily_returns = daily / opening_equity
    std_daily = float(daily_returns.std(ddof=1)) if len(daily) > 1 else 0.0
    sharpe = float(daily_returns.mean()) / std_daily * np.sqrt(365) if std_daily > 0 else 0.0

    cumulative = net.cumsum()
    max_drawdown = float((cumulative - cumulative.cummax().clip(lower=0)).min())

    bess_cfg = config["bess"]
    total_degradation = float(results_df["degradation_cost"].sum())
    # A cycle is one full discharge equivalent (discharged energy / nameplate),
    # matching the target_daily_cycles cap and the fleet estimates. Older runs
    # without the discharge column fall back to a throughput-derived estimate.
    if "discharge_mwh" in results_df.columns:
        total_cycles = float(results_df["discharge_mwh"].sum()) / bess_cfg["capacity_mwh"]
    else:
        deg_cost = bess_cfg["degradation_cost_per_mwh"]
        throughput = total_degradation / deg_cost if deg_cost > 0 else 0.0
        total_cycles = throughput / (2 * bess_cfg["capacity_mwh"])

    metrics = {
        "total_da_revenue": float(results_df["da_revenue"].sum()),
        "total_intraday_pnl": float(results_df["intraday_pnl"].sum()),
        "total_execution_costs_paid": float(results_df["execution_costs_paid"].sum()),
        "total_intraday_throughput_mwh": float(results_df["intraday_throughput_mwh"].sum()),
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
    from src.models.train import train_da_price_model

    bess_cfg = config["bess"]
    paths = setup_experiment_paths(config, mode="bess")

    results = {
        "timestamp": datetime.now().isoformat(),
        "mode": "bess",
        "paths": paths,
    }

    # Step 1: Build features if needed
    if not paths["features_file"].exists():
        logger.info("BESS pipeline: building features from raw data")
        build_features_pipeline(config, features_save_path=paths["features_file"])
    else:
        logger.info("BESS pipeline: reusing existing features at %s", paths["features_file"])

    # Step 2: Train DA price model
    logger.info("BESS pipeline: training DA price model")
    model_cfg = config.get("model", {})
    val_cfg = config.get("validation", {})
    da_model, da_predictions_df, X_test = train_da_price_model(
        features_path=str(paths["features_file"]),
        model_type=model_cfg.get("type", "xgboost"),
        model_params=model_cfg.get("hyperparameters"),
        validation_type=val_cfg.get("type", "walk_forward"),
        wf_train_days=val_cfg.get("train_days", 200),
        wf_test_days=val_cfg.get("test_days", 30),
        wf_step_days=val_cfg.get("step_days", 30),
        holdout_days=val_cfg.get("holdout_days", 0),
    )

    save_model(
        da_model,
        {
            "model_type": model_cfg.get("type", "xgboost"),
            "target": "day_ahead_price",
            "n_features": X_test.shape[1],
            "features": list(X_test.columns),
            "mode": "bess",
        },
        paths,
    )

    # Step 3: Take the walk-forward predictions themselves, indexed by delivery
    # period.
    #
    # These are the only genuinely out-of-sample DA forecasts in the run: each
    # was produced by the fold whose training window ended before its delivery
    # date. Re-predicting these dates with `da_model` — the *last* fitted fold —
    # scores 5,746 of 7,182 periods with a model that trained on them, because
    # the final fold's training window (2018-05-02 to 2018-11-18) swallows four
    # of the five test folds. Filtering to dates that were once called OOS does
    # not make a later model's predictions OOS.
    da_predictions_df = da_predictions_df.copy()
    da_predictions_df["time"] = pd.to_datetime(da_predictions_df["time"], utc=True)
    oos_forecast = (
        da_predictions_df.set_index("time")["predicted_da_price"].sort_index().astype(float)
    )
    if oos_forecast.empty:
        raise RuntimeError(
            "DA price model produced no out-of-sample predictions, so there is "
            "nothing to dispatch against. Check the walk-forward window fits "
            "inside the feature date range."
        )

    oos_dates = set(oos_forecast.index.tz_convert("Europe/London").date)

    if "fold_id" in da_predictions_df.columns:
        logger.info(
            "BESS pipeline: dispatching on %d fold-specific forecasts across %d folds",
            len(oos_forecast),
            da_predictions_df["fold_id"].nunique(),
        )

    # Step 4: Load price data for the days actually being dispatched.
    #
    # This window comes from the forecast, not from the features frame. Bounding
    # it by the features meant fetching prices for every row the parquet happened
    # to contain — and a features file can legitimately span far more than the
    # configured study window, because two cache readers used to ignore their
    # date arguments and return everything on disk. A 2018 run then asked
    # ENTSO-E for day-ahead prices through 2026, which for GB do not exist
    # post-Brexit: thousands of failing requests, one per day, before the run
    # could reach the dispatch loop.
    feat_start = oos_forecast.index.min().strftime("%Y-%m-%d")
    feat_end = (oos_forecast.index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    logger.info("BESS pipeline: loading and processing price data (%s → %s)", feat_start, feat_end)
    da_processed = process_day_ahead_price(
        fetch_day_ahead_price(start_date=feat_start, end_date=feat_end)
    )
    mid_processed = process_market_index_price(
        fetch_market_index_price(start_date=feat_start, end_date=feat_end)
    )

    duration_h = bess_cfg.get("resolution_h", 1.0)
    resample_freq = f"{int(duration_h * 60)}min"

    # Persist the native settlement inputs as well as the forecasts. Consumers
    # must not substitute the feature merge's filled price columns for raw coverage.
    native_prices = da_processed.join(mid_processed, how="outer").sort_index()
    native_prices.index.name = "time"
    paths["trading_dir"].mkdir(parents=True, exist_ok=True)
    native_prices.to_csv(paths["trading_dir"] / "dispatch_prices.csv")
    prices = complete_resample(native_prices, resample_freq).dropna()

    asset = BESSAsset(
        capacity_mwh=bess_cfg["capacity_mwh"],
        power_mw=bess_cfg["power_mw"],
        charge_efficiency=bess_cfg["charge_efficiency"],
        discharge_efficiency=bess_cfg["discharge_efficiency"],
        degradation_cost_per_mwh=bess_cfg["degradation_cost_per_mwh"],
        initial_soc_pct=bess_cfg["initial_soc_pct"],
        min_soc_pct=bess_cfg.get("min_soc_pct", 0.0),
        max_soc_pct=bess_cfg.get("max_soc_pct", 1.0),
    )

    # Step 5: Daily BESS simulation using ML forecasts
    # Forecast onto the dispatch grid once, by timestamp. The prediction series
    # is half-hourly and the battery runs hourly, so the two are aligned by the
    # clock rather than by position — pairing arrays by index silently shifts
    # every later period of a day by one slot as soon as a single settlement
    # period is missing upstream, which happens on 16 days of the 2018 sample.
    forecast_grid = complete_resample(oos_forecast, resample_freq)

    daily_results = []
    skipped: dict[str, int] = {}
    prev_soc_pct: float | None = None

    # Group by the *London* market date. The battery's day, the auction's day and
    # the feature vintage are all GB market days; grouping prices by UTC date
    # instead put the 1 August book on a window starting 31 July 23:00 UTC and
    # paired it with London-dated features, so through BST the two were an hour
    # apart. It also made the 23/24/25-period tolerance meaningless: a UTC day
    # always has exactly 24 hours, so that check could never see a DST day — it
    # only ever waved through days with data missing.
    london_date = prices.index.tz_convert("Europe/London").normalize()
    for date, day_df in prices.groupby(london_date):
        market_date = date.date()
        if market_date not in oos_dates:
            continue

        # A GB market day is 23, 24 or 25 hours long depending on where it sits
        # relative to the clock change; anything else is missing data, not DST.
        # The next boundary is the next *calendar* midnight, so it is found in
        # wall-clock terms and re-localised — adding 24 absolute hours would land
        # at 01:00 on a spring-forward day and demand an hour that never existed.
        next_midnight = (date.tz_localize(None) + pd.Timedelta(days=1)).tz_localize(
            "Europe/London", ambiguous=True, nonexistent="shift_forward"
        )
        expected = pd.date_range(
            start=date, end=next_midnight, freq=resample_freq, inclusive="left"
        ).tz_convert("UTC")
        if not day_df.index.tz_convert("UTC").equals(expected):
            skipped["incomplete_day"] = skipped.get("incomplete_day", 0) + 1
            continue

        forecast_day = forecast_grid.reindex(expected)
        if forecast_day.isna().any():
            skipped["incomplete_forecast"] = skipped.get("incomplete_forecast", 0) + 1
            continue
        forecast = forecast_day.tolist()

        carry_soc = prev_soc_pct if prev_soc_pct is not None else bess_cfg["initial_soc_pct"]
        asset.reset(soc_pct=carry_soc)
        da_prices = day_df["day_ahead_price"].tolist()
        schedule = optimize_da_schedule(
            da_price_forecast=forecast,
            asset=asset,
            duration_h=duration_h,
            target_daily_cycles=bess_cfg.get("target_daily_cycles"),
            commit_fraction=bess_cfg.get("da_commit_fraction", 1.0),
        )
        result = run_intraday_session(
            da_schedule=schedule,
            da_price_actual=da_prices,
            mid_prices=day_df["mid_price"].tolist(),
            asset=asset,
            config=bess_cfg,
        )
        prev_soc_pct = asset.soc_pct
        daily_results.append(
            {
                "date": market_date,
                "da_revenue": result["benchmark_da_revenue"],
                "intraday_pnl": result["intraday_da_improvement"],
                "execution_costs_paid": result["execution_costs_paid"],
                "degradation_cost": result["total_degradation_cost"],
                "intraday_throughput_mwh": result["accumulated_intraday_throughput_mwh"],
                "discharge_mwh": sum(
                    e["final_mw"] * duration_h for e in result["dispatch_log"] if e["final_mw"] > 0
                ),
                "net_pnl": result["net_pnl"],
            }
        )

    # Persist the forecast the dispatch actually ran on, with its provenance.
    # Without this artifact every downstream consumer has to re-derive a forecast
    # from the saved final estimator — which is the leak this pipeline was fixed
    # to remove, reintroduced one notebook at a time.
    forecast_out = da_predictions_df.copy()
    forecast_out = forecast_out[
        [
            c
            for c in (
                "time",
                "actual_da_price",
                "predicted_da_price",
                "feature_imputed",
                "fold_id",
                "train_end",
                "split",
            )
            if c in forecast_out.columns
        ]
    ]
    paths["trading_dir"].mkdir(parents=True, exist_ok=True)
    forecast_out.to_csv(paths["trading_dir"] / "da_forecast.csv", index=False)
    logger.info(
        "BESS DA forecast saved to %s (%d rows)",
        paths["trading_dir"] / "da_forecast.csv",
        len(forecast_out),
    )

    if skipped:
        logger.warning(
            "BESS simulation skipped %d day(s) for incomplete coverage: %s",
            sum(skipped.values()),
            skipped,
        )

    results_df = pd.DataFrame(daily_results)
    if results_df.empty:
        raise RuntimeError(
            "BESS simulation produced no results — no OOS days matched the prices date range. "
            "Check that the features parquet and price data cover the same period."
        )
    save_bess_outputs(results_df, config, paths)
    results["results_df"] = results_df

    logger.info("BESS pipeline completed successfully")
    return results


def _run_virtual_pipeline(config: dict | None = None, skip_features: bool = False) -> dict:
    signal_threshold = config["signal"]["threshold"] if config else DEFAULT_SIGNAL_THRESHOLD
    top_n = config["signal"]["top_n"] if config else 5
    vol_multiplier = config["signal"].get("vol_multiplier", 1.0) if config else 1.0
    vol_window = config["signal"].get("vol_window", 336) if config else 336
    transaction_cost = config["signal"].get("transaction_cost", 0.0) if config else 0.0
    baseline_hedge_ratio = (
        config.get("execution", {}).get("baseline_hedge_ratio", 0.15) if config else 0.15
    )
    take_profit_pct = config.get("execution", {}).get("take_profit_pct", 0.90) if config else 0.90
    stop_loss_price_delta = (
        config.get("execution", {}).get("stop_loss_price_delta", 5.00) if config else 5.00
    )
    # The signal cost hurdle already treats >=900 as a disabled-gate sentinel.
    # Apply the same interpretation to fills: a finite 999 threshold otherwise
    # still fires on an extreme price and charges an unbudgeted intraday exit.
    if take_profit_pct >= _GATE_DISABLED:
        take_profit_pct = float("inf")
    if stop_loss_price_delta >= _GATE_DISABLED:
        stop_loss_price_delta = float("inf")
    slippage = config.get("execution", {}).get("slippage", 2.00) if config else 2.00
    model_type = config["model"]["type"] if config else "xgboost"
    model_params = config["model"]["hyperparameters"] if config else None
    val_type = config["validation"]["type"] if config else "walk_forward"
    wf_train_days = config["validation"]["train_days"] if config else 200
    wf_test_days = config["validation"]["test_days"] if config else 30
    wf_step_days = config["validation"]["step_days"] if config else 30
    holdout_days = config["validation"].get("holdout_days", 0) if config else 0

    paths = setup_experiment_paths(config, mode="virtual")

    results = {
        "timestamp": datetime.now().isoformat(),
        "mode": "virtual",
        "signal_threshold": signal_threshold,
        "paths": paths,
    }

    try:
        if skip_features:
            if not paths["features_file"].exists():
                raise FileNotFoundError(
                    f"--skip-features requires an existing features file: {paths['features_file']}"
                )
            logger.info("Skipping feature build, retraining on existing features")
        else:
            logger.info("Virtual pipeline: building features from raw data")
            build_features_pipeline(config, features_save_path=paths["features_file"])

        logger.info("Training model")
        from src.utils.provenance import fingerprint
        from pathlib import Path

        cache_dir = (config or {}).get("training_cache_dir")
        cached_fit = None
        if cache_dir:
            cache_key = fingerprint(
                Path(__file__).resolve().parents[1],
                {
                    "model": (config or {}).get("model"),
                    "validation": (config or {}).get("validation"),
                },
                features=paths["features_file"],
            )
            cached_fit = Path(cache_dir) / f"{cache_key}.joblib"
        if cached_fit is not None and cached_fit.exists():
            model, predictions_df, X_test = joblib.load(cached_fit)
        else:
            model, predictions_df, X_test = train_model(
                features_path=str(paths["features_file"]),
                model_type=model_type,
                model_params=model_params,
                validation_type=val_type,
                wf_train_days=wf_train_days,
                wf_test_days=wf_test_days,
                wf_step_days=wf_step_days,
                holdout_days=holdout_days,
                evaluate_holdout=(config or {}).get("validation", {}).get("evaluate_holdout", True),
            )
            if cached_fit is not None:
                cached_fit.parent.mkdir(parents=True, exist_ok=True)
                joblib.dump((model, predictions_df, X_test), cached_fit)

        results["model"] = model
        results["predictions_df"] = predictions_df
        results["X_test"] = X_test

        logger.info("Generating trading signals")
        # Slippage belongs in the hurdle only when the position can actually be
        # closed intraday. With no passive slice and the TP/SL gate wide open,
        # every position rides to imbalance cash-out and never crosses a spread,
        # so charging it a spread-crossing cost would gate out trades that never
        # pay one. Deriving the buffer from the execution settings keeps the
        # signal gate and the execution model describing the same strategy.
        exits_intraday = baseline_hedge_ratio > 0.0 or (
            take_profit_pct < _GATE_DISABLED or stop_loss_price_delta < _GATE_DISABLED
        )
        execution_buffer = compute_execution_buffer(
            transaction_cost=transaction_cost,
            slippage=slippage if exits_intraday else 0.0,
        )
        vol_threshold = compute_volatility_threshold(
            system_price=predictions_df["system_buy_price"].values,
            day_ahead_price=predictions_df["day_ahead_price"].values,
            window=vol_window,
        )
        raw_signals = generate_signal(
            predicted_spread=predictions_df["predicted_spread"].values,
            execution_buffer=execution_buffer,
            threshold=signal_threshold,
            vol_threshold=vol_threshold,
            vol_multiplier=vol_multiplier,
        )
        schedule_df, signals = build_daily_schedule(
            predicted_spread=predictions_df["predicted_spread"].values,
            signals=raw_signals,
            timestamps=predictions_df["time"].values,
            top_n=top_n,
        )

        results["signals"] = signals
        results["schedule_df"] = schedule_df

        logger.info("Running backtest")

        def _backtest(mask=None):
            sub = predictions_df if mask is None else predictions_df[mask]
            sig = signals if mask is None else signals[mask.values]
            if len(sub) == 0:
                return None, None
            return run_backtest(
                signals=sig,
                da_prices=sub["day_ahead_price"].values,
                system_sell_price=sub["system_sell_price"].values,
                system_buy_price=sub["system_buy_price"].values,
                timestamps=sub["time"].values,
                cost_per_trade=transaction_cost,
                mid_prices=sub["mid_price"].values,
                predicted_spreads=sub["predicted_spread"].values,
                baseline_hedge_ratio=baseline_hedge_ratio,
                take_profit_pct=take_profit_pct,
                stop_loss_price_delta=stop_loss_price_delta,
                slippage=slippage,
            )

        pnl_series, trading_metrics = _backtest()

        # Development and retrospective evaluation are reported apart. Every
        # hyperparameter, signal setting and execution parameter in this run was
        # picked by reading development results, so quoting a single blended
        # curve as "out-of-sample" would smuggle the selection back in.
        split_results: dict = {}
        if "split" in predictions_df.columns:
            for split_name in ("development", "holdout"):
                mask = predictions_df["split"] == split_name
                if not mask.any():
                    continue
                _, split_metrics = _backtest(mask)
                results[f"trading_metrics_{split_name}"] = split_metrics
                split_results[split_name] = split_metrics
                logger.info(
                    "  %-12s %d trades | PnL £%s | Sharpe %.3f",
                    split_name + ":",
                    split_metrics["n_trades"],
                    f"{split_metrics['total_pnl']:,.0f}",
                    split_metrics["sharpe_ratio"],
                )

        results["pnl_series"] = pnl_series
        results["trading_metrics"] = trading_metrics

        logger.info("Calculating model metrics")
        from sklearn.metrics import mean_absolute_error, mean_squared_error

        mae = mean_absolute_error(
            predictions_df["actual_spread"], predictions_df["predicted_spread"]
        )
        rmse = np.sqrt(
            mean_squared_error(predictions_df["actual_spread"], predictions_df["predicted_spread"])
        )

        actual = predictions_df["actual_spread"].values
        predicted = predictions_df["predicted_spread"].values
        directional_accuracy = float(np.mean(np.sign(actual) == np.sign(predicted)))

        # Forecast accuracy per split. The blended `mae` below spans development
        # AND holdout, so ranking candidates on it reads the holdout during
        # hyperparameter selection — the split has to exist here, not only on the
        # trading metrics, or notebook 01's model tournament cannot avoid it.
        by_split: dict = {}
        if "split" in predictions_df.columns:
            for name, part in predictions_df.groupby("split"):
                by_split[str(name)] = {
                    "mae": float(
                        mean_absolute_error(part["actual_spread"], part["predicted_spread"])
                    ),
                    "rmse": float(
                        np.sqrt(mean_squared_error(part["actual_spread"], part["predicted_spread"]))
                    ),
                    "directional_accuracy": float(
                        np.mean(np.sign(part["actual_spread"]) == np.sign(part["predicted_spread"]))
                    ),
                    "n_rows": int(len(part)),
                }

        ts = predictions_df["time"].values
        model_metrics = {
            "mae": mae,
            "rmse": rmse,
            "directional_accuracy": directional_accuracy,
            # Blended figures above are exploratory only; select on this.
            "by_split": by_split,
            "test_period_start": str(pd.to_datetime(ts[0], utc=True)),
            "test_period_end": str(pd.to_datetime(ts[-1], utc=True)),
            "test_n_periods": int(len(predictions_df)),
        }
        results["model_metrics"] = model_metrics

        if SAVE_OUTPUTS_DEFAULT:
            logger.info("Saving outputs")
            save_model(
                model,
                {
                    "model_type": model_type,
                    "signal_threshold": signal_threshold,
                    "n_features": X_test.shape[1],
                    "n_samples": len(X_test),
                    "features": list(X_test.columns),
                    "mode": "virtual",
                },
                paths,
            )

            save_outputs(predictions_df, signals, pnl_series, paths)
            save_metrics(model_metrics, trading_metrics, paths, split_results)

        logger.info("Virtual pipeline completed successfully")
        print_pipeline_results(results)

        return results

    except Exception as e:
        logger.error(f"Virtual pipeline failed: {str(e)}")
        raise


def _run_download(config: dict) -> dict:
    """Fetch all raw data sources and write them to the per-day cache."""
    logger.info("Download mode: fetching all raw data sources")

    periods = get_periods(config)
    sources = get_sources(config)
    full_start = min(str(p["start"]) for p in periods)
    full_end = max(str(p["end"]) for p in periods)

    fetch_wind_forecast(source=sources["wind_source"], start_date=full_start, end_date=full_end)
    fetch_generation_actual(
        source=sources["generation_source"], start_date=full_start, end_date=full_end
    )
    fetch_day_ahead_price(
        source=sources["day_ahead_price_source"], start_date=full_start, end_date=full_end
    )
    fetch_market_index_price(
        source=sources["market_index_source"], start_date=full_start, end_date=full_end
    )
    fetch_demand_actual(
        source=sources["demand_actual_source"], start_date=full_start, end_date=full_end
    )
    fetch_imbalance_price(
        source=sources["imbalance_source"], start_date=full_start, end_date=full_end
    )

    for p in periods:
        fetch_demand_forecast(
            source=str(p["demand_source"]),
            start_date=str(p["start"]),
            end_date=str(p["end"]),
        )

    logger.info("Download complete")
    return {"mode": "download"}


def _run_features(config: dict) -> dict:
    """Download raw data, preprocess, and build the feature set — stop before training."""
    paths = setup_experiment_paths(config)
    logger.info("Features mode: building features from raw data")
    build_features_pipeline(config, features_save_path=paths["features_file"])
    logger.info("Features written to %s", paths["features_file"])
    return {"mode": "features", "features_file": paths["features_file"]}


def run_full_pipeline(
    mode: str | None = None, config: dict | None = None, skip_features: bool = False
) -> dict:
    """Run the trading pipeline.

    Args:
        mode:   'download'  — fetch raw data only
                'features'  — download + preprocess + build features
                'model'     — train + backtest on existing features (skip download/features)
                'virtual'   — full ML spread-trading pipeline
                'bess'      — full battery storage pipeline
                'all'       — virtual + bess sequentially
                Defaults to config['strategy_type'] when omitted, then 'virtual'.
        config: Experiment config dict loaded from YAML.
        skip_features: If True, skip feature building (alias for mode='model').
    """
    effective_mode = mode or (config or {}).get("strategy_type", "virtual")
    logger.info(f"Starting pipeline in '{effective_mode}' mode")
    ensure_directories()

    if effective_mode == "download":
        if config is None:
            raise ValueError("'download' mode requires a config dict.")
        return _run_download(config)
    elif effective_mode == "features":
        if config is None:
            raise ValueError("'features' mode requires a config dict.")
        return _run_features(config)
    elif effective_mode == "model":
        return _run_virtual_pipeline(config, skip_features=True)
    elif effective_mode == "virtual":
        return _run_virtual_pipeline(config, skip_features=skip_features)
    elif effective_mode == "bess":
        if config is None:
            raise ValueError("'bess' mode requires a config dict.")
        return _run_bess_pipeline(config)
    elif effective_mode == "all":
        if config is None:
            raise ValueError("'all' mode requires a config dict.")
        virtual_results = _run_virtual_pipeline(config, skip_features=skip_features)
        bess_results = _run_bess_pipeline(config)
        return {"virtual": virtual_results, "bess": bess_results}
    else:
        raise ValueError(
            f"Invalid mode: {effective_mode!r}. "
            "Must be 'download', 'features', 'model', 'virtual', 'bess', or 'all'."
        )


def print_pipeline_results(results: dict):
    print("\n" + "=" * 60)
    print(f"ELECTRICITY TRADING PIPELINE RESULTS  (mode: {results['mode']})")
    print("=" * 60)

    mm = results["model_metrics"]
    tm = results["trading_metrics"]
    ds = tm.get("daily_summary", {})

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
    print(
        f"  Profit factor:  {tm['profit_factor']:>11.2f}"
        if tm["profit_factor"] is not None
        else f"  Profit factor:  {'n/a':>11}"
    )
    print(f"  Sharpe ratio:   {tm['sharpe_ratio']:>11.3f}")
    print(f"  Max drawdown:  £{tm['max_drawdown']:>12,.2f}")
    print(f"  Avg win:       £{tm['avg_win']:>12,.2f}")
    print(f"  Avg loss:      £{tm['avg_loss']:>12,.2f}")
    if tm.get("halted_at_period") is not None:
        print(f"  *** Simulation halted at period {tm['halted_at_period']} (drawdown limit) ***")

    if ds:
        print("\nDAILY PnL SUMMARY:")
        print(f"  Mean daily:    £{ds['mean_daily_pnl']:>12,.0f}")
        print(f"  Std daily:     £{ds['std_daily_pnl']:>12,.0f}")
        print(f"  Best day:      £{ds['best_day_pnl']:>12,.0f}")
        print(f"  Worst day:     £{ds['worst_day_pnl']:>12,.0f}")
        print(
            f"  Pos/Neg days:   {ds['positive_days']} / {ds['negative_days']}  (of {ds['total_days']})"
        )

    sig = tm["signal_distribution"]
    print("\nSIGNAL DISTRIBUTION (after Top-5 filter):")
    print(f"  Long:    {sig['long']}")
    print(f"  Short:   {sig['short']}")
    print(f"  Neutral: {sig['neutral']}")

    if "schedule_df" in results and not results["schedule_df"].empty:
        sched = results["schedule_df"]
        print(
            f"\nDAILY BIDDING SCHEDULE ({len(sched)} trade slots across {sched['market_date'].nunique()} days):"
        )
        print(sched.head(10).to_string(index=False))
        if len(sched) > 10:
            print(f"  … ({len(sched) - 10} more rows)")

    if SAVE_OUTPUTS_DEFAULT:
        p = results.get("paths", {})
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
                results["metrics"] = json.load(f)

        model = load_model(paths)
        if model:
            results["model"] = model

        if paths["predictions_file"].exists():
            results["predictions_df"] = pd.read_csv(paths["predictions_file"])

        if paths["signals_file"].exists():
            results["signals_df"] = pd.read_csv(paths["signals_file"])

        if paths["pnl_file"].exists():
            results["pnl_df"] = pd.read_csv(paths["pnl_file"])

        logger.info(f"Loaded results from {paths['trading_dir']}")
        return results

    except Exception as e:
        logger.error(f"Failed to load results: {str(e)}")
        return {}
