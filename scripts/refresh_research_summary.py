"""Refresh the compact README caption from notebook 02's verified report.

Run notebook 02 first. It exports its one README image directly; this script
never scrapes notebook cell positions or reinstates the old account-sweep table.
"""

import hashlib
import json
from pathlib import Path

START = "<!-- partial-hedge-summary:start -->"
END = "<!-- partial-hedge-summary:end -->"
IMAGE = "research/notebooks/assets/equity_curve.png"


def refresh(root: Path) -> None:
    runs = root / "artifacts/da_positioning"
    best = json.loads((runs / "best_run.json").read_text())["best_run"]
    path = runs / best / "virtual/trading/partial_hedge_report.json"
    report = json.loads(path.read_text())
    if (
        report.get("schema_version") != 1
        or report.get("study") != "fixed_volume_partial_hedges"
        or report.get("run") != best
        or report.get("image") != IMAGE
        or report.get("account_simulation") is not False
    ):
        raise ValueError("Incompatible research report; execute notebook 02")
    expected_inputs = {
        f"artifacts/da_positioning/{best}/features/features.parquet",
        f"artifacts/da_positioning/{best}/virtual/trading/signals.csv",
        f"artifacts/da_positioning/{best}/virtual/trading/predictions.csv",
    }
    if set(report["input_sha256"]) != expected_inputs:
        raise ValueError("Missing input provenance; execute notebook 02")
    checks = {**report["input_sha256"], IMAGE: report["image_sha256"]}
    for name, expected in checks.items():
        source = root / name
        if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Stale or missing {name}; execute notebook 02 before refreshing")
    caption = (
        f"Five exit policies on the same {report['matched_signals']:,} entries, "
        f"{report['quantity_mwh_per_signal']:g} MWh each, through "
        f"{report['end']}. Cumulative net research PnL at fixed volume; "
        "shaded gaps mark missing coverage. "
        "[Notebook 02](research/notebooks/02_hybrid_execution_analysis.ipynb) "
        "prices the profit, exposure and tail-risk trade-off."
    )
    readme = root / "README.md"
    content = readme.read_text()
    if content.count(START) != 1 or content.count(END) != 1:
        raise ValueError("README must contain exactly one research-caption marker pair")
    start = content.index(START) + len(START)
    end = content.index(END)
    if end < start:
        raise ValueError("README research-caption markers are reversed")
    readme.write_text(content[:start] + "\n" + caption + "\n" + content[end:])


def main() -> None:
    refresh(Path(__file__).resolve().parents[1])
    print("Verified notebook 02 inputs and overview image; refreshed compact README caption")


if __name__ == "__main__":
    main()
