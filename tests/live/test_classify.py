"""Tests for the pure day-type classifier.

All inputs are synthetic in-memory frames and dicts, so no network or file IO
happens. The classifier must always return a list and never raise.
"""

import pandas as pd

from live import classify
from live.classify import DEFAULTS, DRIVER_TAGS, PRICE_TAGS, TAGS

# A Monday, so the weekend tag stays out of tests that aren't about it.
_WEEKDAY = "2024-06-03"


def _prices(values: list[float], date: str = _WEEKDAY) -> pd.DataFrame:
    """Hourly day-ahead price frame from a list of period prices."""
    times = pd.date_range(f"{date}T00:00:00Z", periods=len(values), freq="60min")
    return pd.DataFrame({"day_ahead_price": values, "mid_price": values}, index=times)


def _full_context() -> dict[str, float | None]:
    """A bland context that triggers none of the context-derived tags."""
    return {
        "wind_gwh": 100.0,
        "solar_gwh": 10.0,
        "demand_gwh": 700.0,
        "wind_share": 0.10,
    }


def test_tag_families_partition_the_vocabulary() -> None:
    assert DRIVER_TAGS | PRICE_TAGS == TAGS
    assert not DRIVER_TAGS & PRICE_TAGS


def test_high_spread_day_is_volatile() -> None:
    prices = _prices([10.0] * 12 + [10.0 + DEFAULTS["volatile_spread"] + 50.0] * 12)
    tags = classify.classify(prices, _full_context())
    assert "volatile" in tags
    assert "flat" not in tags


def test_level_day_is_flat() -> None:
    prices = _prices([50.0] * 24)
    tags = classify.classify(prices, _full_context())
    assert "flat" in tags
    assert "volatile" not in tags


def test_high_wind_share_is_wind_led() -> None:
    context = _full_context()
    context["wind_share"] = DEFAULTS["wind_share"] + 0.2
    tags = classify.classify(_prices([50.0] * 24), context)
    assert "wind-led" in tags
    assert "wind-drought" not in tags


def test_low_wind_share_is_a_wind_drought() -> None:
    context = _full_context()
    context["wind_share"] = DEFAULTS["wind_drought_share"] - 0.05
    tags = classify.classify(_prices([50.0] * 24), context)
    assert "wind-drought" in tags
    assert "wind-led" not in tags


def test_mid_wind_share_earns_neither_wind_tag() -> None:
    # The band between the two thresholds is deliberately untagged, so only
    # clear-cut days carry a wind label.
    context = _full_context()
    context["wind_share"] = (DEFAULTS["wind_drought_share"] + DEFAULTS["wind_share"]) / 2
    tags = classify.classify(_prices([50.0] * 24), context)
    assert "wind-led" not in tags
    assert "wind-drought" not in tags


def test_high_solar_is_solar_led() -> None:
    context = _full_context()
    context["solar_gwh"] = DEFAULTS["solar_gwh"] + 10.0
    tags = classify.classify(_prices([50.0] * 24), context)
    assert "solar-led" in tags

    # Just below the threshold the tag is withheld.
    context["solar_gwh"] = DEFAULTS["solar_gwh"] - 10.0
    assert "solar-led" not in classify.classify(_prices([50.0] * 24), context)


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
    assert "volatile" in tags
    assert not set(tags) & DRIVER_TAGS


def test_returns_only_known_tags_and_never_raises() -> None:
    # Empty prices and an empty context must still yield a (possibly empty) list.
    empty = pd.DataFrame(columns=["day_ahead_price", "mid_price"])
    tags = classify.classify(empty, {})
    assert isinstance(tags, list)
    assert set(tags) <= TAGS


def test_high_and_low_demand() -> None:
    high = _full_context()
    high["demand_gwh"] = DEFAULTS["high_demand_gwh"] + 50.0
    assert "high-demand" in classify.classify(_prices([50.0] * 24), high)

    low = _full_context()
    low["demand_gwh"] = DEFAULTS["low_demand_gwh"] - 50.0
    assert "low-demand" in classify.classify(_prices([50.0] * 24), low)


def test_weekend_tag_from_the_index_date() -> None:
    saturday = _prices([50.0] * 24, date="2024-06-01")
    assert "weekend" in classify.classify(saturday, _full_context())
    monday = _prices([50.0] * 24, date=_WEEKDAY)
    assert "weekend" not in classify.classify(monday, _full_context())


def test_negative_prices_tag() -> None:
    values = [50.0] * 24
    values[3] = -5.0
    assert "negative-price" in classify.classify(_prices(values), _full_context())
    assert "negative-price" not in classify.classify(
        _prices([0.0] + [50.0] * 23), _full_context()
    )


def test_two_peak_shape() -> None:
    # Flat £40 base, £30-prominent humps at 08:00 and 18:00 over a £40 midday.
    values = [40.0] * 24
    values[8] = 70.0
    values[18] = 70.0
    tags = classify.classify(_prices(values), _full_context())
    assert "two-peak" in tags
    assert "single-peak" not in tags


def test_single_peak_shape() -> None:
    # Only the evening hump clears the prominence threshold.
    values = [40.0] * 24
    values[18] = 70.0
    tags = classify.classify(_prices(values), _full_context())
    assert "single-peak" in tags
    assert "two-peak" not in tags


def test_level_day_has_no_shape_tag() -> None:
    tags = classify.classify(_prices([50.0] * 24), _full_context())
    assert "single-peak" not in tags
    assert "two-peak" not in tags
