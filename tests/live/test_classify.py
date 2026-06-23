"""Tests for the pure day-type classifier.

All inputs are synthetic in-memory frames and dicts, so no network or file IO
happens. The classifier must always return a list and never raise.
"""

import pandas as pd

from live import classify
from live.classify import DEFAULTS, TAGS


def _prices(values: list[float]) -> pd.DataFrame:
    """Hourly day-ahead price frame from a list of period prices."""
    times = pd.date_range("2024-06-01T00:00:00Z", periods=len(values), freq="60min")
    return pd.DataFrame({"day_ahead_price": values, "mid_price": values}, index=times)


def _full_context() -> dict[str, float | None]:
    """A bland context that triggers none of the context-derived tags."""
    return {
        "wind_gwh": 100.0,
        "solar_gwh": 10.0,
        "demand_gwh": 700.0,
        "wind_share": 0.10,
    }


def test_high_spread_day_is_volatile() -> None:
    prices = _prices([10.0] * 12 + [10.0 + DEFAULTS["volatile_spread"] + 50.0] * 12)
    tags = classify.classify(prices, _full_context())
    assert "volatile" in tags
    assert "calm" not in tags


def test_flat_day_is_calm() -> None:
    prices = _prices([50.0] * 24)
    tags = classify.classify(prices, _full_context())
    assert "calm" in tags
    assert "volatile" not in tags


def test_high_wind_share_is_windy() -> None:
    context = _full_context()
    context["wind_share"] = DEFAULTS["wind_share"] + 0.2
    tags = classify.classify(_prices([50.0] * 24), context)
    assert "windy" in tags


def test_all_none_context_returns_price_tags_only() -> None:
    none_context: dict[str, float | None] = {
        "wind_gwh": None,
        "solar_gwh": None,
        "demand_gwh": None,
        "wind_share": None,
    }
    # A clearly volatile price curve so a price-derived tag is still produced.
    prices = _prices([10.0] * 12 + [200.0] * 12)
    tags = classify.classify(prices, none_context)
    assert tags == ["volatile"]


def test_returns_only_known_tags_and_never_raises() -> None:
    # Empty prices and an empty context must still yield a (possibly empty) list.
    empty = pd.DataFrame(columns=["day_ahead_price", "mid_price"])
    tags = classify.classify(empty, {})
    assert isinstance(tags, list)
    assert set(tags) <= TAGS


def test_high_and_low_demand() -> None:
    high = _full_context()
    high["demand_gwh"] = DEFAULTS["high_demand_gwh"] + 50.0
    assert "high_demand" in classify.classify(_prices([50.0] * 24), high)

    low = _full_context()
    low["demand_gwh"] = DEFAULTS["low_demand_gwh"] - 50.0
    assert "low_demand" in classify.classify(_prices([50.0] * 24), low)
