"""Tests for the stress-study store builder.

Every fetcher is mocked, so no network call happens and the store is written
into ``tmp_path``. The behaviour that matters here is the *accounting*: a feed
that fails must be recorded and skipped rather than sinking the build, and the
manifest must describe exactly what was written.
"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "build_stress_store", REPO_ROOT / "scripts" / "build_stress_store.py"
)
assert _spec is not None and _spec.loader is not None
bss = importlib.util.module_from_spec(_spec)
sys.modules["build_stress_store"] = bss
_spec.loader.exec_module(bss)

_DAYS = [dt.date(2024, 1, 1), dt.date(2024, 1, 2)]


def _system(date):
    times = pd.date_range(f"{date.isoformat()}T00:00:00Z", periods=48, freq="30min")
    return pd.DataFrame(
        {
            "time": times,
            "demand_actual": 30000.0,
            "gen_WIND": 8000.0,
            "solar_mw": 0.0,
            "residual_mw": 22000.0,
        }
    )


def _prints(date):
    times = pd.date_range(f"{date.isoformat()}T00:00:00Z", periods=48, freq="30min")
    rows = []
    for h in (4, 1):
        rows.append(
            pd.DataFrame(
                {
                    "time": times,
                    "publish_time": times - pd.Timedelta(hours=h),
                    "settlement_period": range(1, 49),
                    "horizon": h,
                    "lolp": 0.0,
                    "drm_mw": 5000.0 + h,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def _profile(date, population=None):
    """A per-BMU feed. These take the population being studied; the market-wide
    feeds (system, LoLP) do not, which is the distinction ``PER_BMU_FEEDS``
    draws in the builder."""
    times = pd.date_range(f"{date.isoformat()}T00:00:00Z", periods=48, freq="30min")
    return pd.DataFrame({"site": "Pillswood", "time": times, "mw": 10.0})


@pytest.fixture
def patched(monkeypatch):
    """All day feeds succeed; SBP and CMN return small fixed frames."""
    monkeypatch.setitem(bss.DAY_FEEDS, "system", (_system, "system"))
    monkeypatch.setitem(bss.DAY_FEEDS, "lolpdrm", (_prints, "lolpdrm_prints"))
    monkeypatch.setitem(bss.DAY_FEEDS, "pn", (_profile, "fleet_pn"))
    monkeypatch.setitem(bss.DAY_FEEDS, "mels", (_profile, "fleet_mels"))
    monkeypatch.setitem(bss.DAY_FEEDS, "mils", (_profile, "fleet_mils"))

    def _sbp(days):
        times = pd.date_range(f"{days[0].isoformat()}T00:00:00Z", periods=96, freq="30min")
        return pd.DataFrame({"time": times, "system_buy_price": 80.0, "niv": 100.0})

    monkeypatch.setattr(bss, "_assemble_sbp", _sbp)
    monkeypatch.setattr(bss, "_assemble_cmn", lambda days: pd.DataFrame())


def test_build_store_writes_every_table_and_manifest(tmp_path, patched):
    summary = bss.build_store(_DAYS, tmp_path, log=lambda _m: None)

    for table in bss.TABLES:
        assert (tmp_path / f"{table}.parquet").exists()
    assert summary["failures"] == []
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["window_start"] == "2024-01-01"
    assert manifest["window_end"] == "2024-01-02"
    assert manifest["rows"]["system"] == 96  # two days × 48 half-hours
    assert manifest["rows"]["lolpdrm_prints"] == 192  # both horizons kept

    loaded = bss.load_store(tmp_path)
    assert isinstance(loaded["system"].index, pd.DatetimeIndex)
    assert loaded["system"].index.name == "time"
    assert "time" in loaded["fleet_pn"].columns  # long tables stay long


def test_failing_feed_is_recorded_not_fatal(tmp_path, monkeypatch, patched):
    def _boom(date):
        raise RuntimeError("feed down")

    monkeypatch.setitem(bss.DAY_FEEDS, "mels", (_boom, "fleet_mels"))
    summary = bss.build_store(_DAYS, tmp_path, log=lambda _m: None)

    # The build completes; the failure is accounted for, not swallowed.
    assert len(summary["failures"]) == 2
    assert all(f[1] == "mels" for f in summary["failures"])
    assert json.loads((tmp_path / "failures.json").read_text())

    coverage = pd.read_parquet(tmp_path / "coverage.parquet")
    assert coverage["system"].all()
    assert not coverage["mels"].any()
    # The other feeds still wrote their rows.
    assert len(pd.read_parquet(tmp_path / "fleet_pn.parquet")) == 96
    assert pd.read_parquet(tmp_path / "fleet_mels.parquet").empty


def test_second_build_reuses_current_store(tmp_path, patched):
    bss.build_store(_DAYS, tmp_path, log=lambda _m: None)
    assert bss.store_is_current(tmp_path, _DAYS)

    with mock.patch.dict(bss.DAY_FEEDS, {"system": (mock.Mock(), "system")}) as feeds:
        summary = bss.build_store(_DAYS, tmp_path, log=lambda _m: None)
        feeds["system"][0].assert_not_called()
    assert summary["skipped"] is True

    # A different window is not "current", so it rebuilds.
    assert not bss.store_is_current(tmp_path, _DAYS + [dt.date(2024, 1, 3)])


def test_store_is_current_accepts_str_paths(tmp_path, patched):
    # build_store normalises its store argument, so this must too — a str path
    # used to raise TypeError and would read as "store is broken, rebuild".
    bss.build_store(_DAYS, tmp_path, log=lambda _m: None)
    assert bss.store_is_current(str(tmp_path), _DAYS)
    assert not bss.store_is_current(str(tmp_path / "nope"), _DAYS)


def test_coverage_marks_sbp_days_from_assembled_frame(tmp_path, patched):
    bss.build_store(_DAYS, tmp_path, log=lambda _m: None)
    coverage = pd.read_parquet(tmp_path / "coverage.parquet")
    assert list(coverage["date"]) == ["2024-01-01", "2024-01-02"]
    assert coverage["sbp"].all()
