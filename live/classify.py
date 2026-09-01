"""Descriptive day-type tagging for the live GB BESS benchmark.

This module labels a single delivery day with zero or more human-readable tags
drawn from a fixed vocabulary. The vocabulary is flat, and split into two
independent families so downstream reporting can cross them without
circularity:

* **Fundamentals** — the physics. What the weather and human behaviour did:
  ``wind-led`` / ``wind-drought``, ``solar-led``, ``high-demand`` /
  ``low-demand``, and the calendar's ``weekend``.
* **Price traits** — the finance. How the market reacted to that physics:
  ``volatile`` / ``flat``, sub-zero hours (``negative-price``) and the intraday
  shape (``two-peak`` / ``single-peak``).

Keeping the families separate matters because a battery's revenue is largely a
function of the price character: "volatile days earn more" is close to a
tautology, whereas "wind-led days turn volatile and earn more" is a finding.
It also means composite regimes need no vocabulary of their own — a scarcity
day is simply where ``wind-drought`` and ``volatile`` overlap, which the
crossing chart shows directly rather than a hard-coded label asserting it.

The classifier is intentionally pure, deterministic and total: it consumes the
already-fetched price frame and context dict from :mod:`live.fetch_live` (A2),
returns a list (possibly empty), and never raises — context fields that are
``None`` simply suppress the tags that depend on them.
"""

import pandas as pd

# The two tag families. Kept as module-level constants so callers and tests can
# assert against the exact vocabulary and split charts by family.
DRIVER_TAGS: frozenset[str] = frozenset(
    {"wind-led", "wind-drought", "solar-led", "high-demand", "low-demand", "weekend"}
)
PRICE_TAGS: frozenset[str] = frozenset(
    {"volatile", "flat", "negative-price", "two-peak", "single-peak"}
)
TAGS: frozenset[str] = DRIVER_TAGS | PRICE_TAGS

# Thresholds for the descriptive tags. Each value is documented with the basis
# for its magnitude; they are deliberately conservative round numbers rather
# than fitted parameters, since the tags are descriptive labels, not signals.
DEFAULTS: dict[str, float] = {
    # Day-ahead intraday spread (max - min over the day), in £/MWh.
    # A quiet GB day rarely swings more than ~£20/MWh peak-to-trough, whereas a
    # genuinely volatile day blows well past £60/MWh; the gap in between is left
    # untagged so only clear-cut days earn "flat" or "volatile".
    "volatile_spread": 60.0,
    "flat_spread": 20.0,
    # Wind share of total generation (0-1). GB wind routinely supplies a large
    # slice of the mix; ~40%+ marks a day where wind clearly dominates.
    "wind_share": 0.40,
    # The other end of the same axis. GB wind share averages roughly a quarter
    # to a third of generation across a year, so a day at or below 15% is a
    # genuine lull — the residual load the rest of the fleet must carry, and
    # the setup for a scarcity day. The band between this and "wind_share" is
    # left untagged so only clear-cut days earn either label.
    "wind_drought_share": 0.15,
    # Solar energy over the day, in GWh. GB solar output is modest — annual
    # generation averages only ~35-40 GWh/day — so a sunny day stands out well
    # below the wind scale; ~55 GWh/day reflects a strong clear-sky summer day.
    "solar_gwh": 55.0,
    # Total demand over the day, in GWh. GB daily demand runs roughly
    # 600-900 GWh across the year; these bounds flag the clearly high and clearly
    # low days while leaving typical mid-range days untagged.
    "high_demand_gwh": 820.0,
    "low_demand_gwh": 600.0,
    # A morning/evening peak "exists" when its window maximum rises at least
    # this far (£/MWh) above the midday trough. £15 is enough to clear normal
    # intraday noise but small enough to catch both humps of a classic GB
    # two-peak day.
    "peak_prominence": 15.0,
}

# UTC hour windows for the intraday shape tags. GB local time is UTC or UTC+1,
# which is close enough for windows this wide; the exact boundaries matter far
# less than the prominence threshold.
_MORNING_HOURS = range(5, 12)
_MIDDAY_HOURS = range(12, 16)
_EVENING_HOURS = range(16, 22)


def _day_ahead_spread(prices: pd.DataFrame) -> float | None:
    """Peak-to-trough day-ahead price spread, or ``None`` if unavailable."""
    if "day_ahead_price" not in prices.columns:
        return None
    series = prices["day_ahead_price"].dropna()
    if series.empty:
        return None
    return float(series.max() - series.min())


def _peak_shape(prices: pd.DataFrame, prominence: float) -> str | None:
    """``"two-peak"``, ``"single-peak"`` or ``None`` for a shapeless day.

    A peak exists when the maximum of its window (morning 05–12 or evening
    16–22 UTC) rises at least ``prominence`` above the midday-trough minimum.
    Days without a usable hourly index or without midday coverage are left
    untagged rather than guessed at.
    """
    if "day_ahead_price" not in prices.columns or not isinstance(prices.index, pd.DatetimeIndex):
        return None
    series = prices["day_ahead_price"].dropna()
    if series.empty:
        return None
    hours = series.index.hour
    midday = series[hours.isin(_MIDDAY_HOURS)]
    if midday.empty:
        return None
    trough = float(midday.min())
    peaks = 0
    for window in (_MORNING_HOURS, _EVENING_HOURS):
        in_window = series[hours.isin(window)]
        if not in_window.empty and float(in_window.max()) - trough >= prominence:
            peaks += 1
    if peaks == 2:
        return "two-peak"
    if peaks == 1:
        return "single-peak"
    return None


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
        :func:`live.fetch_live.get_day_prices` (column ``day_ahead_price``
        drives the price-character tags; the UTC index drives ``weekend``).
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
        Zero or more tags from :data:`TAGS`, driver tags first, in a fixed
        deterministic order. Never raises.
    """
    # Back any custom dictionary with the defaults so an omitted threshold key
    # never raises a KeyError below.
    thresholds = {**DEFAULTS, **thresholds}

    tags: list[str] = []

    # --- Driver tags: what caused the day. -------------------------------- #
    wind_share = context.get("wind_share")
    if wind_share is not None:
        if wind_share >= thresholds["wind_share"]:
            tags.append("wind-led")
        elif wind_share <= thresholds["wind_drought_share"]:
            tags.append("wind-drought")

    solar_gwh = context.get("solar_gwh")
    if solar_gwh is not None and solar_gwh >= thresholds["solar_gwh"]:
        tags.append("solar-led")

    demand_gwh = context.get("demand_gwh")
    if demand_gwh is not None:
        if demand_gwh >= thresholds["high_demand_gwh"]:
            tags.append("high-demand")
        elif demand_gwh <= thresholds["low_demand_gwh"]:
            tags.append("low-demand")

    if isinstance(prices.index, pd.DatetimeIndex) and len(prices.index):
        if int(prices.index[0].dayofweek) >= 5:
            tags.append("weekend")

    # --- Price-character tags: how prices behaved. ------------------------ #
    spread = _day_ahead_spread(prices)
    if spread is not None:
        if spread >= thresholds["volatile_spread"]:
            tags.append("volatile")
        elif spread <= thresholds["flat_spread"]:
            tags.append("flat")

    if "day_ahead_price" in prices.columns:
        da = prices["day_ahead_price"].dropna()
        if not da.empty and float(da.min()) < 0.0:
            tags.append("negative-price")

    shape = _peak_shape(prices, thresholds["peak_prominence"])
    if shape is not None:
        tags.append(shape)

    return tags
