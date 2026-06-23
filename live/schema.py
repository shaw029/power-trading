"""Lightweight validators for the live GB BESS benchmark JSON artifacts.

These are deliberately dependency-free structural checks (not a full JSON-Schema
engine): each ``validate_*`` function walks one artifact shape from Appendix A of
the project spec, confirms the required keys are present with plausible types,
and raises :class:`SchemaError` on the first problem. They exist so that
:mod:`live.io_store` can validate a freshly written ``*.tmp`` file *before* it is
atomically promoted over a good target, guaranteeing a malformed artifact is
never published.

Every artifact carries ``"schema_version": 1`` (:data:`SCHEMA_VERSION`); changing
any shape requires bumping that constant.
"""

from typing import Any

# Current artifact schema version. Stamped on every written artifact and checked
# by every validator.
SCHEMA_VERSION: int = 1

# Required keys for the nested blocks of a per-day artifact.
_CONTEXT_KEYS: tuple[str, ...] = ("wind_gwh", "solar_gwh", "demand_gwh", "wind_share")
_DISPATCH_KEYS: tuple[str, ...] = (
    "period",
    "da_mw",
    "intraday_mw",
    "final_mw",
    "soc_after",
    "da_price",
    "mid_price",
    "trade_type",
    "rule_label",
)
_PNL_KEYS: tuple[str, ...] = (
    "benchmark_da_revenue",
    "intraday_da_improvement",
    "execution_costs_paid",
    "degradation_cost",
    "net_pnl",
)
_METRIC_KEYS: tuple[str, ...] = ("cycles", "capture")


class SchemaError(ValueError):
    """Raised when an artifact does not match its expected shape."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaError(message)


def _is_number(value: Any) -> bool:
    """True for a real (non-bool) int or float."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_number_or_none(value: Any) -> bool:
    return value is None or _is_number(value)


def _check_envelope(obj: Any) -> None:
    """Common checks shared by every artifact: object with the right version."""
    _require(isinstance(obj, dict), "artifact must be a JSON object")
    _require(
        obj.get("schema_version") == SCHEMA_VERSION,
        f"schema_version must be {SCHEMA_VERSION}",
    )


def _check_number_map(obj: dict, key: str) -> None:
    """A sub-dict mapping arbitrary string keys to numeric values."""
    value = obj.get(key)
    _require(isinstance(value, dict), f"'{key}' must be an object")
    assert isinstance(value, dict)
    for sub_key, sub_value in value.items():
        _require(
            _is_number(sub_value),
            f"'{key}.{sub_key}' must be a number",
        )


def _validate_asset(duration: str, asset: Any) -> None:
    _require(isinstance(asset, dict), f"asset '{duration}' must be an object")
    _require(_is_number(asset.get("capacity_mwh")), f"'{duration}.capacity_mwh' must be a number")
    _require(_is_number(asset.get("power_mw")), f"'{duration}.power_mw' must be a number")

    schedule = asset.get("schedule_mw")
    _require(isinstance(schedule, list), f"'{duration}.schedule_mw' must be a list")
    _require(all(_is_number(v) for v in schedule), f"'{duration}.schedule_mw' must be all numbers")

    dispatch = asset.get("dispatch")
    _require(isinstance(dispatch, list), f"'{duration}.dispatch' must be a list")
    for i, entry in enumerate(dispatch):
        _require(isinstance(entry, dict), f"'{duration}.dispatch[{i}]' must be an object")
        for key in _DISPATCH_KEYS:
            _require(key in entry, f"'{duration}.dispatch[{i}]' missing '{key}'")

    soc = asset.get("soc")
    _require(isinstance(soc, dict), f"'{duration}.soc' must be an object")
    _require(_is_number(soc.get("start")), f"'{duration}.soc.start' must be a number")
    _require(_is_number(soc.get("end")), f"'{duration}.soc.end' must be a number")
    track = soc.get("track")
    _require(isinstance(track, list), f"'{duration}.soc.track' must be a list")
    _require(all(_is_number(v) for v in track), f"'{duration}.soc.track' must be all numbers")

    pnl = asset.get("pnl")
    _require(isinstance(pnl, dict), f"'{duration}.pnl' must be an object")
    for key in _PNL_KEYS:
        _require(_is_number(pnl.get(key)), f"'{duration}.pnl.{key}' must be a number")

    metrics = asset.get("metrics")
    _require(isinstance(metrics, dict), f"'{duration}.metrics' must be an object")
    for key in _METRIC_KEYS:
        _require(_is_number(metrics.get(key)), f"'{duration}.metrics.{key}' must be a number")


def validate_day(obj: Any) -> None:
    """Validate a ``days/<YYYY-MM-DD>.json`` artifact."""
    _check_envelope(obj)
    _require(isinstance(obj.get("date"), str), "'date' must be a string")
    _require(_is_number(obj.get("resolution_h")), "'resolution_h' must be a number")

    prices = obj.get("prices")
    _require(isinstance(prices, dict), "'prices' must be an object")
    timestamps = prices.get("timestamps")
    da = prices.get("da")
    mid = prices.get("mid")
    _require(isinstance(timestamps, list), "'prices.timestamps' must be a list")
    _require(isinstance(da, list), "'prices.da' must be a list")
    _require(isinstance(mid, list), "'prices.mid' must be a list")
    _require(
        len(timestamps) == len(da) == len(mid),
        "'prices' timestamps/da/mid must be the same length",
    )
    _require(all(isinstance(t, str) for t in timestamps), "'prices.timestamps' must be all strings")
    _require(all(_is_number(v) for v in da), "'prices.da' must be all numbers")
    _require(all(_is_number(v) for v in mid), "'prices.mid' must be all numbers")

    context = obj.get("context")
    _require(isinstance(context, dict), "'context' must be an object")
    for key in _CONTEXT_KEYS:
        _require(_is_number_or_none(context.get(key)), f"'context.{key}' must be a number or null")

    labels = obj.get("labels")
    _require(isinstance(labels, list), "'labels' must be a list")
    _require(all(isinstance(label, str) for label in labels), "'labels' must be all strings")

    assets = obj.get("assets")
    _require(isinstance(assets, dict) and len(assets) > 0, "'assets' must be a non-empty object")
    for duration, asset in assets.items():
        _validate_asset(duration, asset)


def validate_latest(obj: Any) -> None:
    """Validate a ``latest.json`` artifact."""
    _check_envelope(obj)
    _require(isinstance(obj.get("date"), str), "'date' must be a string")
    _check_number_map(obj, "end_soc")
    _check_number_map(obj, "cumulative_net_pnl")


def validate_history(obj: Any) -> None:
    """Validate a ``history.json`` artifact."""
    _check_envelope(obj)
    rows = obj.get("rows")
    _require(isinstance(rows, list), "'rows' must be a list")
    for i, row in enumerate(rows):
        _require(isinstance(row, dict), f"'rows[{i}]' must be an object")
        _require(isinstance(row.get("date"), str), f"'rows[{i}].date' must be a string")
        _require(
            _is_number_or_none(row.get("da_spread")),
            f"'rows[{i}].da_spread' must be a number or null",
        )
        labels = row.get("labels")
        _require(isinstance(labels, list), f"'rows[{i}].labels' must be a list")
        _require(
            _is_number_or_none(row.get("wind_share")),
            f"'rows[{i}].wind_share' must be a number or null",
        )
        _require(
            _is_number_or_none(row.get("demand_gwh")),
            f"'rows[{i}].demand_gwh' must be a number or null",
        )
        _check_number_map(row, "net_pnl")
        _check_number_map(row, "cycles")


def validate_manifest(obj: Any) -> None:
    """Validate a ``manifest.json`` artifact."""
    _check_envelope(obj)
    available = obj.get("available_dates")
    _require(isinstance(available, list), "'available_dates' must be a list")
    _require(all(isinstance(d, str) for d in available), "'available_dates' must be all strings")
    durations = obj.get("durations")
    _require(isinstance(durations, list), "'durations' must be a list")
    _require(all(isinstance(d, str) for d in durations), "'durations' must be all strings")
    _require(isinstance(obj.get("reference_asset"), dict), "'reference_asset' must be an object")
