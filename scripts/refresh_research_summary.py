"""Refresh selected-run metrics and notebook 02's execution-comparison image."""

import base64
import json
import yaml
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    runs = root / "artifacts/da_positioning"
    best = json.loads((runs / "best_run.json").read_text())["best_run"]
    path = runs / best / "virtual/trading"
    metrics = json.loads((path / "metrics.json").read_text())
    dev = metrics["trading_performance_by_split"]["development"]
    report = json.loads((path / "holdout_report.json").read_text())
    control = report["always_short_control"]
    cfg = yaml.safe_load((root / "configs/config.example.yaml").read_text())
    model_name = cfg["model"]["type"].replace("_", " ")
    hybrid = json.loads((path / "hybrid_development_report.json").read_text())
    hybrid_text = (
        f"Notebook 02 selects a {hybrid['selected_ratio']:.0%} passive share on development only."
        if hybrid["has_eligible_hybrid"]
        else (
            "Notebook 02 reports no eligible hybrid under its capital-floor constraint: "
            "all hybrid candidates halt. This is a failed development calibration, "
            "not an improved strategy."
        )
    )
    text = f"""The canonical run is `{best}`. Model candidates are ranked on development MAE;
signal settings are ranked on development Sharpe within the £1/MWh cost tier and
one-trade-per-day floor. The selected model is {model_name}. The last 60
market days are reserved from this selection, but were inspected in earlier
research and are therefore a **retrospective evaluation split**, not a fresh sample.

| | Development (90 days, selection) | Evaluation (60 days) |
|---|---:|---:|
| Executed trades | {dev['n_trades']:,} | {report['n_trades']:,} |
| Net PnL | £{dev['total_pnl']:,.0f} | £{report['total_pnl']:,.0f} |
| 95% conditional PnL interval | — | £{report['pnl_ci'][0]:,.0f} to £{report['pnl_ci'][1]:,.0f} |
| Sharpe (daily account returns) | {dev['sharpe_ratio']:.2f} | {report['sharpe_ratio']:.2f} |
| 95% conditional Sharpe interval | — | {report['sharpe_ci'][0]:.2f} to {report['sharpe_ci'][1]:.2f} |
| Max cash drawdown | £{abs(dev['max_drawdown']):,.0f} | £{abs(report['max_drawdown']):,.0f} |
| Evaluation volume / fees | — | {report['total_position_mwh']:,.0f} MWh / £{report['total_transaction_costs']:,.0f} |

The intervals include zero and do not establish a reliable trading edge.
[`score_holdout`](src/evaluation/holdout_report.py) uses 10,000 independent
market-day bootstrap draws, seed 7, conditional on observed daily cash PnL and
returns. It does not rerun compounding, capital halts or selection, or account for
serial dependence. The always-short directional control on **model-selected
periods** earns £{control['total_pnl']:,.0f} (Sharpe {control['sharpe_ratio']:.2f});
it is not a model-free scheduling baseline.

Quantities use a fixed pre-auction £50/MWh reference, and auction equity admits
settlements only after the delivery day ends plus a one-hour publication
assumption. Historical revised prices are not a point-in-time publication archive.
{hybrid_text} Notebook 03 discloses missing-input imputation and excludes incomplete
London dispatch days.

"""
    readme = root / "README.md"
    content = readme.read_text()
    start = content.index("### What the backtest actually shows")
    body = content.index("\n\n", start) + 2
    end = content.index("**Everything priced off MID", body)
    readme.write_text(content[:body] + text + content[end:])
    book = json.loads((root / "research/notebooks/02_hybrid_execution_analysis.ipynb").read_text())
    for output in book["cells"][4].get("outputs", []):
        if "image/png" in output.get("data", {}):
            (root / "research/notebooks/assets/equity_curve.png").write_bytes(
                base64.b64decode(output["data"]["image/png"])
            )
            break
    else:
        raise RuntimeError("Notebook 02 has no execution-comparison image; execute it first.")
    print(f"Refreshed README and equity image from {best}")


if __name__ == "__main__":
    main()
