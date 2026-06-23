from live.assets import REFERENCE_DURATIONS, build_assets, bess_config
from src.bess.bess_asset import BESSAsset

_EXPECTED_CAPACITIES = {"1h": 50.0, "2h": 100.0, "4h": 200.0}


def test_build_assets_returns_one_asset_per_duration():
    assets = build_assets()
    assert len(assets) == 3
    assert set(assets) == set(REFERENCE_DURATIONS)
    assert all(isinstance(a, BESSAsset) for a in assets.values())


def test_all_assets_share_fixed_power():
    assets = build_assets()
    assert all(a.power_mw == 50 for a in assets.values())


def test_capacities_scale_with_duration():
    assets = build_assets()
    for duration, asset in assets.items():
        hours = int(duration.removesuffix("h"))
        assert asset.capacity_mwh == 50 * hours
        assert asset.capacity_mwh == _EXPECTED_CAPACITIES[duration]


def test_assets_respect_config_soc_bounds():
    cfg = bess_config()
    assert cfg["min_soc_pct"] == 0.10
    assert cfg["max_soc_pct"] == 0.90
    for asset in build_assets().values():
        assert asset.min_soc_pct == 0.10
        assert asset.max_soc_pct == 0.90


def test_initial_soc_is_configurable():
    assets = build_assets(initial_soc_pct=0.25)
    for asset in assets.values():
        assert asset.soc_pct == 0.25
