import pandas as pd
import pytest

from src.evaluation.start_dates import coverage_start_windows, replay_account_window


def test_horizon_uses_coverage_and_discloses_delayed_monthly_start():
    july = pd.date_range("2018-07-23", "2018-08-31", tz="Europe/London")
    october = pd.date_range("2018-10-01", "2018-10-20", tz="Europe/London")
    november = pd.date_range("2018-11-02", "2018-11-28", tz="Europe/London")
    days, windows = coverage_start_windows(
        pd.Series(july.append(october).append(november)),
        ["2018-07-01", "2018-10-01", "2018-11-01"],
    )
    assert days == 20
    assert windows[0]["actual_start"].day == 23
    assert windows[2]["actual_start"].day == 2
    assert windows[1]["equal_end_exclusive"] == pd.Timestamp("2018-10-21", tz="Europe/London")


def test_london_days_across_dst_do_not_become_24_hour_offsets():
    dates = pd.date_range("2024-10-20", periods=20, tz="Europe/London")
    days, windows = coverage_start_windows(pd.Series(dates), ["2024-10-20"], 20)
    assert days == 20
    assert windows[0]["equal_end_exclusive"] == pd.Timestamp("2024-11-09", tz="Europe/London")
    assert (
        windows[0]["equal_end_exclusive"] - windows[0]["actual_start"]
    ).total_seconds() == 481 * 3600


def test_missing_month_is_not_silently_substituted():
    with pytest.raises(ValueError, match="No covered start"):
        coverage_start_windows(pd.Series(pd.to_datetime(["2018-09-01"], utc=True)), ["2018-08-01"])


def test_duplicate_observations_do_not_lengthen_the_horizon():
    dates = pd.Series(pd.to_datetime(["2018-08-01", "2018-08-01", "2018-08-02"], utc=True))
    days, _ = coverage_start_windows(dates, ["2018-08-01"])
    assert days == 2


def test_restart_does_not_inherit_losses_pending_books_or_halt_state():
    frame = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01T12:00:00Z", periods=4, freq="D"),
            "signal": 1,
            "day_ahead_price": 50.0,
            "system_sell_price": [0.0, 0.0, 60.0, 60.0],
            "system_buy_price": 50.0,
        }
    )
    out, m = replay_account_window(
        frame,
        pd.Timestamp("2024-01-03", tz="UTC"),
        pd.Timestamp("2024-01-05", tz="UTC"),
        starting_capital=1000.0,
        risk_pct=1.0,
        cost_per_trade=0.0,
    )
    assert out.pnl.tolist() == pytest.approx([200, 200])
    assert m["final_capital"] == pytest.approx(1400)
    assert m["halted_at_period"] is None
