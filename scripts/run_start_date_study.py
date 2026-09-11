"""Account restart sensitivity with frozen signals and coverage-selected horizons.

Writes separate artifacts; does not change notebook 02 or the README showcase.
"""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import logging
import sys

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backtest.risk import BookRiskPolicy  # noqa: E402
from src.evaluation.start_dates import coverage_start_windows, replay_account_window  # noqa: E402


def run_study(root: Path, *, figures: dict | None = None) -> dict:
    """Save result ledgers; optionally collect figures in memory for a notebook."""
    config_path = root / "configs/execution_risk_study.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    policy = BookRiskPolicy(**cfg["book_risk_policy"])
    best = json.loads((root / "artifacts/da_positioning/best_run.json").read_text())["best_run"]
    base = root / "artifacts/da_positioning" / best
    features_path = base / "features/features.parquet"
    signal_path = base / "virtual/trading/signals.csv"
    prediction_path = base / "virtual/trading/predictions.csv"
    features = pd.read_parquet(features_path)
    signals = pd.read_csv(signal_path)
    signals["time"] = pd.to_datetime(signals.delivery_time, utc=True)
    predictions = pd.read_csv(prediction_path)
    predictions["time"] = pd.to_datetime(predictions.time, utc=True)
    frame = (
        features[["time", "day_ahead_price", "system_sell_price", "system_buy_price", "mid_price"]]
        .merge(signals[["time", "signal", "predicted_spread"]], on="time", validate="one_to_one")
        .merge(predictions[["time", "split"]], on="time", validate="one_to_one")
        .sort_values("time")
    )
    finite = np.isfinite(
        frame[
            [
                "day_ahead_price",
                "system_sell_price",
                "system_buy_price",
                "mid_price",
                "predicted_spread",
            ]
        ]
    ).all(axis=1)
    frame["excluded_signal"] = ~finite & frame.signal.ne(0)
    frame.loc[~finite, "signal"] = 0
    starts = [f"2018-{month:02d}-01" for month in range(7, 12)]
    horizon, windows = coverage_start_windows(frame["time"], starts)
    strict_horizon, strict_windows = coverage_start_windows(frame.loc[finite, "time"], starts)
    assert [w["actual_start"] for w in windows] == [w["actual_start"] for w in strict_windows]
    year_end = pd.Timestamp("2019-01-01", tz="Europe/London")
    common = dict(
        starting_capital=cfg["starting_capital"],
        risk_pct=cfg["reference_notional_per_trade"],
        max_drawdown_pct=cfg["initial_capital_loss_floor_pct"],
        cost_per_trade=cfg["fee_gbp_per_mwh"],
        slippage=cfg["intraday_slippage_gbp_per_mwh"],
    )
    mid = dict(mid_price_col="mid_price", predicted_spread_col="predicted_spread")
    strategies: dict[str, dict] = {
        "Full imbalance": dict(baseline_hedge_ratio=0),
        "Systematic intraday unwind": dict(**mid, baseline_hedge_ratio=1),
        "Conditional TP/SL": dict(**mid, baseline_hedge_ratio=0),
        "50/50 with TP/SL": dict(**mid, baseline_hedge_ratio=0.5),
        "Pure 50/50 hedge": dict(
            **mid,
            baseline_hedge_ratio=0.5,
            take_profit_pct=float("inf"),
            stop_loss_price_delta=float("inf"),
        ),
    }
    records = []
    curves: dict = {}
    daily_records = []
    logger = logging.getLogger("src.backtest.engine")
    previous_level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        for window in windows:
            start = window["actual_start"]
            for mode, end in [
                ("equal_window", window["equal_end_exclusive"]),
                ("strict_price_window", start + pd.DateOffset(days=strict_horizon)),
                ("to_year_end", year_end),
            ]:
                selection = frame.time.ge(start) & frame.time.lt(end)
                sliced = frame.loc[selection]
                dates = sliced.time.dt.tz_convert("Europe/London").dt.normalize()
                calendar = pd.date_range(start, end, freq="D", inclusive="left")
                covered_days = dates.loc[finite.loc[sliced.index]].nunique()
                for name, risk in [("original_2pct", None), ("book_risk_managed", policy)]:
                    for strategy, kwargs in strategies.items():
                        out, metrics = replay_account_window(
                            frame, start, end, **common, **kwargs, book_risk_policy=risk
                        )
                        day = out.time.dt.tz_convert("Europe/London").dt.normalize()
                        observed_daily = out.groupby(day).pnl.sum()
                        # Unscored dates remain explicit idle dates for this saved-signal replay.
                        # Coverage flags keep them distinct from days with forecasts and no trades.
                        daily = observed_daily.reindex(calendar, fill_value=0.0)
                        opening = cfg["starting_capital"] + daily.cumsum().shift(1).fillna(0)
                        returns = daily / opening
                        sharpe = (
                            float(returns.mean() / returns.std() * np.sqrt(365))
                            if returns.std() > 0
                            else None
                        )
                        item = dict(
                            requested_start=window["requested_start"],
                            actual_start=start.date().isoformat(),
                            end_inclusive=(end - pd.DateOffset(days=1)).date().isoformat(),
                            mode=mode,
                            risk_policy=name,
                            strategy=strategy,
                            calendar_days=len(calendar),
                            forecast_days=int(dates.nunique()),
                            common_price_days=int(covered_days),
                            excluded_signal_periods=int(sliced.excluded_signal.sum()),
                            net_pnl=metrics["total_pnl"],
                            return_pct=100 * metrics["total_return_pct"],
                            max_drawdown_pct=100 * abs(metrics["max_drawdown_pct_peak"]),
                            sharpe_calendar=sharpe,
                            n_trades=metrics["n_trades"],
                            proposed_signals=metrics["n_signals_proposed"],
                            halted=metrics["halted_at_period"] is not None,
                            terminal_below_floor=metrics["final_capital"]
                            <= cfg["starting_capital"]
                            * (1 - cfg["initial_capital_loss_floor_pct"]),
                            halt_auction=(
                                metrics["halt_details"]["auction_time"]
                                if metrics["halt_details"]
                                else None
                            ),
                            worst_day_pnl=float(daily.min()),
                        )
                        records.append(item)
                        for date, value in daily.items():
                            daily_records.append(
                                dict(
                                    actual_start=item["actual_start"],
                                    mode=mode,
                                    risk_policy=name,
                                    strategy=strategy,
                                    date=date.date().isoformat(),
                                    pnl=float(value),
                                    has_saved_forecasts=date in observed_daily.index,
                                )
                            )
                        if mode == "to_year_end":
                            curves.setdefault(name, {}).setdefault(item["actual_start"], {})[
                                strategy
                            ] = (daily, item)
    finally:
        logger.setLevel(previous_level)
    outdir = base / "virtual/trading/start_date_sensitivity"
    outdir.mkdir(exist_ok=True)
    summary = pd.DataFrame(records)
    pd.DataFrame(daily_records).to_csv(outdir / "daily_pnl.csv", index=False)
    inputs = [
        features_path,
        signal_path,
        prediction_path,
        config_path,
        root / "src/backtest/engine.py",
        root / "src/backtest/risk.py",
    ]
    report = dict(
        created_utc=datetime.now(timezone.utc).isoformat(),
        signal_run=best,
        config=cfg,
        equal_calendar_days=horizon,
        strict_common_price_calendar_days=strict_horizon,
        maximum_horizon_considered=30,
        windows=[
            {k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in w.items()}
            for w in windows
        ],
        interpretation="Retrospective sensitivity of empty account restart; no retraining or new start selected.",
        input_sha256={
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs
        },
        results=records,
    )
    (outdir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    if figures is None:
        return report
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))
    for ax, policy_name in zip(axes, ("original_2pct", "book_risk_managed")):
        data = summary[(summary["mode"] == "equal_window") & (summary.risk_policy == policy_name)]
        table = data.pivot(index="actual_start", columns="strategy", values="return_pct").reindex(
            columns=list(strategies)
        )
        bound = max(float(np.abs(table.to_numpy()).max()), 0.01)
        im = ax.imshow(table, cmap="RdYlGn", vmin=-bound, vmax=bound, aspect="auto")
        ax.set_xticks(
            range(len(table.columns)),
            ["Imbalance", "Intraday", "Conditional", "50/50 + TP/SL", "Pure 50/50"],
            rotation=25,
            ha="right",
        )
        ax.set_yticks(range(len(table)), table.index)
        for i, date in enumerate(table.index):
            for j, strategy in enumerate(table.columns):
                halted = bool(
                    data[(data.actual_start == date) & (data.strategy == strategy)].halted.iloc[0]
                )
                terminal_breach = bool(
                    data[
                        (data.actual_start == date) & (data.strategy == strategy)
                    ].terminal_below_floor.iloc[0]
                )
                ax.text(
                    j,
                    i,
                    f"{table.iloc[i, j]:+.1f}%"
                    + ("\nHALTED" if halted else "\nFLOOR AT END" if terminal_breach else "")
                    + (
                        " †"
                        if int(data[data.actual_start == date].common_price_days.iloc[0]) < horizon
                        else ""
                    ),
                    ha="center",
                    va="center",
                    fontsize=9,
                )
        ax.set_title(policy_name.replace("_", " ").title())
        fig.colorbar(im, ax=ax, shrink=0.8, label="Account return (%)")
    fig.suptitle(
        f"Start-date sensitivity · {horizon} calendar days per account · £50,000 reset\n"
        "Frozen rules · † Incomplete common-price coverage · colour scales differ by risk policy",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    figures["equal_windows"] = fig
    plt.close(fig)
    colors = ["#00a6c8", "#e63946", "#ef9a44", "#25895e", "#8b5ec8"]
    for policy_name, paths in curves.items():
        fig, axs = plt.subplots(2, 3, figsize=(15, 8), sharex=True)
        for ax, (start, paths_for_start) in zip(axs.flat, paths.items()):
            for (strategy, (daily, item)), color in zip(paths_for_start.items(), colors):
                ax.step(
                    daily.index,
                    cfg["starting_capital"] + daily.cumsum(),
                    where="post",
                    color=color,
                    lw=1.3,
                    label=strategy,
                )
                if item["halted"]:
                    ax.text(
                        0.98,
                        0.03,
                        "Some accounts halted; tails include idle days",
                        transform=ax.transAxes,
                        ha="right",
                        fontsize=7,
                        color="#777777",
                    )
            ax.axhline(cfg["starting_capital"], color="#999999", ls=":", lw=0.7)
            ax.axvspan(
                pd.Timestamp("2018-10-21", tz="Europe/London"),
                pd.Timestamp("2018-11-02", tz="Europe/London"),
                color="#999999",
                alpha=0.12,
            )
            ax.set_title(f"Account starts {start}", fontsize=10)
            ax.yaxis.set_major_formatter(mticker.StrMethodFormatter("£{x:,.0f}"))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
            ax.xaxis.set_major_locator(mdates.MonthLocator())
            ax.grid(alpha=0.2)
            ax.spines[["top", "right"]].set_visible(False)
        handles, labels = axs.flat[0].get_legend_handles_labels()
        axs.flat[-1].axis("off")
        axs.flat[-1].legend(handles, labels, loc="center", frameon=False)
        fig.suptitle(
            policy_name.replace("_", " ").title() + " · every start runs to 31 December\n"
            "Unequal durations; independent vertical scales; endpoints are not a fair ranking",
            fontsize=13,
        )
        fig.text(
            0.5,
            0.01,
            "Grey band: no saved forecasts · Earlier accounts experience August; September and later accounts do not",
            ha="center",
            fontsize=9,
        )
        fig.tight_layout(rect=(0, 0.035, 1, 0.91))
        figures[policy_name] = fig
        plt.close(fig)
    return report


if __name__ == "__main__":
    result = run_study(Path(__file__).resolve().parents[1])
    table = pd.DataFrame(result["results"])
    for mode in ("equal_window", "to_year_end"):
        print(mode, "horizon", result["equal_calendar_days"])
        print(
            table[(table["mode"] == mode) & table.risk_policy.eq("original_2pct")][
                ["actual_start", "strategy", "net_pnl", "return_pct", "halted"]
            ].to_string(index=False)
        )
