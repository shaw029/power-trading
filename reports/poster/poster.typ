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
#set text(font: ("Helvetica Neue", "Helvetica", "Arial"), size: 20pt, fill: ink)
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
    Quantifying the Alignment Gap Between Battery Arbitrage and System Scarcity
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
    Merchant batteries already deliver #text(fill: cost-red)[79%] of the
    scarcity energy any schedule can achieve. Buying the rest costs
    #text(fill: cost-red)[£4/MW/day] — not the #text(fill: cost-red)[£50]
    a two-way comparison implies.
  ]
  #v(2mm)
  #text(size: 19pt, fill: ink.lighten(20%))[
    Prices find the scarcity peak. What they do not buy is the duration — and
    that turns out to be cheap.
  ]
]

#v(6mm)

// ─── Three columns ───────────────────────────────────────────────────────────
#columns(3, gutter: 20mm)[

#section("1 · The Problem, and the Fleet to Measure It", da-blue)

Grid-scale batteries optimise for arbitrage, but market signals do not always
align with system stress. Measuring that gap at fleet level needs a fleet — and
no public census of GB batteries exists, because Elexon labels no BM Unit a
battery.

So we built one: #metric[87 sites], #metric[124 BM Units], #metric[6,234 MW],
found by declared import matching declared export and corroborated against four
public registers. Sections 2–4 all measure this population.

Energy capacity is barely published: #metric[24 sites] read by hand off operator
pages with URL and read date, #metric[18] from Capacity Market filings, and
#metric[22] with none.

#panel("nb06_fig1_census_composition.svg", ratio: 87%)[
  Fig 1 — What the census contains. Seven sites hold a third of the fleet's MW,
  while the distribution-connected half of the fleet holds under a third of it.
]

#v(4mm)
#text(size: 20pt, weight: "bold", fill: ink)[
  Four analyses, four boundaries
]
#v(1mm)
#text(size: 17pt, fill: ink.lighten(15%))[
  They sit side by side but are not one sample.
]
#v(2mm)
#text(size: 17pt)[
  *Counterfactual* · 60 days, summer 2026 · 50 MW / 2 h reference battery \
  #text(fill: ink.lighten(35%))[The opportunity cost of stress delivery]

  *Observed response* · 2018–2026 · 87-site BM-registered census \
  #text(fill: ink.lighten(35%))[What the real fleet does under operator scarcity]

  *Revenue stack* · 60 days, recent EAC · sites with attributable awards \
  #text(fill: ink.lighten(35%))[Whether earnings track scarcity coverage]

  *Robustness* · Q1 2018 and winter 2019–20 · reference battery \
  #text(fill: ink.lighten(35%))[A different season, price archive and stress rule]
]

#colbreak()

#section("2 · The Gap Is Duration, and It Is Cheap", cost-red)

A profit-optimised #metric[50 MW / 2 h] battery delivers #metric[22%]
#text(size: 17pt)[(13–32%)] less stress-period energy than the same battery run
on a system-value objective — #metric[595 of 2,662 MWh]. That
counterfactual is our own objective, not a NESO instruction.

The shortfall is not mistimed. Mean discharge peaks at #metric[19:00], exactly
when stress does. The battery empties: #metric[88%] charged at 17:00, at its
#metric[10%] floor by 21:00 while the system is still tight #metric[59%] of the
time. The gap is duration, not timing.

Sweeping a blended objective prices that duration. The profit schedule delivers
#metric[79%] of the achievable stress energy for nothing, and all of it costs
#metric[£4.31/MW/day]. A further #metric[£88] buys none — only the rule never
to discharge off-flag.

#panel("nb04_fig2_diurnal_mismatch.svg", ratio: 75%)[
  Fig 2 — The mean day across all 34 days containing a stress hour. Discharge
  peaks at the same hour as stress, so the gap is not one of timing. It is
  duration: the battery reaches its floor by 21:00 while the system is still
  tight 59% of the time.
]

#panel("nb04_fig_alignment_frontier.svg", ratio: 75%)[
  Fig 3 — The whole trade-off, not its two endpoints. Day-ahead value sacrificed
  against stress delivery, sweeping the weight on system value. The dashed tail
  spends more and buys no stress energy.
]

#colbreak()

#section("3 · Real Fleet Performance Under Stress", discharge)

Measured against operator-grade scarcity (De-Rated Margin #metric[< 1 GW]), the
GB fleet performs well, discharging in #metric[95%] of periods. It delivers
#metric[+0.051 MW per MW online], against a #metric[+0.003 MW/MW] baseline.

The fleet arrives ready and does not empty. Charge rises from #metric[61%] six
hours out to #metric[66%] an hour before onset, and across #metric[418] events
only #metric[9%] of event time is spent below #metric[23%] charge.

Its shortfall is dispatch, not duration: #metric[51%] of usable energy is still
held at the deepest point of the average event. Declared duration does not
predict response either (#metric[r = +0.05] across 53 sites).

#panel("nb05_fig_gap_decomposition.svg", ratio: 88%)[
  Fig 4 — Readiness into the event, and which of the three gaps binds. For the
  modelled 2 h battery it is duration. For the real fleet it is dispatch.
]

#section("4 · The Full Revenue Stack", mid-amber)

Revenue does not buy scarcity coverage. Across revenue quartiles median earnings
rise from #metric[£18] to #metric[£224/MW/day] while median stress coverage
stays flat at #metric[0.22–0.25]. The headline correlation of −0.24 is a line
through noise.

Ancillary services do lift earnings — #metric[£7.23m] in 60 days — but only
#metric[27%] of the pound reaches a named site. Participation is a plausible
contributor to the fleet's response, not an identified cause.

#panel("nb04_fig5_revenue_stack.svg", ratio: 79%)[
  Fig 5 — The third stream lifts median earnings from £122 to £150 per MW per
  day, but most of the pound is collected by portfolios naming a trading unit.
]

#v(3mm)
#block(
  width: 100%,
  fill: mid-amber.lighten(90%),
  stroke: (left: 5pt + mid-amber),
  inset: (x: 6mm, y: 4mm),
  radius: 2pt,
)[
  #text(size: 20pt, weight: "bold", fill: ink)[What this implies]
  #v(1mm)
  #text(size: 19pt)[
    GB prices already find the scarcity peak; what they do not procure is
    sustained delivery, and that costs #metric[£4.31/MW/day], not £50. The
    question is not whether batteries respond but whether the market buys the
    right *duration* of response — reserve priced in hours rather than MW,
    readiness payments, energy co-optimised with ancillary services.
  ]
]

]

#v(2mm)
#line(length: 100%, stroke: 3pt + rule-grey)
#v(3mm)

#line(length: 100%, stroke: 3pt + rule-grey)
#v(2mm)

// A footer band, because the three columns leave the lower third of an A0
// empty and a reviewer reads the limitations before the conclusions.
#columns(4, gutter: 14mm)[

#text(size: 21pt, weight: "bold", fill: ink)[Method & data]
#v(2mm)
#text(size: 17pt)[
- *Public feeds only.* Elexon per-BMU notifications, acceptances and cashflows;
  NESO capacity, connection and auction registers; PV_Live. No subscription data.
- *The census is built, not downloaded.* Elexon labels no unit a battery.
- *Sites are found by symmetry* — declared import ≈ declared export. The rule
  recovers all 47 BM Units of the 23-site registry without being shown them.
]

#colbreak()

#text(size: 21pt, weight: "bold", fill: ink)[What these numbers cannot say]
#v(2mm)
#text(size: 17pt)[
- *State of charge is inferred* from notified position, never metered.
- *Three quarters of ancillary revenue reaches no site* — portfolios name a
  trading unit, not an asset. It is quantified and attributed to nobody.
- *Duration is declared, not metered* — energy capacity for a third of the
  census rests on operator disclosure rather than a register.
- *£4.31/MW/day is a private opportunity cost*, not a social one. It excludes
  avoided balancing cost, unserved energy, reserve procurement and peaker
  operation — the benefit side is unvalued here.
- *Rare samples are exhibits, not statistics.* Capacity Market Notices
  (#metric[n=13]) and DRM < 1 GW (#metric[n=39]) carry nothing like the weight
  of tiers with thousands of periods.
]

#colbreak()

#text(size: 21pt, weight: "bold", fill: ink)[Robustness]
#v(2mm)
#text(size: 17pt)[
- *Four definitions, one severe winter.* On winter 2019–20 (margin to
  #metric[213 MW], LoLP #metric[0.371]) the gap lands in #metric[20–24%], cost
  in #metric[£31–38/MW/day], across definitions spanning #metric[364] periods
  down to #metric[21]. The summer's #metric[22%] sits inside it.
- *Why a winter?* Operator scarcity does not occur in a GB summer — margin never
  falls below #metric[5.1 GW]. 2019–20 is also the last priceable one: no GB
  day-ahead price is published after the single market ended.
- *Bootstrap over days:* cost #metric[£37–63/MW/day].
]

#colbreak()

#text(size: 21pt, weight: "bold", fill: ink)[Sources & code]
#v(2mm)
#grid(
  columns: (1fr, 30mm), column-gutter: 6mm, align: (left + top, center + top),
  text(size: 16pt)[
    *Elexon* BMRS / Insights 2018–2026 · *NESO Data Portal* — Capacity Market
    register and notices, TEC and Embedded registers, per-unit auction results
    across all five eras · *PV_Live* · *ENTSO-E* (2018 and 2019–20 day-ahead) · *Nord Pool
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
