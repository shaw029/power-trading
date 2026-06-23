"""Canonical multi-duration BESS reference assets for the live GB benchmark.

The live benchmark runs the existing BESS engine on three reference batteries
that share a fixed 50 MW power rating but differ in storage duration (1h/2h/4h,
i.e. 50/100/200 MWh). Every non-capacity parameter — efficiencies, SOC band,
degradation cost, cycling target, margins and execution slippage — is read from
the ``bess`` block of ``configs/config.example.yaml`` via the shared config
loader, so this module never keeps a second copy of those numbers.
"""

from pathlib import Path

import yaml

from src.bess.bess_asset import BESSAsset
from src.utils.config import PROJECT_ROOT, validate_config

# Reference batteries are all rated at the same fixed power; only the storage
# duration (and therefore the energy capacity) varies between them.
REFERENCE_POWER_MW: float = 50.0

# Ordered duration keys; capacity_mwh = REFERENCE_POWER_MW * duration_hours.
REFERENCE_DURATIONS: tuple[str, ...] = ("1h", "2h", "4h")

_EXAMPLE_CONFIG_PATH: Path = PROJECT_ROOT / "configs" / "config.example.yaml"


def _duration_hours(duration: str) -> int:
    """Parse a duration key like ``"4h"`` into its integer hour count."""
    return int(duration.removesuffix("h"))


def bess_config() -> dict:
    """Return the per-run BESS config dict expected by ``run_intraday_session``.

    The numbers come straight from the example config: it is loaded and run
    through the shared ``validate_config`` (forced to the ``bess`` strategy) so
    the same defaults and execution-slippage surfacing the pipeline relies on
    are applied here too. The returned dict is the validated ``bess`` block.
    """
    raw = yaml.safe_load(_EXAMPLE_CONFIG_PATH.read_text())
    raw["strategy_type"] = "bess"
    validated = validate_config(raw)
    bess: dict = validated["bess"]
    return bess


def build_assets(initial_soc_pct: float = 0.5) -> dict[str, BESSAsset]:
    """Build one reference ``BESSAsset`` per duration, keyed by duration string.

    All assets share the non-capacity parameters from :func:`bess_config` and the
    fixed reference power; only ``capacity_mwh`` varies with duration. Each is
    initialised at ``initial_soc_pct``.
    """
    cfg = bess_config()
    assets: dict[str, BESSAsset] = {}
    for duration in REFERENCE_DURATIONS:
        hours = _duration_hours(duration)
        assets[duration] = BESSAsset(
            capacity_mwh=REFERENCE_POWER_MW * hours,
            power_mw=REFERENCE_POWER_MW,
            charge_efficiency=cfg["charge_efficiency"],
            discharge_efficiency=cfg["discharge_efficiency"],
            degradation_cost_per_mwh=cfg["degradation_cost_per_mwh"],
            initial_soc_pct=initial_soc_pct,
            min_soc_pct=cfg["min_soc_pct"],
            max_soc_pct=cfg["max_soc_pct"],
        )
    return assets
