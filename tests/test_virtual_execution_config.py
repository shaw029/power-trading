"""Pipeline gate sentinels must mean the same thing for entries and fills."""

import numpy as np
import pandas as pd
import pytest

from src import pipeline


@pytest.mark.parametrize("mid", [-1500.0, 20000.0])
@pytest.mark.parametrize("disabled", [900.0, 999.0])
def test_disabled_gate_survives_extreme_mid_but_enabled_gate_exits(
    tmp_path, monkeypatch, mid, disabled
):
    features = tmp_path / "features.parquet"
    features.touch()
    predictions = pd.DataFrame(
        {
            "time": pd.to_datetime(["2018-01-02T12:00Z"]),
            "predicted_spread": [10.0],
            "actual_spread": [10.0],
            "day_ahead_price": [50.0],
            "system_sell_price": [60.0],
            "system_buy_price": [60.0],
            "mid_price": [mid],
        }
    )
    monkeypatch.setattr(
        pipeline, "setup_experiment_paths", lambda *a, **k: {"features_file": features}
    )
    monkeypatch.setattr(pipeline, "train_model", lambda **k: (None, predictions, np.empty((1, 0))))
    monkeypatch.setattr(pipeline, "SAVE_OUTPUTS_DEFAULT", False)
    config = {
        "signal": {"threshold": 3, "top_n": 15, "vol_multiplier": 0, "transaction_cost": 1},
        "execution": {
            "baseline_hedge_ratio": 0,
            "take_profit_pct": disabled,
            "stop_loss_price_delta": disabled,
            "slippage": 2,
        },
        "model": {"type": "linear_regression", "hyperparameters": {}},
        "validation": {"type": "walk_forward", "train_days": 200, "test_days": 30, "step_days": 30},
    }
    result = pipeline._run_virtual_pipeline(config, skip_features=True)
    assert result["pnl_series"][0] == pytest.approx(180)  # 20 MWh * (£10 basis - £1 fee).
    config["execution"].update(take_profit_pct=0.9, stop_loss_price_delta=5)
    active = pipeline._run_virtual_pipeline(config, skip_features=True)
    assert active["pnl_series"][0] == pytest.approx(20 * (mid - 2 - 50 - 1))
