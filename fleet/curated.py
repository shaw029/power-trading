"""Curated registry of large operational GB grid-scale batteries.

The live-fleet dashboard tab tracks *real* batteries in the Balancing
Mechanism, so it needs to know which BM Units belong to which site and who
optimises them. Elexon's BMU reference data carries no battery fuel type and
no optimiser/location fields, so that mapping is hand-curated here.

Selection criteria — a site is included when all of these hold:

1. **BM-registered with its own BM Units.** This is a hard data requirement,
   not a preference: the free per-unit Elexon feeds the dashboard runs on
   (Physical Notifications, ``EBOCF`` cashflows) only exist for registered
   BM Units. Batteries traded behind an aggregator/VLP unit or a supplier
   portfolio are invisible at site level and cannot be listed.
2. **Grid-scale.** Roughly 35 MW nameplate and up (smallest included site is
   Contego at 34 MW). Below that, per-site estimates get noisy and the long
   tail of small sites adds little fleet MW.
3. **Operational.** Actively submitting PNs / being dispatched as of the
   July 2026 snapshot — not merely consented or under commissioning.
4. **Coverage over completeness.** The list is a curated cross-section of
   optimisers (Tesla, Zenobe, Habitat, EDF, Octopus, …) and regions
   (Scotland to the South East), *not* a census of GB BESS. When adding
   sites, prefer ones that broaden optimiser/region coverage.

Provenance and staleness:

* ``bmu_ids`` were verified against the live Elexon BMU reference list
  (``/reference/bmunits/all``) in July 2026 — every ID below exists and its
  registered capacity matches ``power_mw`` to within a few MW.
* ``optimiser`` is the route-to-market / trading party. For most sites it is
  simply the BMU lead party (Tesla, EDF, Limejump, Octopus, …); where the lead
  party is a project SPV the publicly known optimiser is used instead
  (e.g. Pivot Power units are optimised by Habitat Energy).
* ``capacity_mwh`` is approximate nameplate energy. Several sites do not
  publish exact figures, so derived cycle counts are indicative only.
* ``region`` is hand-assigned; transmission-connected BMUs have no GSP group
  in the reference data.

Sites commission, re-contract and change optimiser over time — refresh this
list when the fleet moves on.
"""

from fleet.population import FleetSite, Population


# Metadata snapshot: July 2026.
CURATED_SITES: tuple[FleetSite, ...] = (
    FleetSite(
        site="Coalburn 1",
        bmu_ids=("T_COALB-1", "T_COALB-2", "T_COALB-3", "T_COALB-4", "T_COALB-5"),
        power_mw=500.0,
        capacity_mwh=1000.0,
        optimiser="Alcemi (CIP)",
        region="Scotland (South)",
    ),
    FleetSite(
        site="Kilmarnock South",
        bmu_ids=(
            "T_KILSB-1",
            "T_KILSB-2",
            "T_KILSB-3",
            "T_KILSB-4",
            "T_KILSB-5",
            "T_KILSB-6",
        ),
        power_mw=300.0,
        capacity_mwh=600.0,
        optimiser="Zenobe",
        region="Scotland (South)",
    ),
    FleetSite(
        site="Blackhillock",
        bmu_ids=("T_BLHLB-1", "T_BLHLB-2", "T_BLHLB-3", "T_BLHLB-4"),
        power_mw=200.0,
        capacity_mwh=400.0,
        optimiser="Zenobe",
        region="Scotland (North)",
    ),
    FleetSite(
        site="Uskmouth",
        bmu_ids=("T_USKMB-2", "T_USKMB-3", "T_USKMB-4", "T_USKMB-5"),
        power_mw=230.0,
        capacity_mwh=460.0,
        optimiser="E.ON / UES",
        region="South Wales",
    ),
    FleetSite(
        site="Thornton",
        bmu_ids=("T_BLWNB-1",),
        power_mw=200.0,
        capacity_mwh=400.0,
        optimiser="Statkraft",
        region="Yorkshire",
    ),
    FleetSite(
        site="Ferrybridge",
        bmu_ids=("T_FERRB-1", "T_FERRB-2"),
        power_mw=150.0,
        capacity_mwh=300.0,
        optimiser="SSE",
        region="Yorkshire",
    ),
    FleetSite(
        site="Wilton",
        bmu_ids=("T_LIONB-1", "T_LIONB-2", "T_LIONB-3"),
        power_mw=150.0,
        capacity_mwh=300.0,
        optimiser="Sembcorp",
        region="North East England",
    ),
    FleetSite(
        site="Dollymans",
        bmu_ids=("E_DOLLB-1",),
        power_mw=100.0,
        capacity_mwh=200.0,
        optimiser="Statera",
        region="Eastern England",
    ),
    FleetSite(
        site="Capenhurst (Zenobe)",
        bmu_ids=("T_PINFB-1", "T_PINFB-2", "T_PINFB-3", "T_PINFB-4"),
        power_mw=100.0,
        capacity_mwh=107.0,
        optimiser="Zenobe",
        region="North West England",
    ),
    FleetSite(
        site="Richborough",
        bmu_ids=("T_RICHB-1", "T_RICHB-2"),
        power_mw=100.0,
        capacity_mwh=100.0,
        optimiser="Limejump (Shell)",
        region="South East England",
    ),
    FleetSite(
        site="Clay Tye",
        bmu_ids=("E_CLAYB-1", "E_CLAYB-2"),
        power_mw=99.0,
        capacity_mwh=198.0,
        optimiser="Tesla Autobidder",
        region="Eastern England",
    ),
    FleetSite(
        site="Pillswood",
        bmu_ids=("E_PILLB-1", "E_PILLB-2"),
        power_mw=98.0,
        capacity_mwh=196.0,
        optimiser="bp",
        region="Yorkshire",
    ),
    FleetSite(
        site="Enderby",
        bmu_ids=("T_ENDRB-1",),
        power_mw=57.0,
        capacity_mwh=114.0,
        optimiser="Flexitricity",
        region="East Midlands",
    ),
    FleetSite(
        site="Larks Green",
        bmu_ids=("T_LARKB-1",),
        power_mw=52.0,
        capacity_mwh=104.0,
        optimiser="EDF",
        region="South West England",
    ),
    FleetSite(
        site="Wishaw",
        bmu_ids=("T_WISHB-1",),
        power_mw=51.0,
        capacity_mwh=102.0,
        optimiser="Zenobe",
        region="Scotland (South)",
    ),
    FleetSite(
        site="Sundon",
        bmu_ids=("T_SUNDB-1",),
        power_mw=50.0,
        capacity_mwh=50.0,
        optimiser="Habitat Energy",
        region="Eastern England",
    ),
    FleetSite(
        site="Bredbury",
        bmu_ids=("T_BREDB-1",),
        power_mw=50.0,
        capacity_mwh=50.0,
        optimiser="Habitat Energy",
        region="North West England",
    ),
    FleetSite(
        site="Burwell (Weirs Drove)",
        bmu_ids=("E_BURWB-1",),
        power_mw=50.0,
        capacity_mwh=100.0,
        optimiser="Arenko",
        region="Eastern England",
    ),
    FleetSite(
        site="Broxburn",
        bmu_ids=("E_BROXB-1",),
        power_mw=50.0,
        capacity_mwh=100.0,
        optimiser="ENGIE",
        region="Scotland (South)",
    ),
    FleetSite(
        site="Whitelee",
        bmu_ids=("T_WHLWB-1",),
        power_mw=50.0,
        capacity_mwh=50.0,
        optimiser="ScottishPower",
        region="Scotland (South)",
    ),
    FleetSite(
        site="Roosecote",
        bmu_ids=("E_ROOSB-1",),
        power_mw=49.0,
        capacity_mwh=98.0,
        optimiser="Gresham House",
        region="North West England",
    ),
    FleetSite(
        site="Coupar Angus",
        bmu_ids=("E_CUPAB-1",),
        power_mw=41.0,
        capacity_mwh=82.0,
        optimiser="Octopus",
        region="Scotland (North)",
    ),
    FleetSite(
        site="Contego",
        bmu_ids=("E_CONTB-1",),
        power_mw=34.0,
        capacity_mwh=68.0,
        optimiser="Tesla Autobidder",
        region="South East England",
    ),
)


#: The metadata table as a population. Kept because it is the default argument
#: of every fetcher — a caller that names no population keeps writing to the
#: unsuffixed cache directory it has always written to.
CURATED = Population(name="curated", sites=CURATED_SITES, cache_suffix="")


def all_bmu_ids() -> tuple[str, ...]:
    """Every BM Unit ID this table covers."""
    return tuple(bmu for site in CURATED_SITES for bmu in site.bmu_ids)


def bmu_to_site() -> dict[str, FleetSite]:
    """Map each BM Unit ID to its :class:`FleetSite`."""
    return {bmu: site for site in CURATED_SITES for bmu in site.bmu_ids}
