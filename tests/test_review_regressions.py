"""Information-time, coverage and cache regressions from the research audit."""

import datetime as dt
import os
import time

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import run_backtest
from src.data.market_calendar import complete_resample, complete_market_days, market_day_grid
from src.data.preprocess import process_day_ahead_price
from src.features.build_features import auction_decision_time
from src.models.train import purge_unavailable_labels, train_with_validation
from src.utils.raw_cache import cache_is_fresh
from src.utils.provenance import fingerprint


@pytest.mark.parametrize(
    "times,signals",
    [
        (["2018-01-01", "2018-01-02", "2018-01-03"], [1, 0, 1]),
        (["2018-01-01", "2018-01-02", "2018-01-03"], [1, 1, 1]),
        (["2018-01-01", "2018-01-05", "2018-01-09"], [1, 0, 1]),
    ],
)
def test_settlement_is_released_across_empty_days_and_gaps(times, signals):
    pnl, metrics = run_backtest(
        signals, [50] * 3, [-1000, 50, 60], [-1000, 50, 60], timestamps=times, cost_per_trade=0
    )
    assert pnl.tolist() == [-21000, 0, 0]
    assert metrics["halted_at_period"] is not None


def test_quantity_does_not_depend_on_cleared_da_price():
    quantities = []
    for price in [1, 50, 500, -100]:
        _, m = run_backtest([1], [price], [60], [60], cost_per_trade=0)
        quantities.append(m["total_position_mwh"])
    assert quantities == [20] * 4


@pytest.mark.parametrize("day,hours", [("2018-03-25", 23), ("2018-10-28", 25), ("2018-07-01", 24)])
def test_london_calendar_and_native_coverage(day, hours):
    idx = market_day_grid(day, "30min")
    assert len(idx) == 2 * hours
    full = pd.Series(1.0, index=idx)
    assert len(complete_market_days(complete_resample(full))) == 1
    partial = full.drop(full.index[1])
    assert complete_resample(partial).iloc[0] is np.nan or pd.isna(
        complete_resample(partial).iloc[0]
    )
    assert not complete_market_days(complete_resample(partial))


def test_last_hour_expands_but_missing_hour_is_not_filled():
    raw = pd.DataFrame(
        {"time": pd.to_datetime(["2018-01-01T00:00Z", "2018-01-01T02:00Z"]), "value": [10, 30]}
    )
    out = process_day_ahead_price(raw).day_ahead_price
    assert out.iloc[-1] == 30
    assert out.index[-1].minute == 30
    assert out.iloc[2:4].isna().all()


def test_labels_use_period_end_and_publication_delay():
    frame = pd.DataFrame({"time": pd.date_range("2018-01-02T08:30Z", periods=5, freq="30min")})
    assert purge_unavailable_labels(frame, "2018-01-03").time.max() == pd.Timestamp(
        "2018-01-02T09:00Z"
    )
    assert purge_unavailable_labels(
        frame, "2018-01-03", pd.Timedelta(0)
    ).time.max() == pd.Timestamp("2018-01-02T10:00Z")


@pytest.mark.parametrize("day", ["2018-03-25", "2018-03-26", "2018-10-28", "2018-10-29"])
def test_decision_time_remains_1030_london_across_dst(day):
    out = auction_decision_time(pd.Series([pd.Timestamp(day, tz="Europe/London")])).dt.tz_convert(
        "Europe/London"
    )
    assert out.iloc[0].hour == 10 and out.iloc[0].minute == 30
    assert out.iloc[0].date() == pd.Timestamp(day).date() - dt.timedelta(days=1)


def test_recent_raw_cache_expires_but_historical_cache_remains(tmp_path):
    path = tmp_path / "day.json"
    path.write_text("{}")
    today = dt.datetime.now(dt.timezone.utc).date()
    assert cache_is_fresh(path, today)
    os.utime(path, (time.time() - 3600, time.time() - 3600))
    assert not cache_is_fresh(path, today)
    assert cache_is_fresh(path, today - dt.timedelta(days=6))


def test_cache_changes_with_preprocessing_config_and_feature_bytes(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    code = src / "preprocess.py"
    code.write_text("a=1")
    feat = tmp_path / "features"
    feat.write_bytes(b"old")
    old = fingerprint(tmp_path, {"threshold": 1}, features=feat)
    code.write_text("a=2")
    assert fingerprint(tmp_path, {"threshold": 1}, features=feat) != old
    current = fingerprint(tmp_path, {"threshold": 1}, features=feat)
    feat.write_bytes(b"new")
    assert fingerprint(tmp_path, {"threshold": 1}, features=feat) != current
    assert fingerprint(tmp_path, {"threshold": 2}, features=feat) != fingerprint(
        tmp_path, {"threshold": 1}, features=feat
    )


def test_selection_does_not_predict_reserved_holdout():
    frame = pd.DataFrame(
        {"time": pd.date_range("2018-01-01", periods=60 * 48, freq="30min", tz="UTC")}
    )
    frame["x"] = np.arange(len(frame))
    frame["y"] = frame.x % 48
    preds, _, _ = train_with_validation(
        frame,
        ["x"],
        "y",
        validation_type="walk_forward",
        model_type="linear_regression",
        wf_train_days=20,
        wf_test_days=10,
        wf_step_days=10,
        holdout_days=10,
        evaluate_holdout=False,
    )
    assert set(preds.split) == {"development"}
    assert preds.time.max() < pd.Timestamp("2018-02-20", tz="UTC")
