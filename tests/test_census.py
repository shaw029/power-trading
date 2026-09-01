"""Tests for the battery census and its coverage arithmetic.

Every network source is mocked, so these tests are about the *classification
logic* rather than about the registers themselves. The behaviours that matter:
the identifying rule must recover known batteries and reject the generators
that superficially resemble them, the persistent asset ID must survive the
changes it exists to survive, and the coverage arithmetic must not quietly
extrapolate over sites whose energy capacity is unknown.
"""

from unittest import mock

import pandas as pd
import pytest

from fleet.research import census, coverage


def _bmu(elexon, ng, name, party, demand, generation, fuel=None, unit_type="T", gsp=None):
    return {
        "elexonBmUnit": elexon,
        "nationalGridBmUnit": ng,
        "bmUnitName": name,
        "leadPartyName": party,
        "demandCapacity": demand,
        "generationCapacity": generation,
        "fuelType": fuel,
        "bmUnitType": unit_type,
        "interconnectorId": None,
        "gspGroupName": gsp,
    }


#: A deliberately adversarial population: two symmetric batteries, a
#: co-located solar farm with a token site load, a CHP, a wind BMU and an
#: interconnector — every shape the rule has to tell apart.
_REFERENCE = [
    _bmu("T_TESTB-1", "TESTB-1", "Testville BESS", "Test Storage Ltd", -50.0, 50.0),
    _bmu("T_TESTB-2", "TESTB-2", "Testville BESS", "Test Storage Ltd", -50.0, 50.0),
    _bmu("E_SMALB-1", "SMALB-1", "Smalltown BESS", "Small Storage Ltd", -10.0, 10.0, unit_type="E"),
    _bmu("T_SOLAR-1", "SOLAR-1", "Sunny Solar 1", "Solar Ltd", -2.0, 205.0),
    _bmu("E_CHP-1", "CHP-1", "Someplace Cogeneration", "CHP Ltd", -3.0, 218.0, unit_type="E"),
    _bmu("T_WIND-1", "WIND-1", "Windy Farm", "Wind Ltd", -51.0, 225.0, fuel="WIND"),
    _bmu("T_PUMP-1", "PUMP-1", "Pumped Storage", "Hydro Ltd", -288.0, 288.0, fuel="PS"),
]

_CM = pd.DataFrame(
    [
        {
            "cm_unit_name": "TESTB1",
            "registered_holder": "Test Storage Ltd",
            "cm_power_mw": 100.0,
            "cm_derated_mw": 25.0,
            "duration_h": 2.0,
            "cm_capacity_mwh": 200.0,
            "connection_level": "Transmission",
            "delivery_year": 2026.0,
        }
    ]
)

_EMPTY_CONNECTION = pd.DataFrame(
    columns=["project_name", "customer_name", "connected_mw", "project_status", "plant_type"]
)
_EMPTY_EAC = pd.DataFrame(columns=["participant", "auction_unit"])


@pytest.fixture
def patched_sources():
    """Point every census fetcher at the fixture population above."""
    with (
        mock.patch.object(census, "fetch_bmu_reference", return_value=_frame()),
        mock.patch.object(census, "fetch_cm_storage", return_value=_CM),
        mock.patch.object(census, "fetch_tec_storage", return_value=_EMPTY_CONNECTION),
        mock.patch.object(census, "fetch_embedded_storage", return_value=_EMPTY_CONNECTION),
        mock.patch.object(census, "fetch_eac_battery_participants", return_value=_EMPTY_EAC),
        mock.patch.object(census, "bmu_to_site", return_value={}),
    ):
        yield


def _frame():
    frame = pd.DataFrame(_REFERENCE)
    for col in ("demandCapacity", "generationCapacity"):
        frame[col] = pd.to_numeric(frame[col])
    return frame


def test_symmetric_units_are_batteries(patched_sources):
    units = census.battery_bmus()
    batteries = set(units.loc[units["is_battery"], "elexonBmUnit"])
    assert batteries == {"T_TESTB-1", "T_TESTB-2", "E_SMALB-1"}


def test_asymmetric_generators_are_rejected(patched_sources):
    """A solar farm or CHP with a small site load is bidirectional, not a battery."""
    units = census.battery_bmus().set_index("elexonBmUnit")
    assert not units.loc["T_SOLAR-1", "is_battery"]
    assert not units.loc["E_CHP-1", "is_battery"]


def test_labelled_fuel_types_are_rejected(patched_sources):
    """Wind and pumped storage carry a fuel label, so they can never qualify."""
    units = census.battery_bmus().set_index("elexonBmUnit")
    assert not units.loc["T_WIND-1", "is_battery"]
    assert not units.loc["T_PUMP-1", "is_battery"]


def test_curated_membership_does_not_admit_a_unit(patched_sources):
    """The population is the rule's, not a list's.

    The curated list used to be OR'd into ``is_battery``, which let a name on a
    hand-written list stand in for evidence. It no longer does: a unit whose
    declared capability fails the symmetry test stays out however it is
    labelled. ``E_CHP-1`` is asymmetric in the fixture, and being named as a
    curated BM Unit must not rescue it.
    """
    with mock.patch.object(census, "bmu_to_site", return_value={"E_CHP-1": object()}):
        units = census.battery_bmus().set_index("elexonBmUnit")
    assert not units.loc["E_CHP-1", "is_battery"]


def test_the_rule_recovers_every_curated_bm_unit_unaided():
    """The claim notebook 06 prints, held as a test.

    Dropping the curated shortcut from the classifier is only safe while the
    signature finds those units by itself. If a curated BM Unit ever stops
    passing the rule, the census silently loses it — so the agreement between
    the two routes is asserted here rather than left to be noticed.
    """
    from fleet import curated

    units = census.battery_bmus().set_index("elexonBmUnit")
    listed = [b for b in curated.bmu_to_site() if b in units.index]
    assert listed, "no curated BM Unit present in the reference data"
    missed = [b for b in listed if not units.loc[b, "is_battery"]]
    assert not missed, f"the rule no longer recovers curated units: {missed}"


def test_multi_unit_site_collapses_to_one_asset(patched_sources):
    sites = census.census_sites().set_index("asset_id")
    assert sites.loc["GB-BESS-TESTB", "n_bmus"] == 2
    assert sites.loc["GB-BESS-TESTB", "declared_export_mw"] == pytest.approx(100.0)


def test_asset_id_is_stable_across_unit_and_prefix_changes():
    """The whole point of the persistent ID: same site, different registration."""
    assert census.asset_id("COALB-1") == census.asset_id("COALB-5")
    assert census.asset_id("COALB-1", "T_COALB-1") == census.asset_id(None, "E_COALB-3")


def test_asset_id_alias_stitches_a_re_registration():
    with mock.patch.dict(census.ASSET_ID_ALIASES, {"OLDRT": "NEWRT"}, clear=False):
        assert census.asset_id("OLDRT-1") == census.asset_id("NEWRT-2")


def test_normalise_name_drops_boilerplate_but_keeps_identity():
    assert census.normalise_name("Coalburn Battery Energy Storage Facility") == frozenset(
        {"COALBURN"}
    )
    assert census.normalise_name("Coalburn 1") == frozenset({"COALBURN"})


def test_pumped_storage_durations_are_excluded_from_cm_storage():
    """Dinorwig shares the CM's ``Storage`` family with 2-hour lithium sites."""
    raw = [
        {
            "CMU Technology": "Storage (Duration 2h)",
            "Connection / DSR Capacity": "100",
            "De-Rated Capacity": "25",
            "Delivery Year": "2026",
            "CM Unit Name": "A",
            "Registered Holder": None,
            "Parent Company": None,
            "Transmission / Distribution": "Transmission",
            "Capacity Agreement Awarded": "Yes",
        },
        {
            "CMU Technology": "Storage (Duration 12h)",
            "Connection / DSR Capacity": "1800",
            "De-Rated Capacity": "1700",
            "Delivery Year": "2026",
            "CM Unit Name": "B",
            "Registered Holder": None,
            "Parent Company": None,
            "Transmission / Distribution": "Transmission",
            "Capacity Agreement Awarded": "Yes",
        },
    ]
    with mock.patch.object(census, "_cached", return_value=raw):
        storage = census.fetch_cm_storage()
    assert list(storage["cm_unit_name"]) == ["A"]
    assert storage["cm_capacity_mwh"].iloc[0] == pytest.approx(200.0)


def test_coverage_reports_unknown_mwh_rather_than_extrapolating(patched_sources):
    """MWh coverage must be stated over known sites only, never inferred."""
    table = coverage.coverage_table()
    table["in_registry"] = table["asset_id"] == "GB-BESS-TESTB"
    table["registry_capacity_mwh"] = float("nan")
    table["capacity_mwh"] = [
        200.0 if a == "GB-BESS-TESTB" else float("nan") for a in table["asset_id"]
    ]

    stats = coverage.representativeness(table)
    assert stats.loc["MWh (where known)", "census"] == pytest.approx(200.0)
    assert stats.loc["MWh (where known)", "coverage_pct"] == pytest.approx(100.0)
    # The unknown-MWh sites are still counted in the MW and site rows.
    assert stats.loc["sites", "census"] == len(table)


def test_missing_reason_separates_scope_from_omission(patched_sources):
    table = coverage.coverage_table()
    table = table.set_index("asset_id")
    assert table.loc["GB-BESS-SMALB", "missing_reason"] == "below size floor"
    assert table.loc["GB-BESS-TESTB", "missing_reason"] == "not curated"


def test_capacity_market_match_is_rejected_when_power_disagrees(patched_sources):
    """A name collision must not put a fabricated denominator under a site.

    "The Drove" (a 6 MW BM Unit) token-matches the Capacity Market's
    "GR - Hightown Drove" (90 MW / 360 MWh). Believed, that implies a 60-hour
    battery and corrupts every duration and cycles figure the site appears in.
    An unmatched site is far less damaging than a wrong one.
    """
    sites = pd.DataFrame(
        {
            "asset_id": ["GB-BESS-TDRVE", "GB-BESS-GOODB"],
            "site_name": ["The Drove", "Goodmatch BESS"],
            "declared_export_mw": [6.0, 50.0],
            "registry_capacity_mwh": [float("nan"), float("nan")],
        }
    )
    cm = pd.DataFrame(
        [
            {
                "cm_unit_name": "Hightown Drove",
                "cm_power_mw": 90.0,
                "duration_h": 4.0,
                "cm_capacity_mwh": 360.0,
                "registered_holder": None,
                "connection_level": "Distribution",
                "delivery_year": 2026.0,
            },
            {
                "cm_unit_name": "Goodmatch",
                "cm_power_mw": 49.0,
                "duration_h": 2.0,
                "cm_capacity_mwh": 98.0,
                "registered_holder": None,
                "connection_level": "Transmission",
                "delivery_year": 2026.0,
            },
        ]
    )
    enriched = coverage.enrich_with_capacity_market(sites, cm).set_index("asset_id")

    assert pd.isna(enriched.loc["GB-BESS-TDRVE", "capacity_mwh"]), "15x mismatch believed"
    assert enriched.loc["GB-BESS-GOODB", "capacity_mwh"] == pytest.approx(98.0)


def test_no_census_site_implies_an_impossible_duration(patched_sources):
    """The guard's purpose, stated as the invariant it protects."""
    sites = pd.DataFrame(
        {
            "asset_id": ["GB-BESS-AAAA"],
            "site_name": ["A"],
            "declared_export_mw": [10.0],
            "registry_capacity_mwh": [float("nan")],
        }
    )
    cm = pd.DataFrame(
        [
            {
                "cm_unit_name": "A",
                "cm_power_mw": 10.0,
                "duration_h": 40.0,
                "cm_capacity_mwh": 400.0,
                "registered_holder": None,
                "connection_level": "Transmission",
                "delivery_year": 2026.0,
            }
        ]
    )
    enriched = coverage.enrich_with_capacity_market(sites, cm)
    assert pd.isna(enriched["capacity_mwh"].iloc[0])


def test_unknown_duration_is_labelled_not_crashed():
    """Half the census has no published energy capacity; that must stay usable."""
    from fleet.performance import UNKNOWN_DURATION, duration_label

    assert duration_label(50.0, 100.0) == "2h"
    assert duration_label(50.0, float("nan")) == UNKNOWN_DURATION
    assert duration_label(50.0, 0.0) == UNKNOWN_DURATION


def _worksheet(tmp_path, **overrides):
    row = {
        "asset_id": "GB-BESS-AAAA",
        "site_name": "A BESS",
        "declared_export_mw": 50.0,
        "capacity_mwh": 110.0,
        "duration_h": 2.2,
        "source_type": "operator",
        "source_url": "https://operator.example/projects/a",
        "read_on": "2026-08-23",
        "notes": None,
    }
    row.update(overrides)
    path = tmp_path / "sheet.xlsx"
    pd.DataFrame([row]).to_excel(path, index=False)
    return path


def test_worksheet_value_carries_its_provenance(tmp_path):
    """A figure read off an operator's page must not look like a settled one."""
    sites = pd.DataFrame(
        {
            "asset_id": ["GB-BESS-AAAA"],
            "capacity_mwh": [float("nan")],
            "mwh_source": [None],
            "declared_export_mw": [50.0],
        }
    )
    out = coverage.apply_energy_worksheet(sites, _worksheet(tmp_path))
    assert out["capacity_mwh"].iloc[0] == pytest.approx(110.0)
    assert out["mwh_source"].iloc[0] == "operator"
    assert out["mwh_source_url"].iloc[0].startswith("https://")


def test_worksheet_does_not_override_the_hand_verified_registry(tmp_path):
    sites = pd.DataFrame(
        {
            "asset_id": ["GB-BESS-AAAA"],
            "capacity_mwh": [200.0],
            "mwh_source": ["registry"],
            "declared_export_mw": [50.0],
        }
    )
    out = coverage.apply_energy_worksheet(sites, _worksheet(tmp_path))
    assert out["capacity_mwh"].iloc[0] == pytest.approx(200.0)
    assert out["mwh_source"].iloc[0] == "registry"


def test_worksheet_row_without_a_citation_is_rejected(tmp_path):
    """The citation is the point: an uncited figure is not evidence."""
    assert coverage.load_energy_worksheet(_worksheet(tmp_path, source_url=None)).empty
    assert coverage.load_energy_worksheet(_worksheet(tmp_path, source_type="hearsay")).empty


def test_worksheet_row_implying_an_impossible_duration_is_rejected(tmp_path):
    """50 MW with 600 MWh is a 12-hour battery — a typo, not a discovery."""
    assert coverage.load_energy_worksheet(_worksheet(tmp_path, capacity_mwh=600.0)).empty


def test_absent_worksheet_is_not_an_error(tmp_path):
    """The sheet adds sites that can be priced; it is never load-bearing."""
    assert coverage.load_energy_worksheet(tmp_path / "nope.xlsx").empty


def test_worksheet_rejects_a_project_figure_on_a_bm_unit_row(tmp_path):
    """The operator's project boundary is not the BM Unit boundary.

    Wolverhampton West publishes 310 MWh at 2.4 hours — a 129 MW project —
    against a 56 MW BM Unit. Declared MW and published MWh come from
    independent places, so their agreement is corroboration and their
    disagreement means one of them is describing a different asset.
    """
    rejected = coverage.load_energy_worksheet(
        _worksheet(tmp_path, declared_export_mw=56.0, capacity_mwh=310.0, duration_h=2.4)
    )
    assert rejected.empty


def test_worksheet_accepts_agreement_between_independent_sources(tmp_path):
    """57 MW declared with 138 MWh published implies 2.42 h against 2.4 recorded."""
    accepted = coverage.load_energy_worksheet(
        _worksheet(tmp_path, declared_export_mw=57.0, capacity_mwh=138.0, duration_h=2.4)
    )
    assert len(accepted) == 1


def test_a_self_consistent_figure_is_flagged_when_the_duration_is_unlike_the_fleet(tmp_path):
    """The agreement check goes circular if the duration is derived from the MWh.

    Wolverhampton West was recorded first at 2.4 h against 310 MWh (rejected as
    disagreeing) and then at 5.5 h (agreeing, because 310/56 is 5.5). The same
    figure underneath, now unfalsifiable by comparison — so a second check asks
    whether GB batteries have this duration at all, and flags rather than
    rejects, since longer batteries do exist.
    """
    sheet = coverage.load_energy_worksheet(
        _worksheet(tmp_path, declared_export_mw=56.0, capacity_mwh=310.0, duration_h=5.5)
    )
    assert len(sheet) == 1, "a plausible-looking outlier still loads"
    assert bool(sheet["mwh_needs_review"].iloc[0]) is True


def test_an_ordinary_duration_is_not_flagged(tmp_path):
    sheet = coverage.load_energy_worksheet(
        _worksheet(tmp_path, declared_export_mw=57.0, capacity_mwh=138.0, duration_h=2.4)
    )
    assert bool(sheet["mwh_needs_review"].iloc[0]) is False
