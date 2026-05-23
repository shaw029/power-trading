"""Unit tests for config loading and validation (strategy_type, bess block)."""

import pytest

from src.utils.config import validate_config, _BESS_DEFAULTS


class TestStrategyType:
    def test_default_strategy_type_is_virtual(self):
        cfg = validate_config({})
        assert cfg["strategy_type"] == "virtual"

    def test_virtual_strategy_type(self):
        cfg = validate_config({"strategy_type": "virtual"})
        assert cfg["strategy_type"] == "virtual"

    def test_bess_strategy_type(self):
        cfg = validate_config({"strategy_type": "bess"})
        assert cfg["strategy_type"] == "bess"

    def test_invalid_strategy_type_raises(self):
        with pytest.raises(ValueError, match="Invalid strategy_type"):
            validate_config({"strategy_type": "nuclear"})


class TestBessConfig:
    def test_bess_block_parses_with_defaults(self):
        cfg = validate_config({"strategy_type": "bess"})
        bess = cfg["bess"]
        for key, expected in _BESS_DEFAULTS.items():
            assert bess[key] == expected

    def test_bess_block_custom_values(self):
        cfg = validate_config({
            "strategy_type": "bess",
            "bess": {
                "capacity_mwh": 200.0,
                "power_mw": 100.0,
                "round_trip_efficiency": 0.92,
                "degradation_cost_per_mwh": 5.00,
                "initial_soc_pct": 0.80,
            },
        })
        assert cfg["bess"]["capacity_mwh"] == 200.0
        assert cfg["bess"]["round_trip_efficiency"] == 0.92

    def test_bess_partial_override_fills_defaults(self):
        cfg = validate_config({
            "strategy_type": "bess",
            "bess": {"capacity_mwh": 50.0},
        })
        assert cfg["bess"]["capacity_mwh"] == 50.0
        assert cfg["bess"]["power_mw"] == _BESS_DEFAULTS["power_mw"]

    def test_virtual_does_not_inject_bess_block(self):
        cfg = validate_config({"strategy_type": "virtual"})
        assert "bess" not in cfg
