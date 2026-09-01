"""Which batteries an analysis is about.

Every fleet function in this package needs two things from its population: the
list of BM Units to fetch, and the map from BM Unit to the site it belongs to.
Both were previously read straight from :mod:`fleet.registry`, which welded the
whole fleet layer to the curated 23 sites — so the research notebooks were
computing fleet-level results on a sample without any way to ask for more.

A :class:`Population` supplies that pair, and every fetcher and metric takes one
as an argument. Two exist:

``fleet.registry.REGISTRY``
    **The** fleet: every BM-registered battery the census identifies whose
    energy capacity is published. Generated, not written — so it is a
    measurement. This is what the live dashboard renders.

``fleet.curated.CURATED``
    Not a rival registry. A hand-researched **metadata table** — optimiser,
    region and MWh for the sites it covers — which the generator copies into
    ``REGISTRY``. It is also the default population of every fetcher, purely so
    that a caller which says nothing keeps writing to the cache directory it
    always wrote to.

``census_population()``
    Every BM-registered battery :mod:`fleet.research.census` can identify. The research
    tier's population; its size depends on the register vintage the caller pins,
    so it is not quoted here. Its metadata is machine-derived
    rather than hand-checked, which matters for some metrics and not others; see
    the note on that function.

**Caching is keyed by population, not merged.** A day-file holds exactly the BM
Units it was fetched for, so a census fetch writes to ``FLEET_PN_CENSUS/`` while
the curated fetch keeps ``FLEET_PN/`` untouched. Merging them would silently make
the dashboard parse three times the records it needs, which is the opposite of
what the two-tier split is for.

This module deliberately does **not** import :mod:`fleet.research.census` at module
level. ``fetch_fleet`` and ``performance`` import this module, and the dashboard
imports those; a top-level census import would drag the entire research tier
into a Streamlit process. The import is therefore made inside
:func:`census_population`, and ``tests/test_profile_boundary.py`` enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FleetSite:
    """One physical battery site, possibly spanning several BM Units.

    Defined here rather than beside any one site list, because three modules
    build them — :mod:`fleet.registry` (generated), :mod:`fleet.curated`
    (hand-researched) and :func:`census_population` — and none of them owns the
    shape.
    """

    site: str
    bmu_ids: tuple[str, ...]
    power_mw: float
    capacity_mwh: float
    optimiser: str
    region: str


@dataclass(frozen=True)
class Population:
    """A set of battery sites, and how its cached data is named."""

    name: str
    sites: tuple[FleetSite, ...]
    #: Appended to every raw-cache directory, so a day-file always holds
    #: exactly the BM Units it was fetched for and two populations never merge.
    cache_suffix: str = ""

    def bmu_ids(self) -> tuple[str, ...]:
        """Every BM Unit in the population, in site order."""
        return tuple(bmu for site in self.sites for bmu in site.bmu_ids)

    def bmu_to_site(self) -> dict[str, FleetSite]:
        """Map each BM Unit to the site it belongs to."""
        return {bmu: site for site in self.sites for bmu in site.bmu_ids}

    def __len__(self) -> int:
        return len(self.sites)


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
    from fleet.research import coverage  # noqa: PLC0415 - deliberately lazy

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
