import hashlib
import json

import pytest

from scripts.refresh_research_summary import END, IMAGE, START, refresh


def setup_report(root):
    run = "example_run"
    runs = root / "artifacts/da_positioning"
    trading = runs / run / "virtual/trading"
    trading.mkdir(parents=True)
    (runs / "best_run.json").write_text(json.dumps({"best_run": run}))
    inputs = {}
    for name in [
        "features/features.parquet",
        "virtual/trading/signals.csv",
        "virtual/trading/predictions.csv",
    ]:
        path = runs / run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test input")
        inputs[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    image = root / IMAGE
    image.parent.mkdir(parents=True)
    image.write_bytes(b"test image")
    report = {
        "schema_version": 1,
        "study": "fixed_volume_partial_hedges",
        "run": run,
        "image": IMAGE,
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "account_simulation": False,
        "input_sha256": inputs,
        "matched_signals": 1911,
        "quantity_mwh_per_signal": 1,
        "end": "2018-12-31",
    }
    (trading / "partial_hedge_report.json").write_text(json.dumps(report))
    (root / "README.md").write_text(f"Keep introduction\n{START}\nold\n{END}\nKeep research")


def test_refresh_preserves_other_content_and_is_idempotent(tmp_path):
    setup_report(tmp_path)
    refresh(tmp_path)
    first = (tmp_path / "README.md").read_text()
    assert first.startswith(f"Keep introduction\n{START}\n")
    assert first.endswith(f"\n{END}\nKeep research")
    assert "1,911 entries" in first
    assert "What the backtest actually shows" not in first
    refresh(tmp_path)
    assert (tmp_path / "README.md").read_text() == first


@pytest.mark.parametrize(
    "name", [IMAGE, "artifacts/da_positioning/example_run/virtual/trading/signals.csv"]
)
def test_stale_artifact_fails_before_readme_write(tmp_path, name):
    setup_report(tmp_path)
    original = (tmp_path / "README.md").read_bytes()
    (tmp_path / name).write_bytes(b"changed by another run")
    with pytest.raises(ValueError, match="Stale"):
        refresh(tmp_path)
    assert (tmp_path / "README.md").read_bytes() == original


def test_missing_marker_does_not_replace_unrelated_readme(tmp_path):
    setup_report(tmp_path)
    (tmp_path / "README.md").write_text("Different README")
    with pytest.raises(ValueError, match="marker"):
        refresh(tmp_path)
    assert (tmp_path / "README.md").read_text() == "Different README"
