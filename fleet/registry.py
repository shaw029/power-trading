"""The battery fleet this project analyses — generated, do not hand-edit.

Every BM-registered GB battery the census can identify **whose energy capacity
is known**, which is what makes every dashboard metric computable for every site
shown: cycles per day and the duration bucket both divide by MWh, and a site
without one would render blank cells rather than a smaller number.

Every site in the curated registry is included: this is a superset of it, so the
dashboard can never show less than it did before. The generator refuses to write
a file that is not. Sizes are deliberately not written here — count the tuple
below, which is the only copy that cannot go stale.

Metadata provenance differs across the two groups and the difference matters:

* For the curated sites, ``optimiser``, ``region`` and
  ``capacity_mwh`` are hand-verified (see :mod:`fleet.registry`).
* For the rest, ``power_mw`` is Elexon's declared export capability and
  ``capacity_mwh`` comes from a matched Capacity Market agreement — both
  published figures. ``optimiser`` falls back to the BM Unit's lead party, which
  is the trading party rather than the optimiser proper, and ``region`` to the
  GSP group. Read the *By optimiser* cut with that in mind.

**Sites cycling below 0.3 cycles/day are left out**, measured over
2026-07-02 → 2026-08-30. That criterion is behaviour rather than identity, so this list moves
with market conditions as well as with the fleet — which is why the window is
recorded here. Left out on that basis:
  Capenhurst (0.08/day)
  Coylton  Greener Grid  Park (0.00/day)
  Enderby (0.00/day)
  INDIAN QUEENS BESS (0.00/day)
  Iron Acton (0.00/day)
  Monk Fryston BESS BMU-1 (0.00/day)
  Neilston Battery 1 (0.12/day)
  Pen y Cymoedd Battery (0.00/day)
  Roosecote (0.04/day)
  Sizing John (0.00/day)
  Thornton (0.11/day)
  Uskmouth (0.03/day)
  Whitegate (0.19/day)
  Wilton (0.25/day)

Generated 2026-08-30 from a census snapshot by ``scripts/build_registry.py``.
Regenerate when the fleet moves on; this file is data, not logic.
"""

from fleet.population import FleetSite, Population

REGISTRY_SITES: tuple[FleetSite, ...] = (
    FleetSite(
        site='AR0006-BLOX',
        bmu_ids=("E_ARNKB-1",),
        power_mw=41.7,
        capacity_mwh=47.0,
        optimiser='Octopus Energy Trading Limited',
        region='Midlands',
    ),
    FleetSite(
        site='Berkeley BESS',
        bmu_ids=("E_BERKB-1", "E_BERKB-2"),
        power_mw=104.0,
        capacity_mwh=49.9,
        optimiser='EDF Energy Customers Limited',
        region='Midlands',
    ),
    FleetSite(
        site='Blackhillock',
        bmu_ids=("T_BLHLB-1", "T_BLHLB-2", "T_BLHLB-3", "T_BLHLB-4"),
        power_mw=208.8,
        capacity_mwh=400.0,
        optimiser='Zenobe',
        region='Scotland (North)',
    ),
    FleetSite(
        site='Bredbury',
        bmu_ids=("T_BREDB-1",),
        power_mw=49.9,
        capacity_mwh=50.0,
        optimiser='Habitat Energy',
        region='North West England',
    ),
    FleetSite(
        site='Brentwood BESS',
        bmu_ids=("E_BRETB-1", "E_BRETB-2"),
        power_mw=104.0,
        capacity_mwh=49.9,
        optimiser='EDF Energy Customers Limited',
        region='Eastern',
    ),
    FleetSite(
        site='Brook Farm BESS',
        bmu_ids=("E_BROFB-1",),
        power_mw=52.0,
        capacity_mwh=49.4,
        optimiser='EDF Energy Customers Limited',
        region='Eastern',
    ),
    FleetSite(
        site='Broxburn',
        bmu_ids=("E_BROXB-1",),
        power_mw=50.0,
        capacity_mwh=100.0,
        optimiser='ENGIE',
        region='Scotland (South)',
    ),
    FleetSite(
        site='Bulphan Fen Warley Green BESS',
        bmu_ids=("T_BLPFB-1",),
        power_mw=56.6,
        capacity_mwh=75.0,
        optimiser='EDF Energy Customers Limited',
        region='unknown',
    ),
    FleetSite(
        site='Burwell (Weirs Drove)',
        bmu_ids=("E_BURWB-1", "E_BURWB-2", "E_BURWB-3"),
        power_mw=132.5,
        capacity_mwh=100.0,
        optimiser='Arenko',
        region='Eastern England',
    ),
    FleetSite(
        site='Capenhurst (Zenobe)',
        bmu_ids=("T_PINFB-1", "T_PINFB-2", "T_PINFB-3", "T_PINFB-4"),
        power_mw=105.1,
        capacity_mwh=107.0,
        optimiser='Zenobe',
        region='North West England',
    ),
    FleetSite(
        site='Carnegie Road 1',
        bmu_ids=("E_CRSSB-1",),
        power_mw=20.0,
        capacity_mwh=20.0,
        optimiser='Arenko Cleantech Limited',
        region='Merseyside North Wales',
    ),
    FleetSite(
        site='CathkinBattery',
        bmu_ids=("E_CATHB-1",),
        power_mw=49.9,
        capacity_mwh=100.0,
        optimiser='ENGIE Power Limited',
        region='South Scotland',
    ),
    FleetSite(
        site='Chapel Farm BESS',
        bmu_ids=("E_CHAPB-1",),
        power_mw=50.2,
        capacity_mwh=84.0,
        optimiser='Tesla Motors Limited',
        region='Eastern',
    ),
    FleetSite(
        site='Clay Tye',
        bmu_ids=("E_CLAYB-1", "E_CLAYB-2"),
        power_mw=99.0,
        capacity_mwh=198.0,
        optimiser='Tesla Autobidder',
        region='Eastern England',
    ),
    FleetSite(
        site='Coalburn 1',
        bmu_ids=("T_COALB-1", "T_COALB-2", "T_COALB-3", "T_COALB-4", "T_COALB-5"),
        power_mw=512.4,
        capacity_mwh=1000.0,
        optimiser='Alcemi (CIP)',
        region='Scotland (South)',
    ),
    FleetSite(
        site='Contego',
        bmu_ids=("E_CONTB-1",),
        power_mw=35.8,
        capacity_mwh=68.0,
        optimiser='Tesla Autobidder',
        region='South East England',
    ),
    FleetSite(
        site='Coupar Angus',
        bmu_ids=("E_CUPAB-1",),
        power_mw=41.3,
        capacity_mwh=82.0,
        optimiser='Octopus',
        region='Scotland (North)',
    ),
    FleetSite(
        site='Cowley',
        bmu_ids=("T_COWB-1",),
        power_mw=50.4,
        capacity_mwh=50.0,
        optimiser='Pivoted Power LLP',
        region='unknown',
    ),
    FleetSite(
        site='Dollymans',
        bmu_ids=("E_DOLLB-1",),
        power_mw=102.0,
        capacity_mwh=200.0,
        optimiser='Statera',
        region='Eastern England',
    ),
    FleetSite(
        site='Erskine BESS',
        bmu_ids=("E_ERSKB-1",),
        power_mw=29.9,
        capacity_mwh=30.0,
        optimiser='EDF Energy Customers Limited',
        region='South Scotland',
    ),
    FleetSite(
        site='Farnham BESS',
        bmu_ids=("E_FARNB-1",),
        power_mw=20.0,
        capacity_mwh=40.0,
        optimiser='Tesla Motors Limited',
        region='Southern',
    ),
    FleetSite(
        site='Ferrybridge',
        bmu_ids=("T_FERRB-1", "T_FERRB-2"),
        power_mw=152.0,
        capacity_mwh=300.0,
        optimiser='SSE',
        region='Yorkshire',
    ),
    FleetSite(
        site='Gerrards Cross BESS',
        bmu_ids=("E_GRCRB-1",),
        power_mw=20.0,
        capacity_mwh=20.0,
        optimiser='FIELD GERRARDS CROSS LTD',
        region='Southern',
    ),
    FleetSite(
        site='HawkersHill  Battery',
        bmu_ids=("E_HAWKB-1",),
        power_mw=20.0,
        capacity_mwh=40.0,
        optimiser='Tesla Motors Limited',
        region='Southern',
    ),
    FleetSite(
        site='Holes Bay Battery',
        bmu_ids=("E_BHOLB-1",),
        power_mw=7.1,
        capacity_mwh=10.0,
        optimiser='Tesla Motors Limited',
        region='Southern',
    ),
    FleetSite(
        site='Hunningley Stairfoot BESS',
        bmu_ids=("E_BARNB-1",),
        power_mw=44.0,
        capacity_mwh=40.0,
        optimiser='EDF Energy Customers Limited',
        region='Yorkshire',
    ),
    FleetSite(
        site='KXP Immingham BESS',
        bmu_ids=("E_STALB-1",),
        power_mw=80.8,
        capacity_mwh=160.0,
        optimiser='KXP Immingham Ltd',
        region='Yorkshire',
    ),
    FleetSite(
        site='Kilmarnock South',
        bmu_ids=("T_KILSB-1", "T_KILSB-2", "T_KILSB-3", "T_KILSB-4", "T_KILSB-5", "T_KILSB-6"),
        power_mw=312.6,
        capacity_mwh=600.0,
        optimiser='Zenobe',
        region='Scotland (South)',
    ),
    FleetSite(
        site='Lakeside  BESS',
        bmu_ids=("T_LKSDB-1",),
        power_mw=105.0,
        capacity_mwh=149.9,
        optimiser='Lakeside Energy Storage Ltd',
        region='unknown',
    ),
    FleetSite(
        site='Larks Green',
        bmu_ids=("T_LARKB-1",),
        power_mw=52.0,
        capacity_mwh=104.0,
        optimiser='EDF',
        region='South West England',
    ),
    FleetSite(
        site='Little Raith BESS',
        bmu_ids=("E_LITRB-1",),
        power_mw=50.0,
        capacity_mwh=98.0,
        optimiser='Tesla Motors Limited',
        region='South Scotland',
    ),
    FleetSite(
        site='Monk Fryston',
        bmu_ids=("T_MKFRB-1",),
        power_mw=57.0,
        capacity_mwh=165.0,
        optimiser='HD777FRY Ltd',
        region='unknown',
    ),
    FleetSite(
        site='Native River',
        bmu_ids=("T_NTRVB-1",),
        power_mw=57.0,
        capacity_mwh=138.0,
        optimiser='Arenko Cleantech Limited',
        region='unknown',
    ),
    FleetSite(
        site='Newton wood BESS',
        bmu_ids=("E_NEWTB-1",),
        power_mw=52.0,
        capacity_mwh=49.9,
        optimiser='EDF Energy Customers Limited',
        region='East Midlands',
    ),
    FleetSite(
        site='North Tawton BESS',
        bmu_ids=("E_NTAWB-1",),
        power_mw=32.0,
        capacity_mwh=30.0,
        optimiser='EDF Energy Customers Limited',
        region='South Western',
    ),
    FleetSite(
        site='Ocker Hill',
        bmu_ids=("T_OCHLB-1",),
        power_mw=58.0,
        capacity_mwh=165.0,
        optimiser='HD143OCK Ltd',
        region='unknown',
    ),
    FleetSite(
        site='Oldham BESS',
        bmu_ids=("E_OLDHB-1",),
        power_mw=20.0,
        capacity_mwh=20.0,
        optimiser='Field Oldham Ltd',
        region='North Western',
    ),
    FleetSite(
        site='Pillswood',
        bmu_ids=("E_PILLB-1", "E_PILLB-2"),
        power_mw=99.8,
        capacity_mwh=196.0,
        optimiser='bp',
        region='Yorkshire',
    ),
    FleetSite(
        site='Pivot Power Bustleholme',
        bmu_ids=("T_BUSTB-1",),
        power_mw=52.2,
        capacity_mwh=100.0,
        optimiser='Pivoted Power LLP',
        region='unknown',
    ),
    FleetSite(
        site='Pivot Power Coventry',
        bmu_ids=("T_COVNB-1",),
        power_mw=50.4,
        capacity_mwh=80.0,
        optimiser='Pivoted Power LLP',
        region='unknown',
    ),
    FleetSite(
        site='Richborough',
        bmu_ids=("T_RICHB-1", "T_RICHB-2"),
        power_mw=99.8,
        capacity_mwh=100.0,
        optimiser='Limejump (Shell)',
        region='South East England',
    ),
    FleetSite(
        site='Roaring Hill BESS',
        bmu_ids=("E_ROARB-1",),
        power_mw=50.0,
        capacity_mwh=75.0,
        optimiser='Tesla Motors Limited',
        region='South Scotland',
    ),
    FleetSite(
        site='Skelmersdale Battery',
        bmu_ids=("E_SKELB-1",),
        power_mw=49.9,
        capacity_mwh=99.8,
        optimiser='Tesla Motors Limited',
        region='North Western',
    ),
    FleetSite(
        site='Sundon',
        bmu_ids=("T_SUNDB-1",),
        power_mw=50.2,
        capacity_mwh=50.0,
        optimiser='Habitat Energy',
        region='Eastern England',
    ),
    FleetSite(
        site='T_THURB-1',
        bmu_ids=("T_THURB-1", "T_THURB-2", "T_THURB-3"),
        power_mw=300.0,
        capacity_mwh=600.0,
        optimiser='THURROCK STORAGE LIMITED',
        region='unknown',
    ),
    FleetSite(
        site='Tye Lane BESS',
        bmu_ids=("T_TYLNB-1",),
        power_mw=59.2,
        capacity_mwh=114.0,
        optimiser='Pivoted Power LLP',
        region='unknown',
    ),
    FleetSite(
        site='West Burton B Battery',
        bmu_ids=("T_WBURB-41", "T_WBURB-43"),
        power_mw=62.0,
        capacity_mwh=49.0,
        optimiser='West Burton B Limited',
        region='unknown',
    ),
    FleetSite(
        site='Whitebirk BESS',
        bmu_ids=("E_WHTBB-1",),
        power_mw=25.0,
        capacity_mwh=36.6,
        optimiser='Field Whitebirk Ltd',
        region='North Western',
    ),
    FleetSite(
        site='Whitelee',
        bmu_ids=("T_WHLWB-1",),
        power_mw=50.2,
        capacity_mwh=50.0,
        optimiser='ScottishPower',
        region='Scotland (South)',
    ),
    FleetSite(
        site='Wishaw',
        bmu_ids=("T_WISHB-1",),
        power_mw=51.0,
        capacity_mwh=102.0,
        optimiser='Zenobe',
        region='Scotland (South)',
    ),
    FleetSite(
        site='Wolverhampton West BESS',
        bmu_ids=("E_WOLVB-1",),
        power_mw=56.0,
        capacity_mwh=310.0,
        optimiser='EDF Energy Customers Limited',
        region='Midlands',
    ),
)

#: The dashboard's population. Its own cache suffix, because a day-file
#: holds exactly the BM Units it was fetched for — reusing the curated
#: cache would silently serve a 47-unit day as if it were the whole fleet.
REGISTRY = Population(
    name="registry", sites=REGISTRY_SITES, cache_suffix="_REGISTRY"
)
