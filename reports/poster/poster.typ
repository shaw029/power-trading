// Beyond the Spread — A0 portrait research poster.
//
// Figures are referenced as SVG, not PDF: Typst embeds PNG, JPEG, GIF and SVG,
// and has no PDF image support. The SVG and PDF exports carry the same vectors,
// so nothing is lost — see src/utils/poster.py.

#let ink        = rgb("#0b0b0b")
#let da-blue    = rgb("#2a78d6")
#let discharge  = rgb("#1baf7a")
#let cost-red   = rgb("#e34948")
#let mid-amber  = rgb("#c98500")
#let paper      = rgb("#fcfcfb")
#let rule-grey  = rgb("#d8d7d0")

#let FIG = "../figures/poster/"

// A0 portrait. Margins are generous because a poster is read standing up and
// crowding the edge is what makes a board feel dense.
#set page(
  width: 1189mm, height: 841mm,
  margin: (x: 40mm, top: 32mm, bottom: 28mm),
  fill: paper,
)

// Body copy at 26pt. Poster text is read from roughly 1.5 m, where anything
// under about 24pt starts costing the reader.
#set text(font: ("Helvetica Neue", "Helvetica", "Arial"), size: 21pt, fill: ink)
#set par(justify: true, leading: 0.62em)

// A metric that must survive being read at a glance.
#let metric(body) = text(weight: "bold", fill: ink)[#body]

// Section heading: a coloured rule above the title carries the section's
// identity without spending a whole band of colour on it.
#let section(title, accent) = block(width: 100%, breakable: false)[
  #line(length: 100%, stroke: 4pt + accent)
  #v(-3mm)
  #block(inset: (top: 5mm, bottom: 3mm))[
    #text(size: 30pt, weight: "bold", fill: ink)[#title]
  ]
]

// Figure with a caption beneath. `scale` lets a panel exceed its column when
// the figure's own labels would otherwise be too small to read.
#let panel(path, caption, ratio: 97%) = block(width: 100%, breakable: false)[
  #v(3mm)
  #align(center)[#image(FIG + path, width: ratio)]
  #v(2mm)
  #text(size: 16pt, fill: ink.lighten(35%), style: "italic")[#caption]
  #v(5mm)
]

// ─── Title banner ────────────────────────────────────────────────────────────
#block(width: 100%)[
  #text(size: 62pt, weight: "bold", fill: ink)[
    Beyond the Spread
  ]
  #v(3mm)
  #text(size: 32pt, fill: da-blue)[
    Quantifying the Alignment Gap Between Battery Arbitrage and Energy System Resilience
  ]
  #v(6mm)
  #line(length: 100%, stroke: 3pt + rule-grey)
  #v(3mm)
  #text(size: 19pt, fill: ink.lighten(25%))[
    An 87-site census of GB grid-scale batteries · 2018–2026 · built entirely
    from public Elexon and NESO data
  ]
]

#v(5mm)

#block(
  width: 100%,
  fill: da-blue.lighten(90%),
  stroke: (left: 6pt + da-blue),
  inset: (x: 10mm, y: 6mm),
  radius: 2pt,
)[
  #text(size: 24pt, weight: "bold", fill: ink)[
    Full alignment to system resilience costs #text(fill: cost-red)[£50/MW/day] —
    #text(fill: cost-red)[47%] of day-ahead value — and pure arbitrage still
    leaves #text(fill: cost-red)[22%] of stress-hour energy undelivered.
  ]
  #v(2mm)
  #text(size: 19pt, fill: ink.lighten(20%))[
    The real GB fleet does better than the arbitrage benchmark under genuine
    scarcity, and ancillary revenue is why.
  ]
]

#v(6mm)

// ─── Three columns ───────────────────────────────────────────────────────────
#columns(3, gutter: 20mm)[

#section("1 · The Research Problem & Coverage Gap", da-blue)

Grid-scale batteries optimise for arbitrage, but market signals do not always
align with system stress. Previous studies relied on a curated 23-site registry
capturing only #metric[46.4%] of operational capacity.

We reconstructed an #metric[87-site census] of #metric[124 BM Units], totalling
#metric[6,234 MW].
Physical energy capacity (MWh) was hierarchically sourced to prevent a
#metric[~34% duration understatement] caused by Capacity Market de-rating.

#panel("nb06_fig2_coverage_by_basis.svg")[
  Fig 1 — Registry coverage of the census by site count, MW and MWh. MW is the
  headline; site count flatters a sample that deliberately picked large assets.
]

#panel("nb06_fig3_where_missing_mw_sits.svg")[
  Fig 2 — Where the missing MW sits. Coverage falls away with site size and off
  the transmission network.
]

#colbreak()

#section("2 · The Alignment Gap: Profit vs Resilience", cost-red)

A purely profit-optimised #metric[50 MW / 2 h] reference battery captures
#metric[40.5%] stress coverage. Forcing alignment to grid resilience costs
#metric[~£50/MW/day], sacrificing #metric[47%] of Day-Ahead value.

Pure arbitrage inherently leaves #metric[22% (595 MWh)] of potential
stress-hour energy undelivered.

#panel("nb04_fig1_exemplar_day.svg")[
  Fig 3 — Exemplar day: profit-optimal dispatch discharging into evening stress
  and charging through midday surplus.
]

#panel("nb04_fig2_value_vs_stress_energy.svg")[
  Fig 4 — Value earned against stress energy delivered. The gap between the two
  is the cost of alignment.
]

#colbreak()

#section("3 · Real Fleet Performance Under Stress", discharge)

Measured against operator-grade scarcity (De-Rated Margin #metric[< 1 GW]), the
GB fleet performs well, discharging in #metric[95%] of periods. It delivers
#metric[+0.051 MW per MW online], against a #metric[+0.003 MW/MW] baseline.

Cycle-filtered state-of-charge inference shows the fleet enters sub-1 GW events
with a robust #metric[64%] capacity.

#panel("nb05_fig4_response_by_system_state.svg")[
  Fig 5 — Fleet net response across system stress tiers.
]

#section("4 · The Full Revenue Stack", mid-amber)

Evaluating only Wholesale and Balancing Mechanism revenue shows a
#metric[negative correlation (−0.21)] with stress coverage.

Enduring Auction Capability (EAC) data proves ancillary services lift the
fleet: in 60 days #metric[£7.23m] landed on census sites, with #metric[72%] of
active, high-cycling batteries participating — but only #metric[27%] of the
ancillary pound reaches a site at all.

#panel("nb04_fig5_revenue_stack.svg")[
  Fig 6 — The third stream lifts a site's median earnings from £122 to £150 per
  MW per day. Most of the pound, though, is collected by portfolios that name a
  trading unit rather than an asset.
]

]

#v(4mm)
#line(length: 100%, stroke: 3pt + rule-grey)
#v(4mm)

// A footer band, because the three columns leave the lower third of an A0
// empty and a reviewer reads the limitations before the conclusions.
#columns(4, gutter: 14mm)[

#text(size: 23pt, weight: "bold", fill: ink)[Method & data]
#v(2mm)
#text(size: 18pt)[
- *Public feeds only.* Elexon per-BMU notifications, acceptances and cashflows;
  NESO capacity, connection and auction registers; PV_Live. No subscription data.
- *The census is built, not downloaded.* Elexon labels no unit a battery.
- *Sites are found by symmetry* — declared import ≈ declared export. The rule
  recovers all 47 BM Units of the 23-site registry without being shown them.
]

#colbreak()

#text(size: 23pt, weight: "bold", fill: ink)[What these numbers cannot say]
#v(2mm)
#text(size: 18pt)[
- *State of charge is inferred* from notified position, never metered.
- *Three quarters of ancillary revenue reaches no site* — portfolios name a
  trading unit, not an asset. It is quantified and attributed to nobody.
- *Two definitions of stress.* Sections 1–2 use tightness relative to their
  window; section 3 uses operator-grade scarcity. Not interchangeable.
]

#colbreak()

#text(size: 23pt, weight: "bold", fill: ink)[Robustness]
#v(2mm)
#text(size: 18pt)[
- *Why 60 days?* Nord Pool publishes GB day-ahead prices on a rolling basis —
  a limit of the data, not the method.
- *Re-run on Q1 2018* with ENTSO-E archived auction prices, spanning the
  #emph[Beast from the East]: stress coverage #metric[44%] against #metric[40%],
  correlation #metric[+0.42] against #metric[+0.41].
- *The result survives* a different fleet, price archive and scarcity mechanism.
]

#colbreak()

#text(size: 23pt, weight: "bold", fill: ink)[Sources & code]
#v(2mm)
#grid(
  columns: (1fr, 30mm), column-gutter: 6mm, align: (left + top, center + top),
  text(size: 16pt)[
    *Elexon* BMRS / Insights 2018–2026 · *NESO Data Portal* — Capacity Market
    register and notices, TEC and Embedded registers, per-unit auction results
    across all five eras · *PV_Live* · *ENTSO-E* (2018 day-ahead) · *Nord Pool
    N2EX* · *operator disclosures* for energy capacity, each carrying its source
    and read date.
  ],
  [
    #image("../figures/poster/repo_qr.svg", width: 100%)
    #v(1mm)
    #text(size: 13pt, fill: ink.lighten(25%), hyphenate: false)[Repo]
  ],
)

]
