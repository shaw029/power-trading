"""Unit tests for config loading and validation."""

import pytest

from src.utils.config import validate_config, get_periods, get_sources, _BESS_DEFAULTS

_MINIMAL_DATA = {
    "data": {
        "periods": [{"start": "2018-01-01", "end": "2019-01-01", "demand_source": "ENTSOE"}],
    },
}


def _cfg(**overrides: object) -> dict:  # type: ignore[type-arg]
    base: dict[str, object] = {**_MINIMAL_DATA}
    base.update(overrides)
    return base


class TestStrategyType:
    def test_default_strategy_type_is_virtual(self):
        cfg = validate_config(_cfg())
        assert cfg["strategy_type"] == "virtual"

    def test_virtual_strategy_type(self):
        cfg = validate_config(_cfg(strategy_type="virtual"))
        assert cfg["strategy_type"] == "virtual"

    def test_bess_strategy_type(self):
        cfg = validate_config(_cfg(strategy_type="bess"))
        assert cfg["strategy_type"] == "bess"

    def test_invalid_strategy_type_raises(self):
        with pytest.raises(ValueError, match="Invalid strategy_type"):
            validate_config(_cfg(strategy_type="nuclear"))


class TestBessConfig:
    def test_bess_block_parses_with_defaults(self):
        cfg = validate_config(_cfg(strategy_type="bess"))
        bess = cfg["bess"]
        for key, expected in _BESS_DEFAULTS.items():
            assert bess[key] == expected

    def test_bess_block_custom_values(self):
        cfg = validate_config(
            _cfg(
                strategy_type="bess",
                bess={
                    "capacity_mwh": 200.0,
                    "power_mw": 100.0,
                    "charge_efficiency": 0.96,
                    "discharge_efficiency": 0.96,
                    "degradation_cost_per_mwh": 5.00,
                    "initial_soc_pct": 0.80,
                },
            )
        )
        assert cfg["bess"]["capacity_mwh"] == 200.0
        assert cfg["bess"]["charge_efficiency"] == 0.96

    def test_bess_partial_override_fills_defaults(self):
        cfg = validate_config(
            _cfg(
                strategy_type="bess",
                bess={"capacity_mwh": 50.0},
            )
        )
        assert cfg["bess"]["capacity_mwh"] == 50.0
        assert cfg["bess"]["power_mw"] == _BESS_DEFAULTS["power_mw"]

    def test_virtual_does_not_inject_bess_block(self):
        cfg = validate_config(_cfg(strategy_type="virtual"))
        assert "bess" not in cfg


class TestDataPeriods:
    def test_missing_data_raises(self):
        with pytest.raises(ValueError, match="data.periods"):
            validate_config({"strategy_type": "virtual"})

    def test_empty_periods_raises(self):
        with pytest.raises(ValueError, match="data.periods"):
            validate_config({"strategy_type": "virtual", "data": {"periods": []}})

    def test_missing_field_raises(self):
        with pytest.raises(ValueError, match="missing required field"):
            validate_config(
                {
                    "strategy_type": "virtual",
                    "data": {
                        "periods": [
                            {"start": "2018-01-01", "end": "2019-01-01"},
                        ]
                    },
                }
            )

    def test_bad_demand_source_raises(self):
        with pytest.raises(ValueError, match="demand_source"):
            validate_config(
                {
                    "strategy_type": "virtual",
                    "data": {
                        "periods": [
                            {"start": "2018-01-01", "end": "2019-01-01", "demand_source": "BOGUS"},
                        ]
                    },
                }
            )

    def test_overlapping_periods_raises(self):
        with pytest.raises(ValueError, match="overlap"):
            validate_config(
                {
                    "strategy_type": "virtual",
                    "data": {
                        "periods": [
                            {"start": "2018-01-01", "end": "2019-01-01", "demand_source": "ENTSOE"},
                            {"start": "2018-06-01", "end": "2019-06-01", "demand_source": "ENTSOE"},
                        ]
                    },
                }
            )

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError, match="must be before"):
            validate_config(
                {
                    "strategy_type": "virtual",
                    "data": {
                        "periods": [
                            {"start": "2019-01-01", "end": "2018-01-01", "demand_source": "ENTSOE"},
                        ]
                    },
                }
            )

    def test_valid_periods(self):
        cfg = validate_config(_cfg())
        periods = get_periods(cfg)
        assert len(periods) == 1
        assert periods[0]["demand_source"] == "ENTSOE"

    def test_adjacent_periods_allowed(self):
        cfg = validate_config(
            {
                "strategy_type": "virtual",
                "data": {
                    "periods": [
                        {"start": "2017-01-01", "end": "2018-01-01", "demand_source": "ENTSOE"},
                        {"start": "2018-01-01", "end": "2019-01-01", "demand_source": "NESO_API"},
                    ]
                },
            }
        )
        assert len(get_periods(cfg)) == 2


class TestDataSources:
    def test_defaults_applied(self):
        cfg = validate_config(_cfg())
        sources = get_sources(cfg)
        assert sources["wind_source"] == "ELEXON"
        assert sources["day_ahead_price_source"] == "ENTSOE"

    def test_custom_source(self):
        data = {
            "periods": [{"start": "2018-01-01", "end": "2019-01-01", "demand_source": "ENTSOE"}],
            "wind_source": "CSV",
        }
        cfg = validate_config({"strategy_type": "virtual", "data": data})
        assert get_sources(cfg)["wind_source"] == "CSV"

    def test_invalid_source_raises(self):
        data = {
            "periods": [{"start": "2018-01-01", "end": "2019-01-01", "demand_source": "ENTSOE"}],
            "wind_source": "INVALID",
        }
        with pytest.raises(ValueError, match="wind_source"):
            validate_config({"strategy_type": "virtual", "data": data})
