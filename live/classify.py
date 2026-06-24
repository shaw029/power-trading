"""Descriptive day-type tagging for the live GB BESS benchmark.

This module labels a single delivery day with zero or more human-readable tags
drawn from a fixed vocabulary. The tags summarise *why* a day looked the way it
did — was it windy, sunny, a high-demand day, was the price curve volatile — so
that downstream reporting can group and compare days by character rather than by
raw numbers.

The classifier is intentionally pure, deterministic and total: it consumes the
already-fetched price frame and context dict from :mod:`live.fetch_live` (A2),
returns a list (possibly empty), and never raises — context fields that are
``None`` simply suppress the tags that depend on them.
"""

import pandas as pd

# Every tag this module can ever emit. Kept as a module-level constant so callers
# and tests can assert against the exact vocabulary.
TAGS: frozenset[str] = frozenset(
    {"windy", "sunny", "volatile", "calm", "high_demand", "low_demand"}
)

# Thresholds for the descriptive tags. Each value is documented with the basis
# for its magnitude; they are deliberately conservative round numbers rather
# than fitted parameters, since the tags are descriptive labels, not signals.
DEFAULTS: dict[str, float] = {
    # Day-ahead intraday spread (max - min over the day), in £/MWh.
    # A quiet GB day rarely swings more than ~£20/MWh peak-to-trough, whereas a
    # genuinely volatile day blows well past £60/MWh; the gap in between is left
    # untagged so only clear-cut days earn "calm" or "volatile".
    "volatile_spread": 60.0,
    "calm_spread": 20.0,
    # Wind share of total generation (0-1). GB wind routinely supplies a large
    # slice of the mix; ~40%+ marks a day where wind clearly dominates.
    "wind_share": 0.40,
    # Solar energy over the day, in GWh. GB solar output is modest — annual
    # generation averages only ~35-40 GWh/day — so a sunny day stands out well
    # below the wind scale; ~55 GWh/day reflects a strong clear-sky summer day.
    "solar_gwh": 55.0,
    # Total demand over the day, in GWh. GB daily demand runs roughly
    # 600-900 GWh across the year; these bounds flag the clearly high and clearly
    # low days while leaving typical mid-range days untagged.
    "high_demand_gwh": 820.0,
    "low_demand_gwh": 600.0,
}


def _day_ahead_spread(prices: pd.DataFrame) -> float | None:
    """Peak-to-trough day-ahead price spread, or ``None`` if unavailable."""
    if "day_ahead_price" not in prices.columns:
        return None
    series = prices["day_ahead_price"].dropna()
    if series.empty:
        return None
    return float(series.max() - series.min())


def classify(
    prices: pd.DataFrame,
    context: dict[str, float | None],
    thresholds: dict[str, float] = DEFAULTS,
) -> list[str]:
    """Return descriptive day-type tags for one delivery day.

    Parameters
    ----------
    prices:
        Hourly price frame for the day, as produced by
        :func:`live.fetch_live.get_day_prices` (column ``day_ahead_price`` is
        used for the volatility tags).
    context:
        Tier-2 aggregates for the day, as produced by
        :func:`live.fetch_live.get_day_context` (keys ``wind_share``,
        ``solar_gwh`` and ``demand_gwh`` are consulted). Any field may be
        ``None``, in which case the dependent tag is simply omitted.
    thresholds:
        Threshold dictionary; defaults to :data:`DEFAULTS`. A custom dictionary
        need only override the keys it cares about — any key it omits falls back
        to the corresponding :data:`DEFAULTS` value.

    Returns
    -------
    list[str]
        Zero or more tags from :data:`TAGS`, in a fixed deterministic order.
        Never raises.
    """
    # Back any custom dictionary with the defaults so an omitted threshold key
    # never raises a KeyError below.
    thresholds = {**DEFAULTS, **thresholds}

    tags: list[str] = []

    # Price-derived tags: volatility of the day-ahead curve.
    spread = _day_ahead_spread(prices)
    if spread is not None:
        if spread >= thresholds["volatile_spread"]:
            tags.append("volatile")
        elif spread <= thresholds["calm_spread"]:
            tags.append("calm")

    # Context-derived tags. Each guards against a missing (``None``) field.
    wind_share = context.get("wind_share")
    if wind_share is not None and wind_share >= thresholds["wind_share"]:
        tags.append("windy")

    solar_gwh = context.get("solar_gwh")
    if solar_gwh is not None and solar_gwh >= thresholds["solar_gwh"]:
        tags.append("sunny")

    demand_gwh = context.get("demand_gwh")
    if demand_gwh is not None:
        if demand_gwh >= thresholds["high_demand_gwh"]:
            tags.append("high_demand")
        elif demand_gwh <= thresholds["low_demand_gwh"]:
            tags.append("low_demand")

    return tags
