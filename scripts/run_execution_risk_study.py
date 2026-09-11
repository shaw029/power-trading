"""Compare execution policies under common prospective book risk limits.

Uses saved signals; does not fit or select a new forecasting model or risk policy.
"""

from dataclasses import asdict
from pathlib import Path
import json
import logging
import sys

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backtest.engine import run_backtest_from_dataframe  # noqa: E402
from src.backtest.risk import BookRiskPolicy  # noqa: E402


def run_study(root: Path):
    cfg = yaml.safe_load((root / "configs/execution_risk_study.yaml").read_text())
    policy = BookRiskPolicy(**cfg["book_risk_policy"])
    best = json.loads((root / "artifacts/da_positioning/best_run.json").read_text())["best_run"]
    artifact = root / "artifacts/da_positioning" / best
    features = pd.read_parquet(artifact / "features/features.parquet")
    signals = pd.read_csv(artifact / "virtual/trading/signals.csv")
    signals["time"] = pd.to_datetime(signals["delivery_time"], utc=True)
    predictions = pd.read_csv(artifact / "virtual/trading/predictions.csv")
    predictions["time"] = pd.to_datetime(predictions["time"], utc=True)
    frame = (
        features[["time", "day_ahead_price", "system_sell_price", "system_buy_price", "mid_price"]]
        .merge(signals[["time", "signal", "predicted_spread"]], on="time", validate="one_to_one")
        .merge(predictions[["time", "split"]], on="time", validate="one_to_one")
        .sort_values("time")
    )
    price_cols = [
        "day_ahead_price",
        "system_sell_price",
        "system_buy_price",
        "mid_price",
        "predicted_spread",
    ]
    valid = np.isfinite(frame[price_cols]).all(axis=1)
    exclusions = frame.loc[~valid].copy()
    # Preserve the full calendar; all variants skip the same unpriceable signals.
    frame.loc[~valid, "signal"] = 0
    common = dict(
        starting_capital=cfg["starting_capital"],
        risk_pct=cfg["reference_notional_per_trade"],
        max_drawdown_pct=cfg["initial_capital_loss_floor_pct"],
        cost_per_trade=cfg["fee_gbp_per_mwh"],
        slippage=cfg["intraday_slippage_gbp_per_mwh"],
    )
    mid = dict(mid_price_col="mid_price", predicted_spread_col="predicted_spread")
    pure: dict[str, dict] = {
        f"{h:.0%} intraday / {1-h:.0%} imbalance": dict(
            **mid,
            baseline_hedge_ratio=h,
            take_profit_pct=float("inf"),
            stop_loss_price_delta=float("inf"),
        )
        for h in (0, 0.25, 0.5, 0.75, 1)
    }
    overlays: dict[str, dict] = {
        "Full imbalance": dict(baseline_hedge_ratio=0),
        "Systematic intraday unwind": dict(**mid, baseline_hedge_ratio=1),
        "Conditional TP/SL": dict(**mid, baseline_hedge_ratio=0),
        "50/50 with TP/SL remainder": dict(**mid, baseline_hedge_ratio=0.5),
    }
    report = {
        "selected_signal_run": best,
        "policy": cfg,
        "interpretation": "Post-review research design on previously inspected data; no new policy selected.",
        "missing_price_signal_periods_excluded": int(exclusions.signal.ne(0).sum()),
        "risk_policy": asdict(policy),
        "coverage": {},
        "scopes": {},
    }
    logger = logging.getLogger("src.backtest.engine")
    old_level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        for scope, mask in [
            ("development", frame["split"].eq("development")),
            ("retrospective_evaluation", frame["split"].ne("development")),
            ("full_150_day_replay", pd.Series(True, index=frame.index)),
        ]:
            data = frame.loc[mask].copy()
            scope_valid = valid.loc[data.index]
            dates = data.time.dt.tz_convert("Europe/London").dt.normalize()
            report["coverage"][scope] = {
                "scheduled_market_days": int(dates.nunique()),
                "market_days_with_common_prices": int(dates.loc[scope_valid].nunique()),
                "excluded_signal_periods": int(
                    exclusions.loc[exclusions.index.intersection(data.index)].signal.ne(0).sum()
                ),
            }
            results = {}
            for group, strategies, risk in [
                ("original_2pct", overlays, None),
                ("managed_overlays", overlays, policy),
                ("managed_pure_hedges", pure, policy),
            ]:
                records = []
                for name, kwargs in strategies.items():
                    out, m = run_backtest_from_dataframe(
                        data, **common, **kwargs, book_risk_policy=risk
                    )
                    market_day = out.time.dt.tz_convert("Europe/London").dt.normalize()
                    daily = out.groupby(market_day).pnl.sum()
                    ledger = m["risk_book_ledger"]
                    active = [row for row in ledger if row["gross_mwh"] > 0]
                    record = {
                        key: m[key]
                        for key in (
                            "total_pnl",
                            "sharpe_ratio",
                            "max_drawdown",
                            "max_drawdown_pct_peak",
                            "total_position_mwh",
                            "n_trades",
                            "n_signals_proposed",
                            "halt_details",
                        )
                    }
                    record.update(
                        strategy=name,
                        completed=m["halted_at_period"] is None,
                        days=len(daily),
                        daily_pnl_std=float(daily.std()),
                        worst_day_pnl=float(daily.min()),
                        mean_worst_5pct_days=float(
                            daily.nsmallest(max(1, int(np.ceil(0.05 * len(daily))))).mean()
                        ),
                        active_books=len(active) if risk is not None else None,
                        budget_paused_books=len(ledger) - len(active) if risk is not None else None,
                        last_traded_delivery_day=active[-1]["delivery_day"] if active else None,
                        min_drawdown_scale=min((x["drawdown_scale"] for x in ledger), default=1),
                        risk_book_ledger=ledger,
                    )
                    records.append(record)
                results[group] = records
            report["scopes"][scope] = results
    finally:
        logger.setLevel(old_level)
    dest = artifact / "virtual/trading/execution_risk_study.json"
    dest.write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    result = run_study(Path(__file__).resolve().parents[1])
    for scope, groups in result["scopes"].items():
        print(scope)
        for group, rows in groups.items():
            for row in rows:
                print(
                    group,
                    row["strategy"],
                    round(row["total_pnl"]),
                    round(row["sharpe_ratio"], 2),
                    "complete" if row["completed"] else "HALTED",
                    "active books",
                    row["active_books"],
                    "min size scale",
                    round(row["min_drawdown_scale"], 3),
                )
