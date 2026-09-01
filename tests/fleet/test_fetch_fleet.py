"""Tests for the fleet fetchers — HTTP is mocked, caching uses tmp_path."""

import datetime as dt
import json
import os
from unittest import mock

from fleet import fetch_fleet

_DAY = dt.date(2024, 1, 1)


def _pn_payload() -> list[dict]:
    """Stream records spanning the padded window — one belongs to the prior day."""
    return [
        {"bmUnit": "E_PILLB-1", "settlementDate": "2024-01-01", "levelFrom": 10, "levelTo": 10},
        {"bmUnit": "E_PILLB-1", "settlementDate": "2023-12-31", "levelFrom": 5, "levelTo": 5},
    ]


def test_fetch_fleet_pn_filters_to_settlement_date_and_caches(tmp_path):
    with (
        mock.patch.object(fetch_fleet, "RAW_DATA_DIR", str(tmp_path)),
        mock.patch.object(fetch_fleet, "_get_json", return_value=_pn_payload()) as get,
    ):
        records = fetch_fleet.fetch_fleet_pn(_DAY)

    assert [r["settlementDate"] for r in records] == ["2024-01-01"]
    url, params = get.call_args.args
    assert url.endswith("/datasets/PN/stream")
    # Padded UTC window so the BST-shifted settlement day is fully covered.
    assert ("from", "2023-12-31T22:00Z") in params
    assert ("to", "2024-01-02T02:00Z") in params
    assert ("bmUnit", "E_PILLB-1") in params

    cache = tmp_path / "FLEET_PN" / "FLEET_PN_2024-01-01.json"
    assert json.loads(cache.read_text()) == records


def test_fetch_fleet_pn_reads_cache_without_hitting_network(tmp_path):
    cache_dir = tmp_path / "FLEET_PN"
    os.makedirs(cache_dir)
    (cache_dir / "FLEET_PN_2024-01-01.json").write_text(json.dumps([{"bmUnit": "X"}]))

    with (
        mock.patch.object(fetch_fleet, "RAW_DATA_DIR", str(tmp_path)),
        mock.patch.object(fetch_fleet, "_get_json") as get,
    ):
        records = fetch_fleet.fetch_fleet_pn(_DAY)

    assert records == [{"bmUnit": "X"}]
    get.assert_not_called()


def test_fetch_fleet_pn_does_not_cache_empty_days(tmp_path):
    with (
        mock.patch.object(fetch_fleet, "RAW_DATA_DIR", str(tmp_path)),
        mock.patch.object(fetch_fleet, "_get_json", return_value=[]),
    ):
        records = fetch_fleet.fetch_fleet_pn(_DAY)

    assert records == []
    assert not (tmp_path / "FLEET_PN").exists()


def test_fetch_fleet_bm_cashflows_fetches_both_directions(tmp_path):
    def _fake(url, params=None):
        direction = "bid" if "/bid/" in url else "offer"
        assert url.endswith(
            f"/balancing/settlement/indicative/cashflows/all/{direction}/2024-01-01"
        )
        return {"data": [{"bmUnit": "E_PILLB-1", "direction": direction}]}

    with (
        mock.patch.object(fetch_fleet, "RAW_DATA_DIR", str(tmp_path)),
        mock.patch.object(fetch_fleet, "_get_json", side_effect=_fake),
    ):
        payload = fetch_fleet.fetch_fleet_bm_cashflows(_DAY)

    assert payload["bid"][0]["direction"] == "bid"
    assert payload["offer"][0]["direction"] == "offer"
    cache = tmp_path / "FLEET_EBOCF" / "FLEET_EBOCF_2024-01-01.json"
    assert cache.exists()


def _mels_payload() -> list[dict]:
    return [
        {
            "bmUnit": "E_PILLB-1",
            "settlementDate": "2024-01-01",
            "timeFrom": "2024-01-01T18:00:00Z",
            "timeTo": "2024-01-01T18:24:00Z",
            "levelFrom": 49,
            "levelTo": 49,
            "notificationTime": "2024-01-01T17:53:43Z",
            "notificationSequence": 1,
        },
        {"bmUnit": "E_PILLB-1", "settlementDate": "2023-12-31", "levelFrom": 49, "levelTo": 49},
    ]


def test_fetch_fleet_mels_filters_to_settlement_date_and_caches(tmp_path):
    with (
        mock.patch.object(fetch_fleet, "RAW_DATA_DIR", str(tmp_path)),
        mock.patch.object(fetch_fleet, "_get_json", return_value=_mels_payload()) as get,
    ):
        records = fetch_fleet.fetch_fleet_mels(_DAY)

    assert [r["settlementDate"] for r in records] == ["2024-01-01"]
    url, params = get.call_args.args
    assert url.endswith("/datasets/MELS/stream")
    assert ("from", "2023-12-31T22:00Z") in params
    assert ("to", "2024-01-02T02:00Z") in params
    assert ("bmUnit", "E_PILLB-1") in params

    cache = tmp_path / "FLEET_MELS" / "FLEET_MELS_2024-01-01.json"
    assert json.loads(cache.read_text()) == records


def test_fetch_fleet_mils_uses_own_dataset_and_cache_dir(tmp_path):
    payload = [
        {"bmUnit": "E_PILLB-1", "settlementDate": "2024-01-01", "levelFrom": -11, "levelTo": -11}
    ]
    with (
        mock.patch.object(fetch_fleet, "RAW_DATA_DIR", str(tmp_path)),
        mock.patch.object(fetch_fleet, "_get_json", return_value=payload) as get,
    ):
        records = fetch_fleet.fetch_fleet_mils(_DAY)

    url, _ = get.call_args.args
    assert url.endswith("/datasets/MILS/stream")
    assert records[0]["levelFrom"] == -11
    assert (tmp_path / "FLEET_MILS" / "FLEET_MILS_2024-01-01.json").exists()
    assert not (tmp_path / "FLEET_MELS").exists()


def test_fetch_fleet_mels_does_not_cache_empty_days(tmp_path):
    with (
        mock.patch.object(fetch_fleet, "RAW_DATA_DIR", str(tmp_path)),
        mock.patch.object(fetch_fleet, "_get_json", return_value=[]),
    ):
        assert fetch_fleet.fetch_fleet_mels(_DAY) == []
    assert not (tmp_path / "FLEET_MELS").exists()


def test_fetch_fleet_mels_reads_cache_without_network(tmp_path):
    cache_dir = tmp_path / "FLEET_MELS"
    os.makedirs(cache_dir)
    (cache_dir / "FLEET_MELS_2024-01-01.json").write_text(json.dumps([{"bmUnit": "X"}]))

    with (
        mock.patch.object(fetch_fleet, "RAW_DATA_DIR", str(tmp_path)),
        mock.patch.object(fetch_fleet, "_get_json") as get,
    ):
        assert fetch_fleet.fetch_fleet_mels(_DAY) == [{"bmUnit": "X"}]
    get.assert_not_called()
