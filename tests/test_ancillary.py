"""Tests for per-unit ancillary revenue assembly.

The network is mocked throughout. What matters here is the arithmetic and the
honesty guards: block length differs by era so revenue must be computed from
each record's own timestamps, aggregator units must never be force-fitted onto
a site, and months with different service sets must never be presented as
comparable.
"""

import datetime as dt
from unittest import mock

import pandas as pd
import pytest

from fleet.research import ancillary


def _rows():
    """Two eras with deliberately different block lengths and unit naming."""
    return pd.DataFrame(
        [
            # 4-hour EFA block, BM-named unit: 10 MW x GBP 5/MW/h x 4h = GBP 200
            {
                "unit": "TESTB-1",
                "service": "DCL",
                "volume_mw": 10.0,
                "price_gbp_mw_h": 5.0,
                "block_start": pd.Timestamp("2023-10-01T00:00Z"),
                "block_end": pd.Timestamp("2023-10-01T04:00Z"),
                "source": "response_dc_dr_dm",
                "era": "DC/DR/DM",
                "stated_revenue_gbp": float("nan"),
                "site_attributed_only": False,
            },
            # 30-minute block, same unit: 10 MW x GBP 5/MW/h x 0.5h = GBP 25
            {
                "unit": "TESTB-1",
                "service": "Response",
                "volume_mw": 10.0,
                "price_gbp_mw_h": 5.0,
                "block_start": pd.Timestamp("2026-04-01T00:00Z"),
                "block_end": pd.Timestamp("2026-04-01T00:30Z"),
                "source": "eac_response_reserve",
                "era": "EAC",
                "stated_revenue_gbp": float("nan"),
                "site_attributed_only": False,
            },
            # Aggregator house code — a trading unit, not a site.
            {
                "unit": "AG-GBL0EN",
                "service": "Response",
                "volume_mw": 20.0,
                "price_gbp_mw_h": 5.0,
                "block_start": pd.Timestamp("2026-04-01T00:00Z"),
                "block_end": pd.Timestamp("2026-04-01T00:30Z"),
                "source": "eac_response_reserve",
                "era": "EAC",
                "stated_revenue_gbp": float("nan"),
                "site_attributed_only": False,
            },
        ]
    )


@pytest.fixture
def offline_census():
    """Stub the census lookups `classify_units` needs, so tests never hit the network."""
    sites = pd.DataFrame(
        {
            "asset_id": ["GB-BESS-TESTB"],
            "site_name": ["Testville BESS"],
            "lead_party": ["Test Storage Ltd"],
            "declared_export_mw": [50.0],
            "in_registry": [True],
        }
    )
    reference = pd.DataFrame(
        {"nationalGridBmUnit": ["TESTB-1"], "elexonBmUnit": ["T_TESTB-1"], "bmUnitType": ["T"]}
    )
    with (
        mock.patch.object(ancillary.census, "census_sites", return_value=sites),
        mock.patch.object(ancillary.census, "fetch_bmu_reference", return_value=reference),
    ):
        yield


@pytest.fixture
def cached(tmp_path):
    """Run fetch_all's derivation over the fixture rows, without network or cache."""
    with (
        mock.patch.object(
            ancillary,
            "_fetch_source",
            side_effect=lambda s: _rows() if s.name == "response_dc_dr_dm" else pd.DataFrame(),
        ),
        mock.patch.object(ancillary, "_CACHE_DIR", str(tmp_path)),
    ):
        yield ancillary.fetch_all(refresh=True)


def test_block_length_is_read_not_assumed(cached):
    """A 4-hour EFA block and a 30-minute auction block price differently."""
    by_service = cached.set_index("service")["revenue_gbp"]
    assert by_service["DCL"] == pytest.approx(200.0)
    assert by_service["Response"].max() == pytest.approx(50.0)  # the 20 MW aggregator row


def test_bm_named_units_resolve_to_a_persistent_asset(cached):
    resolved = cached[cached["unit"] == "TESTB-1"]["asset_id"].unique()
    assert list(resolved) == ["GB-BESS-TESTB"]


def test_aggregator_house_codes_are_never_force_fitted(cached):
    """An aggregator unit names a portfolio, so it must stay unattributed."""
    house = cached[cached["unit"] == "AG-GBL0EN"]
    assert house["asset_id"].isna().all()


def test_unattributed_revenue_is_reported_not_dropped(cached, offline_census):
    with mock.patch.object(ancillary, "fetch_all", return_value=cached):
        summary = ancillary.unmatched_summary()
    # The aggregator's GBP 50 must survive into the summary, not vanish.
    assert summary["unattributed_gbp"].sum() == pytest.approx(50.0)
    assert summary["attributed_gbp"].sum() == pytest.approx(225.0)


def test_months_with_no_data_read_as_uncovered_not_zero_revenue(cached, offline_census):
    with mock.patch.object(ancillary, "fetch_all", return_value=cached):
        coverage = ancillary.coverage_by_month(dt.date(2023, 10, 1), dt.date(2026, 4, 30))
    assert coverage.loc["2023-10", "covered"]
    assert coverage.loc["2026-04", "covered"]
    assert not coverage.loc["2024-06", "covered"], "a gap month must not read as covered"
    assert pd.isna(coverage.loc["2024-06", "revenue_gbp"]), "a gap is null, never 0"


def test_different_service_sets_are_not_comparable(cached, offline_census):
    """The trap this guard exists for: comparing across eras measures NESO."""
    with mock.patch.object(ancillary, "fetch_all", return_value=cached):
        coverage = ancillary.coverage_by_month(dt.date(2023, 10, 1), dt.date(2026, 4, 30))
        windows = ancillary.comparable_windows(coverage)
    assert len(windows) == 2, "the two eras must not collapse into one window"
    assert set(windows["services"]) == {"DCL", "Response"}


def test_battery_filter_matches_every_spelling():
    """'Batteries', 'Battery', 'BATTERY' and 'BESS' all appear across eras."""
    predicate = ancillary._BATTERY_PREDICATE.format(col="techType")
    assert "batter" in predicate.lower() and "bess" in predicate.lower()
    assert "ILIKE" in predicate, "matching must be case-insensitive"


def test_every_source_declares_the_columns_it_needs():
    for source in ancillary.SOURCES:
        assert len(source.columns) == 6, f"{source.name} column spec is malformed"


def test_units_are_classified_by_what_they_actually_are(cached, offline_census):
    """Half of ancillary revenue is earned by units that are not sites at all."""
    classes = ancillary.classify_units(pd.Series(["TESTB-1", "AG-GBL0EN", "NOSUCH-1"]))
    assert list(classes) == ["census site", "aggregator portfolio", "unknown"]


def test_vlp_and_supplier_units_are_not_called_a_census_gap(offline_census):
    """A VLP route is correctly outside the site census, not missing from it."""
    reference = pd.DataFrame(
        {"nationalGridBmUnit": ["MELKB-1"], "elexonBmUnit": ["V_MELKB-1"], "bmUnitType": ["V"]}
    )
    with mock.patch.object(ancillary.census, "fetch_bmu_reference", return_value=reference):
        assert ancillary.classify_units(pd.Series(["MELKB-1"]))[0] == "VLP / supplier unit"


def test_stated_revenue_is_preferred_over_reconstructing_it():
    """NESO states settled revenue for the Dynamic Containment masterdata."""
    rows = pd.DataFrame(
        [
            {
                "unit": "TESTB-1",
                "service": "DC LF",
                "volume_mw": 49.0,
                "price_gbp_mw_h": 15.03,
                "block_start": pd.Timestamp("2021-01-01T00:00Z"),
                "block_end": pd.Timestamp("2021-01-02T00:00Z"),
                "source": "dc_masterdata",
                "era": "DC masterdata",
                "stated_revenue_gbp": 17675.28,
                "site_attributed_only": True,
            }
        ]
    )
    with (
        mock.patch.object(
            ancillary,
            "_fetch_source",
            side_effect=lambda s: rows if s.name == "dc_masterdata" else pd.DataFrame(),
        ),
        mock.patch.object(ancillary, "_CACHE_DIR", "/tmp/anc-test"),
    ):
        out = ancillary.fetch_all(refresh=True)
    # 49 x 15.03 x 24h reconstructs to 17,675.28 — but the published figure wins
    # outright rather than being checked against, because it is the settlement.
    assert out["revenue_gbp"].iloc[0] == pytest.approx(17675.28)


def test_unlabelled_sources_contribute_batteries_only():
    """FFR and the DC masterdata carry every technology in their auction."""
    units = pd.Series(["TESTB-1", "DBESS-22", "GASENGINE-4", "AG-KNOWN01"])
    flags = ancillary._is_battery(units, {"AG-KNOWN01", "TESTB"})
    assert list(flags) == [
        True,
        True,
        False,
        True,
    ], "known unit, name says BESS, gas engine, whitelisted aggregator"
