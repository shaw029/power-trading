"""Which batteries an analysis is about.

Every fleet function in this package needs two things from its population: the
list of BM Units to fetch, and the map from BM Unit to the site it belongs to.
Both were previously read straight from :mod:`fleet.registry`, which welded the
whole fleet layer to the curated 23 sites — so the research notebooks were
computing fleet-level results on a sample without any way to ask for more.

A :class:`Population` supplies that pair, and every fetcher and metric takes one
as an argument. Two exist:

``REGISTRY``
    The curated 23 sites / 47 BM Units, hand-verified, with real optimiser,
    region and MWh metadata. The **default everywhere**, so the live dashboard's
    behaviour is unchanged by construction — it never passes a population and
    therefore always gets this one.

``census_population()``
    Every BM-registered battery :mod:`fleet.census` can identify — 90 sites /
    127 BM Units. The research tier's population. Its metadata is machine-derived
    rather than hand-checked, which matters for some metrics and not others; see
    the note on that function.

**Caching is keyed by population, not merged.** A day-file holds exactly the BM
Units it was fetched for, so a census fetch writes to ``FLEET_PN_CENSUS/`` while
the curated fetch keeps ``FLEET_PN/`` untouched. Merging them would silently make
the dashboard parse three times the records it needs, which is the opposite of
what the two-tier split is for.

This module deliberately does **not** import :mod:`fleet.census` at module
level. ``fetch_fleet`` and ``performance`` import this module, and the dashboard
imports those; a top-level census import would drag the entire research tier
into a Streamlit process. The import is therefore made inside
:func:`census_population`, and ``tests/test_profile_boundary.py`` enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass

from fleet.registry import FLEET, FleetSite


@dataclass(frozen=True)
class Population:
    """A set of battery sites, and how its cached data is named."""

    name: str
    sites: tuple[FleetSite, ...]
    #: Appended to every raw-cache directory. Empty for the curated registry so
    #: its existing caches keep working untouched.
    cache_suffix: str = ""

    def bmu_ids(self) -> tuple[str, ...]:
        """Every BM Unit in the population, in site order."""
        return tuple(bmu for site in self.sites for bmu in site.bmu_ids)

    def bmu_to_site(self) -> dict[str, FleetSite]:
        """Map each BM Unit to the site it belongs to."""
        return {bmu: site for site in self.sites for bmu in site.bmu_ids}

    def __len__(self) -> int:
        return len(self.sites)


#: The curated cross-section. Default for every fleet function.
REGISTRY = Population(name="registry", sites=FLEET, cache_suffix="")


def census_population(refresh: bool = False) -> Population:
    """Every BM-registered battery the census can identify.

    **Metadata is machine-derived for the sites the registry does not cover**,
    and the difference is not uniform across metrics:

    * ``power_mw`` comes from Elexon's declared export capability, so anything
      normalised by MW — £/MW/day, MW per MW online, availability factor — is
      as sound for a census site as for a curated one.
    * ``capacity_mwh`` is only known where a Capacity Market agreement could be
      matched, so it is ``nan`` for most non-registry sites. Any metric dividing
      by energy capacity — cycles per day above all — is undefined for those and
      must be reported over the known-MWh subset rather than fleet-wide.
    * ``optimiser`` falls back to the BM Unit's lead party, which is the trading
      party rather than the optimiser proper, and ``region`` to the GSP group,
      which is null for transmission-connected units.

    The census is imported here rather than at module scope so that importing
    this module stays cheap for the dashboard.
    """
    from fleet import coverage  # noqa: PLC0415 - deliberately lazy

    table = coverage.coverage_table(refresh)

    sites = []
    for row in table.itertuples():
        sites.append(
            FleetSite(
                site=row.registry_site or row.site_name or row.asset_id,
                bmu_ids=tuple(row.bmu_ids),
                power_mw=float(row.declared_export_mw),
                capacity_mwh=float(row.capacity_mwh),
                optimiser=row.registry_optimiser or row.lead_party or "unknown",
                region=row.registry_region or row.gsp_group or "unknown",
            )
        )

    return Population(
        name="census", sites=tuple(sites), cache_suffix="_CENSUS"
    )
