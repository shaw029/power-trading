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
            raise ValueError(f"Stale or missing {name}; execute notebook 02a before refreshing")
    # The start-date caveat lives here, not hand-written into the README, because
    # this block is regenerated: a caveat typed between the markers is silently
    # overwritten on the next refresh, which is the one place it must not be.
    caption = (
        f"Five exit policies on the same {report['matched_signals']:,} entries, "
        f"{report['quantity_mwh_per_signal']:g} MWh each, through "
        f"{report['end']} — fixed volume, so this is edge per unit traded, not an "
        "equity curve. Shaded gaps are missing coverage.\n\n"
        "**Read the ordering as window-specific.** It comes from one period and one "
        "account inception. "
        "[Notebook 02a](research/notebooks/02a_hybrid_execution_analysis.ipynb) "
        "prices the profit/exposure/tail trade-off; "
        "[02b](research/notebooks/02b_start_date_sensitivity.ipynb) restarts the same "
        "signals from five monthly inceptions and the ranking moves — full imbalance "
        "wins four of five windows, October puts conditional TP/SL on top. At the "
        "original 2% sizing, a July start halts four of the five policies on the "
        "capital floor; under managed book risk none of them halt and full imbalance "
        "earns +8.8% instead of +485.9%. The sizing policy, not the exit policy, "
        "decides whether the account survives."
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
