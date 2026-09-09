"""Tests for raw-feed coverage accounting and the backfill driver.

No network: coverage is a filesystem question, and the backfill's fetchers are
mocked. What matters is that coverage reads every cache naming convention the
repository actually uses, that the backfill asks only for the days it lacks,
and that a day which fails is recorded rather than aborting the run.
"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
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
        mock.patch.object(backfill.cov, "missing_days", return_value=[dt.date(2024, 1, 2)]),
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


# --------------------------------------------------------------------------- #
# Cache readers must honour the window they are asked for
# --------------------------------------------------------------------------- #


class TestCacheReadersRespectDateRange:
    """A fetcher that ignores start/end silently widens everything downstream.

    Two of them did. `fetch_imbalance_price` and the NESO demand forecast globbed
    their whole cache directory, so a request for the 2018 study window came back
    with every settlement day on disk — 2017 through 2026. The feature frame then
    spanned eight years instead of one, and the BESS pipeline, which sized its
    price fetch from that frame, asked ENTSO-E for GB day-ahead prices that stop
    existing after Brexit.
    """

    def _write_day_files(self, root, dataset, dates, payload_for):
        d = root / dataset
        d.mkdir(parents=True, exist_ok=True)
        for stamp in dates:
            (d / f"{dataset}_{stamp}_page_1.json").write_text(json.dumps(payload_for(stamp)))
        return d

    def test_b1770_reader_selects_only_the_requested_days(self, tmp_path, monkeypatch):
        from src.data import download as D

        dates = ["20171231", "20180101", "20180102", "20260824"]
        self._write_day_files(
            tmp_path,
            "B1770",
            dates,
            lambda s: {
                "data": [
                    {
                        "startTime": f"{s[:4]}-{s[4:6]}-{s[6:]}T00:00:00Z",
                        "systemBuyPrice": 50.0,
                        "systemSellPrice": 50.0,
                        "netImbalanceVolume": 0.0,
                    }
                ]
            },
        )
        monkeypatch.setattr(D, "RAW_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(D, "download_b1770", lambda *a, **k: None)

        df = D.fetch_imbalance_price(
            source="ELEXON", start_date="2018-01-01", end_date="2018-01-02"
        )
        got = set(pd.to_datetime(df["startTime"], utc=True).dt.strftime("%Y%m%d"))
        assert "20260824" not in got, "reader returned days outside the requested window"
        assert {"20180101", "20180102"} <= got

    def test_ndfd_reader_selects_only_the_requested_days(self, tmp_path, monkeypatch):
        from src.data import download as D

        def payload(stamp):
            return {
                "result": {
                    "records": [
                        {
                            "TARGETDATE": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}",
                            "CP_ST_TIME": "1700",
                            "FORECAST_TIMESTAMP": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}T08:45:00",
                            "FORECASTDEMAND": 30000,
                            "DAYSAHEAD": 1,
                        }
                    ]
                }
            }

        self._write_day_files(tmp_path, "NESO_NDFD", ["20180102", "20180103", "20260819"], payload)
        monkeypatch.setattr(D, "RAW_DATA_DIR", str(tmp_path))

        df = D.read_neso_ndfd(start_date="2018-01-02", end_date="2018-01-03")
        years = set(pd.to_datetime(df["TARGETDATE"]).dt.year)
        assert 2026 not in years, "reader returned days outside the requested window"
        assert years == {2018}

    def test_reading_without_a_window_still_returns_everything(self, tmp_path, monkeypatch):
        # The filter is opt-in: callers that pass no dates keep the old behaviour.
        from src.data import download as D

        def payload(stamp):
            return {
                "result": {
                    "records": [
                        {
                            "TARGETDATE": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}",
                            "CP_ST_TIME": "1700",
                            "FORECAST_TIMESTAMP": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}T08:45:00",
                            "FORECASTDEMAND": 30000,
                            "DAYSAHEAD": 1,
                        }
                    ]
                }
            }

        self._write_day_files(tmp_path, "NESO_NDFD", ["20180102", "20260819"], payload)
        monkeypatch.setattr(D, "RAW_DATA_DIR", str(tmp_path))
        df = D.read_neso_ndfd()
        assert set(pd.to_datetime(df["TARGETDATE"]).dt.year) == {2018, 2026}
