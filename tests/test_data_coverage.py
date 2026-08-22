"""Tests for raw-feed coverage accounting and the backfill driver.

No network: coverage is a filesystem question, and the backfill's fetchers are
mocked. What matters is that coverage reads every cache naming convention the
repository actually uses, that the backfill asks only for the days it lacks,
and that a day which fails is recorded rather than aborting the run.
"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

from src.data import coverage as cov

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "backfill_market_data", REPO_ROOT / "scripts" / "backfill_market_data.py"
)
assert _spec is not None and _spec.loader is not None
backfill = importlib.util.module_from_spec(_spec)
sys.modules["backfill_market_data"] = backfill
_spec.loader.exec_module(backfill)


@pytest.fixture
def raw_dir(tmp_path):
    """A cache tree using all three filename conventions in the repository."""
    (tmp_path / "MID").mkdir()
    (tmp_path / "MID" / "MID_20240101_page_1.json").write_text("{}")
    (tmp_path / "MID" / "MID_20240101_page_2.json").write_text("{}")  # paged: one day
    (tmp_path / "MID" / "MID_20240103_page_1.json").write_text("{}")
    (tmp_path / "LOLPDRM").mkdir()
    (tmp_path / "LOLPDRM" / "LOLPDRM_20240102.json").write_text("{}")
    (tmp_path / "FLEET_PN").mkdir()
    (tmp_path / "FLEET_PN" / "FLEET_PN_2024-01-02.json").write_text("{}")
    return str(tmp_path)


def test_reads_every_filename_convention(raw_dir):
    assert cov.cached_days("MID", raw_dir) == {dt.date(2024, 1, 1), dt.date(2024, 1, 3)}
    assert cov.cached_days("LOLPDRM", raw_dir) == {dt.date(2024, 1, 2)}
    assert cov.cached_days("FLEET_PN", raw_dir) == {dt.date(2024, 1, 2)}


def test_absent_feed_reads_as_empty_not_an_error(raw_dir):
    """A feed the current config never fetched is a normal state."""
    assert cov.cached_days("WINDFOR", raw_dir) == set()


def test_missing_days_are_the_gap_in_the_window(raw_dir):
    missing = cov.missing_days("MID", dt.date(2024, 1, 1), dt.date(2024, 1, 4), raw_dir)
    assert missing == [dt.date(2024, 1, 2), dt.date(2024, 1, 4)]


def test_summary_counts_only_days_inside_the_window(raw_dir):
    summary = cov.coverage_summary(
        dt.date(2024, 1, 2), dt.date(2024, 1, 3), feeds=["MID"], raw_dir=raw_dir
    )
    assert summary.loc["MID", "days_present"] == 1
    assert summary.loc["MID", "days_missing"] == 1
    assert summary.loc["MID", "pct_present"] == pytest.approx(50.0)


def test_backfill_requests_only_missing_days():
    asked = []
    with (
        mock.patch.object(
            backfill.cov, "missing_days", return_value=[dt.date(2024, 1, 2)]
        ),
        mock.patch.dict(backfill.DAY_FETCHERS, {"MID": asked.append}),
    ):
        result = backfill.backfill_feed("MID", dt.date(2024, 1, 1), dt.date(2024, 1, 3))
    assert asked == [dt.date(2024, 1, 2)]
    assert result["failures"] == []


def test_a_failing_day_is_recorded_not_fatal():
    """A feed publishing late must not cost the other thousand days."""
    days = [dt.date(2024, 1, 1), dt.date(2024, 1, 2), dt.date(2024, 1, 3)]
    seen = []

    def flaky(day):
        seen.append(day)
        if day == dt.date(2024, 1, 2):
            raise RuntimeError("not published yet")

    with (
        mock.patch.object(backfill.cov, "missing_days", return_value=days),
        mock.patch.dict(backfill.DAY_FETCHERS, {"MID": flaky}),
    ):
        result = backfill.backfill_feed("MID", days[0], days[-1])

    assert seen == days, "the run continued past the failure"
    assert len(result["failures"]) == 1
    assert "2024-01-02" in result["failures"][0]


def test_complete_feed_does_no_work():
    with (
        mock.patch.object(backfill.cov, "missing_days", return_value=[]),
        mock.patch.dict(backfill.DAY_FETCHERS, {"MID": mock.Mock(side_effect=AssertionError)}),
    ):
        result = backfill.backfill_feed("MID", dt.date(2024, 1, 1), dt.date(2024, 1, 3))
    assert result["requested"] == 0


def test_nordpool_is_not_offered_for_backfill():
    """Its portal serves ~65 rolling days, so asking would log a thousand failures."""
    assert "NORDPOOL_DA" not in backfill.DEFAULT_FEEDS
    assert "NORDPOOL_DA" in cov.FEEDS
