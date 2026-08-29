"""Tests for the population abstraction that lets one code path serve two tiers.

The behaviours that matter are all about *not* breaking the presentation tier
while opening the research tier up: the curated registry must stay the default
everywhere, its cache paths must not move, the census must not be reachable at
import time, and the two populations' day-files must never be confused for each
other.
"""

import ast
import datetime as dt
from pathlib import Path
from unittest import mock

import pytest

from fleet import fetch_fleet, performance
from fleet.population import Population
from fleet.curated import CURATED, CURATED_SITES
from fleet.population import FleetSite

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_curated_is_the_default_population():
    assert CURATED.sites is CURATED_SITES
    assert len(CURATED.bmu_ids()) == 47


def test_curated_cache_paths_are_unchanged():
    """The dashboard reads these directories; moving them would orphan its cache."""
    assert fetch_fleet._dir_for("FLEET_PN", CURATED) == "FLEET_PN"
    assert fetch_fleet._dir_for("FLEET_EBOCF", CURATED) == "FLEET_EBOCF"


def test_populations_cache_into_separate_directories():
    """A day-file holds only the BM Units it was fetched for, so it cannot be shared."""
    census = Population("census", CURATED_SITES, cache_suffix="_CENSUS")
    assert fetch_fleet._dir_for("FLEET_PN", census) == "FLEET_PN_CENSUS"
    assert fetch_fleet._dir_for("FLEET_PN", census) != fetch_fleet._dir_for(
        "FLEET_PN", CURATED
    )


def test_census_is_not_imported_at_module_scope():
    """`population` is imported by the dashboard's dependency chain.

    A top-level `fleet.census` import here would pull the whole research tier —
    registers, the full BMU reference, the coverage join — into a Streamlit
    process. The import must stay inside `census_population`.
    """
    tree = ast.parse((REPO_ROOT / "fleet" / "population.py").read_text(encoding="utf-8"))
    top_level = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    top_level |= {
        alias.name for node in tree.body if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not {"fleet.census", "fleet.coverage"} & top_level


def test_fetchers_request_the_populations_own_units():
    """The BMU list sent to Elexon must follow the population, not the registry."""
    two = Population(
        "two",
        (FleetSite("A", ("T_AAAA-1",), 50.0, 100.0, "opt", "region"),),
        cache_suffix="_TEST",
    )
    captured = {}

    def fake_get(url, params=None):
        captured["params"] = params
        return []

    with (
        mock.patch.object(fetch_fleet, "_get_json", side_effect=fake_get),
        mock.patch.object(fetch_fleet, "_read_cache", return_value=None),
    ):
        fetch_fleet.fetch_fleet_pn(dt.date(2024, 6, 1), two)

    requested = [v for k, v in captured["params"] if k == "bmUnit"]
    assert requested == ["T_AAAA-1"]


def test_metrics_map_units_through_the_given_population():
    sites = (FleetSite("Somewhere", ("T_XXXX-1",), 50.0, 100.0, "opt", "region"),)
    population = Population("custom", sites)
    records = [
        {
            "bmUnit": "T_XXXX-1",
            "timeFrom": "2024-06-01T00:00:00Z",
            "timeTo": "2024-06-01T00:30:00Z",
            "levelFrom": 50,
            "levelTo": 50,
        }
    ]
    profile = performance.site_profile(records, population)
    assert list(profile["site"].unique()) == ["Somewhere"]

    # The same records under the default population resolve to nothing, because
    # that BM Unit is not in the curated registry.
    assert performance.site_profile(records).empty


def test_census_population_carries_machine_derived_metadata():
    """MWh is unknown for most census sites and must arrive as nan, not zero."""
    table = mock.MagicMock()
    rows = [
        mock.Mock(
            asset_id="GB-BESS-AAAA", bmu_ids=("T_AAAA-1",), site_name="A BESS",
            registry_site=None, declared_export_mw=50.0, capacity_mwh=float("nan"),
            registry_optimiser=None, lead_party="Some Ltd",
            registry_region=None, gsp_group=None,
        )
    ]
    table.itertuples.return_value = rows
    with mock.patch("fleet.coverage.coverage_table", return_value=table):
        from fleet.population import census_population

        population = census_population()

    site = population.sites[0]
    assert site.site == "A BESS"
    assert site.power_mw == pytest.approx(50.0)
    assert site.capacity_mwh != site.capacity_mwh, "unknown MWh must be nan"
    assert site.optimiser == "Some Ltd"
    assert site.region == "unknown"
    assert population.cache_suffix == "_CENSUS"
