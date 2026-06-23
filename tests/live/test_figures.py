"""Tests for the figure-export layer.

These build a minimal day artifact matching the Appendix A schema, write it via
:mod:`live.io_store` into a redirected temp ``docs/data`` tree, then assert that
:func:`live.figures.write_day_figures` produces Plotly JSON files that
:func:`plotly.io.from_json` can re-load.
"""

import json

import plotly.io as pio
import pytest

from live import figures, io_store, schema

_DATE = "2026-06-24"
_DURATION = "2h"


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path, monkeypatch):
    """Point all artifact and figure IO at an isolated temp directory."""
    monkeypatch.setattr(io_store, "DATA_DIR", tmp_path / "data")


def _dispatch_entry(period: int, da_mw: float, intraday_mw: float, soc_after: float) -> dict:
    return {
        "period": period,
        "da_mw": da_mw,
        "intraday_mw": intraday_mw,
        "final_mw": da_mw + intraday_mw,
        "soc_after": soc_after,
        "da_price": 50.0,
        "mid_price": 51.0,
        "trade_type": "hold",
        "rule_label": "none",
    }


def _day_artifact() -> dict:
    """A small but schema-valid four-period day artifact with one '2h' asset."""
    n = 4
    timestamps = [f"2026-06-24T0{i}:00:00Z" for i in range(n)]
    da = [20.0, 25.0, 70.0, 65.0]
    mid = [21.0, 24.0, 72.0, 64.0]
    schedule_mw = [-10.0, -10.0, 10.0, 10.0]
    soc = [0.7, 0.9, 0.65, 0.4]
    dispatch = [_dispatch_entry(i, schedule_mw[i], 0.0, soc[i]) for i in range(n)]
    asset = {
        "capacity_mwh": 20.0,
        "power_mw": 10.0,
        "schedule_mw": schedule_mw,
        "dispatch": dispatch,
        "soc": {"start": 0.5, "end": soc[-1], "track": soc},
        "pnl": {
            "benchmark_da_revenue": 1000.0,
            "intraday_da_improvement": 120.0,
            "execution_costs_paid": 30.0,
            "degradation_cost": 45.0,
            "net_pnl": 1045.0,
        },
        "metrics": {"cycles": 1.0, "capture": 0.8},
    }
    return {
        "schema_version": schema.SCHEMA_VERSION,
        "date": _DATE,
        "resolution_h": 1.0,
        "prices": {"timestamps": timestamps, "da": da, "mid": mid},
        "context": {
            "wind_gwh": 100.0,
            "solar_gwh": 20.0,
            "demand_gwh": 600.0,
            "wind_share": 0.3,
        },
        "labels": ["weekday"],
        "assets": {_DURATION: asset},
    }


def _write_day_artifact() -> None:
    """Persist the fixture day artifact directly through the atomic writer."""
    artifact = _day_artifact()
    schema.validate_day(artifact)
    io_store._atomic_write(io_store._day_path(_DATE), artifact, schema.validate_day)


def test_write_day_figures_produces_loadable_plotly_json():
    _write_day_artifact()

    outputs = figures.write_day_figures(_DATE)

    assert set(outputs) == {"dispatch", "waterfall"}
    for path in outputs.values():
        assert path.exists()
        # A valid, re-loadable Plotly figure with at least one trace.
        fig = pio.from_json(path.read_text(encoding="utf-8"))
        assert len(fig.data) > 0
        # The file is also plain JSON on disk.
        json.loads(path.read_text(encoding="utf-8"))


def test_write_day_figures_writes_under_date_directory():
    _write_day_artifact()

    outputs = figures.write_day_figures(_DATE)

    assert outputs["dispatch"] == io_store.DATA_DIR / "figs" / _DATE / "dispatch.json"
    assert outputs["waterfall"] == io_store.DATA_DIR / "figs" / _DATE / "waterfall.json"


def test_write_day_figures_unknown_duration_raises():
    _write_day_artifact()

    with pytest.raises(KeyError):
        figures.write_day_figures(_DATE, duration="9h")
