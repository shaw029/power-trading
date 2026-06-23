"""Tests for the history roll-up CLI.

These write three minimal but schema-valid day artifacts into a redirected temp
``docs/data`` tree, run :func:`live.aggregate.aggregate`, and assert that it
rebuilds a three-row ``history.json``, a ``manifest.json`` listing the three
dates, and four re-loadable history-level Plotly figures.
"""

import json

import plotly.io as pio
import pytest

from live import aggregate, io_store, schema
from live.assets import REFERENCE_DURATIONS

_DATES = ["2026-06-24", "2026-06-22", "2026-06-23"]  # deliberately out of order


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path, monkeypatch):
    """Point all artifact and figure IO at an isolated temp directory."""
    monkeypatch.setattr(io_store, "DATA_DIR", tmp_path / "data")


def _dispatch_entry(period: int, da_mw: float, soc_after: float) -> dict:
    return {
        "period": period,
        "da_mw": da_mw,
        "intraday_mw": 0.0,
        "final_mw": da_mw,
        "soc_after": soc_after,
        "da_price": 50.0,
        "mid_price": 51.0,
        "trade_type": "hold",
        "rule_label": "none",
    }


def _asset(duration_hours: int, net_pnl: float, cycles: float) -> dict:
    n = 4
    schedule_mw = [-10.0, -10.0, 10.0, 10.0]
    soc = [0.7, 0.9, 0.65, 0.4]
    dispatch = [_dispatch_entry(i, schedule_mw[i], soc[i]) for i in range(n)]
    return {
        "capacity_mwh": 50.0 * duration_hours,
        "power_mw": 50.0,
        "schedule_mw": schedule_mw,
        "dispatch": dispatch,
        "soc": {"start": 0.5, "end": soc[-1], "track": soc},
        "pnl": {
            "benchmark_da_revenue": net_pnl,
            "intraday_da_improvement": 0.0,
            "execution_costs_paid": 0.0,
            "degradation_cost": 0.0,
            "net_pnl": net_pnl,
        },
        "metrics": {"cycles": cycles, "capture": 0.8},
    }


def _day_artifact(date: str, labels: list[str], net_pnl: float) -> dict:
    n = 4
    timestamps = [f"{date}T0{i}:00:00Z" for i in range(n)]
    da = [20.0, 25.0, 70.0, 65.0]
    mid = [21.0, 24.0, 72.0, 64.0]
    assets = {
        dur: _asset(int(dur.removesuffix("h")), net_pnl + i * 100.0, 1.0 + i * 0.5)
        for i, dur in enumerate(REFERENCE_DURATIONS)
    }
    return {
        "schema_version": schema.SCHEMA_VERSION,
        "date": date,
        "resolution_h": 1.0,
        "prices": {"timestamps": timestamps, "da": da, "mid": mid},
        "context": {
            "wind_gwh": 100.0,
            "solar_gwh": 20.0,
            "demand_gwh": 600.0,
            "wind_share": 0.3,
        },
        "labels": labels,
        "assets": assets,
    }


def _write_days() -> None:
    """Persist three fixture day artifacts directly through the atomic writer."""
    labels = [["windy"], ["calm"], []]
    for date, label, pnl in zip(_DATES, labels, [1000.0, 500.0, 800.0]):
        artifact = _day_artifact(date, label, pnl)
        schema.validate_day(artifact)
        io_store._atomic_write(io_store._day_path(date), artifact, schema.validate_day)


def test_aggregate_rebuilds_three_row_history_sorted_by_date():
    _write_days()

    aggregate.aggregate()

    history = io_store.read_history()
    assert history is not None
    rows = history["rows"]
    assert len(rows) == 3
    # Stable ascending date ordering regardless of filesystem listing order.
    assert [row["date"] for row in rows] == sorted(_DATES)
    first = rows[0]
    assert set(first["net_pnl"]) == set(REFERENCE_DURATIONS)
    assert set(first["cycles"]) == set(REFERENCE_DURATIONS)
    assert first["da_spread"] == pytest.approx(50.0)


def test_aggregate_writes_manifest_listing_the_three_dates():
    _write_days()

    aggregate.aggregate()

    manifest_path = io_store._manifest_path()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema.validate_manifest(manifest)
    assert manifest["available_dates"] == sorted(_DATES)
    assert manifest["durations"] == list(REFERENCE_DURATIONS)
    assert manifest["reference_asset"]["power_mw"] == 50.0


def test_aggregate_writes_loadable_history_figures():
    _write_days()

    summary = aggregate.aggregate()

    assert set(summary["figures"]) == {
        "equity",
        "duration_comparison",
        "daytype_scatter",
        "daytype_profiles",
    }
    for path in summary["figures"].values():
        assert path.exists()
        fig = pio.from_json(path.read_text(encoding="utf-8"))
        assert len(fig.data) > 0
        json.loads(path.read_text(encoding="utf-8"))


def test_aggregate_is_idempotent():
    _write_days()

    aggregate.aggregate()
    first = io_store._history_path().read_text(encoding="utf-8")
    aggregate.aggregate()
    second = io_store._history_path().read_text(encoding="utf-8")

    assert first == second
