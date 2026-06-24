"""Tests for the atomic JSON persistence layer.

These exercise :mod:`live.io_store` against a temporary ``docs/data`` tree (the
module-level :data:`live.io_store.DATA_DIR` is redirected to ``tmp_path``), so no
committed artifact is ever touched. The real settlement engine produces the
:class:`live.settle.DayResult` written out, keeping the fixtures honest.
"""

import datetime as dt
import json

import pandas as pd
import pytest

from live import io_store, schema
from live.assets import REFERENCE_DURATIONS, bess_config, build_assets

_DAY = dt.date(2026, 6, 24)


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path, monkeypatch):
    """Point all io_store writes at an isolated temp directory."""
    monkeypatch.setattr(io_store, "DATA_DIR", tmp_path / "data")


def _prices(n_periods: int = 24, *, low: float = 20.0, high: float = 80.0) -> pd.DataFrame:
    times = pd.date_range("2026-06-24T00:00:00Z", periods=n_periods, freq="60min")
    da = [low if i < n_periods // 2 else high for i in range(n_periods)]
    mid = [p + 1.0 for p in da]
    return pd.DataFrame({"day_ahead_price": da, "mid_price": mid}, index=times)


def _settled_day():
    from live import settle

    cfg = bess_config()
    assets = build_assets()
    start = {duration: 0.5 for duration in REFERENCE_DURATIONS}
    result = settle.settle_day(_DAY, _prices(), cfg, assets, start)
    assert result is not None
    return result


def _context() -> dict[str, float | None]:
    return {"wind_gwh": 120.0, "solar_gwh": 30.0, "demand_gwh": 700.0, "wind_share": 0.42}


def test_write_read_day_round_trip_preserves_fields():
    day_result = _settled_day()
    labels = ["windy", "volatile"]
    io_store.write_day(_DAY, day_result, _context(), labels)

    loaded = io_store.read_day(_DAY)

    assert loaded["schema_version"] == 1
    assert loaded["date"] == _DAY.isoformat()
    assert loaded["resolution_h"] == io_store.RESOLUTION_H
    assert loaded["labels"] == labels
    assert loaded["context"] == _context()
    assert set(loaded["assets"]) == set(REFERENCE_DURATIONS)

    for duration, result in day_result.durations.items():
        block = loaded["assets"][duration]
        assert len(block["dispatch"]) == len(result.dispatch_log)
        assert len(block["schedule_mw"]) == len(result.da_schedule)
        assert block["soc"]["end"] == pytest.approx(result.end_soc, abs=1e-3)
        assert len(block["soc"]["track"]) == len(result.dispatch_log)
        # Prices have one entry per settlement period.
        assert len(loaded["prices"]["timestamps"]) == len(result.dispatch_log)
        assert len(loaded["prices"]["da"]) == len(result.dispatch_log)
        # PnL buckets survive the round-trip and obey the ledger invariant.
        pnl = block["pnl"]
        reconstructed = (
            pnl["benchmark_da_revenue"]
            + pnl["intraday_da_improvement"]
            - pnl["execution_costs_paid"]
            - pnl["degradation_cost"]
        )
        assert reconstructed == pytest.approx(pnl["net_pnl"], abs=1e-2)


def test_interrupted_write_does_not_corrupt_existing_file(monkeypatch):
    day_result = _settled_day()
    io_store.write_day(_DAY, day_result, _context(), ["windy"])
    good = io_store.read_day(_DAY)

    # Simulate a failure during the validate step of the next write.
    original = schema.validate_day

    def _boom(_obj):
        raise schema.SchemaError("simulated mid-write failure")

    schema.validate_day = _boom  # type: ignore[assignment]
    try:
        with pytest.raises(schema.SchemaError):
            io_store.write_day(
                _DAY,
                day_result,
                {"wind_gwh": None, "solar_gwh": None, "demand_gwh": None, "wind_share": None},
                ["calm"],
            )
    finally:
        schema.validate_day = original  # type: ignore[assignment]

    # The previously written, valid file must be intact and no temp left behind.
    assert io_store.read_day(_DAY) == good
    assert not (io_store._day_path(_DAY).with_name(io_store._day_path(_DAY).name + ".tmp")).exists()


def test_all_artifacts_carry_schema_version():
    day_result = _settled_day()
    io_store.write_day(_DAY, day_result, _context(), ["windy"])
    io_store.write_latest(
        _DAY,
        end_soc={d: 0.5 for d in REFERENCE_DURATIONS},
        cumulative_net_pnl={d: 123.456 for d in REFERENCE_DURATIONS},
    )
    io_store.write_history(
        [
            {
                "date": _DAY.isoformat(),
                "da_spread": 60.0,
                "labels": ["windy"],
                "wind_share": 0.42,
                "demand_gwh": 700.0,
                "net_pnl": {d: 10.0 for d in REFERENCE_DURATIONS},
                "cycles": {d: 1.0 for d in REFERENCE_DURATIONS},
            }
        ]
    )
    io_store.write_manifest(
        available_dates=[_DAY.isoformat()],
        durations=list(REFERENCE_DURATIONS),
        reference_asset={
            "power_mw": 50,
            "round_trip_eff": 0.8836,
            "soc_band": [0.10, 0.90],
            "degradation_cost_per_mwh": 5.0,
            "target_daily_cycles": 1.5,
        },
    )

    for path in (
        io_store._day_path(_DAY),
        io_store._latest_path(),
        io_store._history_path(),
        io_store._manifest_path(),
    ):
        with open(path, "r", encoding="utf-8") as handle:
            assert json.load(handle)["schema_version"] == 1


def test_read_missing_artifacts_return_none():
    assert io_store.read_latest() is None
    assert io_store.read_history() is None


def test_latest_and_history_round_trip():
    end_soc = {d: 0.55 for d in REFERENCE_DURATIONS}
    cumulative = {d: 999.0 for d in REFERENCE_DURATIONS}
    io_store.write_latest(_DAY, end_soc, cumulative)
    latest = io_store.read_latest()
    assert latest is not None
    assert latest["end_soc"] == end_soc
    assert latest["cumulative_net_pnl"] == cumulative

    rows = [
        {
            "date": _DAY.isoformat(),
            "da_spread": 60.0,
            "labels": ["windy"],
            "wind_share": 0.42,
            "demand_gwh": 700.0,
            "net_pnl": {d: 10.0 for d in REFERENCE_DURATIONS},
            "cycles": {d: 1.0 for d in REFERENCE_DURATIONS},
        }
    ]
    io_store.write_history(rows)
    history = io_store.read_history()
    assert history is not None
    assert history["rows"] == rows


def test_floats_rounded_to_three_decimals():
    io_store.write_latest(
        _DAY,
        end_soc={d: 0.5 for d in REFERENCE_DURATIONS},
        cumulative_net_pnl={d: 1.234567 for d in REFERENCE_DURATIONS},
    )
    latest = io_store.read_latest()
    assert latest is not None
    assert latest["cumulative_net_pnl"]["1h"] == 1.235


def _valid_day_artifact() -> dict:
    """A freshly settled, schema-valid per-day artifact to mutate in tests."""
    day_result = _settled_day()
    io_store.write_day(_DAY, day_result, _context(), ["windy"])
    artifact = io_store.read_day(_DAY)
    # Sanity-check the baseline passes before any test mutates it.
    schema.validate_day(artifact)
    return artifact


def _first_dispatch_entry(artifact: dict) -> dict:
    duration = next(iter(artifact["assets"]))
    entry: dict = artifact["assets"][duration]["dispatch"][0]
    return entry


def test_validate_day_accepts_settled_artifact():
    schema.validate_day(_valid_day_artifact())


def test_validate_day_rejects_non_numeric_dispatch_value():
    artifact = _valid_day_artifact()
    _first_dispatch_entry(artifact)["da_mw"] = "not-a-number"
    with pytest.raises(schema.SchemaError, match="da_mw"):
        schema.validate_day(artifact)


def test_validate_day_rejects_bool_dispatch_number():
    # bool is a subclass of int but must not pass a numeric type check.
    artifact = _valid_day_artifact()
    _first_dispatch_entry(artifact)["soc_after"] = True
    with pytest.raises(schema.SchemaError, match="soc_after"):
        schema.validate_day(artifact)


def test_validate_day_rejects_non_string_dispatch_label():
    artifact = _valid_day_artifact()
    _first_dispatch_entry(artifact)["trade_type"] = 7
    with pytest.raises(schema.SchemaError, match="trade_type"):
        schema.validate_day(artifact)


def test_validate_day_rejects_non_integer_period():
    artifact = _valid_day_artifact()
    _first_dispatch_entry(artifact)["period"] = 1.5
    with pytest.raises(schema.SchemaError, match="period"):
        schema.validate_day(artifact)


def test_validate_day_rejects_missing_dispatch_key():
    artifact = _valid_day_artifact()
    del _first_dispatch_entry(artifact)["mid_price"]
    with pytest.raises(schema.SchemaError, match="mid_price"):
        schema.validate_day(artifact)


def test_validate_day_rejects_non_dict_dispatch_entry():
    artifact = _valid_day_artifact()
    duration = next(iter(artifact["assets"]))
    artifact["assets"][duration]["dispatch"][0] = ["not", "an", "object"]
    with pytest.raises(schema.SchemaError, match="must be an object"):
        schema.validate_day(artifact)
