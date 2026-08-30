// Beyond the Spread — A0 portrait research poster.
//
// Figures are referenced as SVG, not PDF: Typst embeds PNG, JPEG, GIF and SVG,
// and has no PDF image support. The SVG and PDF exports carry the same vectors,
// so nothing is lost — see src/utils/poster.py.
//
// **Every number below is read from the notebooks, not typed here.** Each
// notebook writes its poster-facing figures to <name>_metrics.json beside its
// figures, and this file substitutes them. That is deliberate: a number typed
// onto a poster is a second copy of a result, and the two drift silently the
// moment a window moves or a register refreshes — which is exactly what
// happened before this was wired up. Re-run the notebooks, rebuild, and the
// board cannot disagree with the analysis.
//
// So: do not type a figure into this file. If the poster needs a number the
// notebooks do not publish, add it to that notebook's export cell first.
#let n4 = json("../figures/poster/nb04_metrics.json")
#let n5 = json("../figures/poster/nb05_metrics.json")
#let n6 = json("../figures/poster/nb06_metrics.json")

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
#set text(font: ("Helvetica Neue", "Helvetica", "Arial"), size: 18pt, fill: ink)
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
  #v(4mm)
  #line(length: 100%, stroke: 3pt + rule-grey)
  #v(2mm)
  #text(size: 19pt, fill: ink.lighten(25%))[
    A #n6.census_sites census of GB grid-scale batteries · 2018–2026 · built
    entirely from public Elexon and NESO data · all data as of #n6.snapshot
  ]
]

#v(4mm)

#block(
  width: 100%,
  fill: da-blue.lighten(90%),
  stroke: (left: 6pt + da-blue),
  inset: (x: 10mm, y: 6mm),
  radius: 2pt,
)[
  #text(size: 24pt, weight: "bold", fill: ink)[
    GB pays #text(fill: cost-red)[#n4.scarcity_mean] for scarcity across the window
    studied — and pays it in cash-out, not the day-ahead price batteries
    schedule against. So they find the peak and stop:
    #text(fill: cost-red)[#n4.forgone_pct] of system-optimal scarcity energy undelivered.
  ]
  #v(2mm)
  #text(size: 19pt, fill: ink.lighten(20%))[
    Closing it costs #text(fill: cost-red)[#n4.cost_all_share]. But no price
    closes it fully — a 2 h battery caps at #n4.dur2_best of what a 6 h one reaches.
  ]
]

#v(4mm)

// ─── Three columns ───────────────────────────────────────────────────────────
#columns(3, gutter: 20mm)[

#section("1 · The Problem, and the Fleet to Measure It", da-blue)

Measuring the gap at fleet level needs a fleet, and no public census of GB
batteries exists — Elexon labels no BM Unit a battery. So we built one:
#metric[#n6.census_sites], #metric[#n6.census_bmus], #metric[#n6.census_mw], found by declared
import matching declared export and corroborated against four public registers.
Sections 2–4 all measure this population.

Energy capacity is barely published: #metric[#n6.mwh_hand] read by hand off operator
pages, #metric[#n6.mwh_cm] from Capacity Market filings, #metric[#n6.mwh_none] with none.

#panel("nb06_fig1_census_composition.svg", ratio: 73%)[
  Fig 1 — What the census contains. #n6.top_band_sites sites hold #n6.top_band_share of the
  fleet's MW, while its #n6.dist_sites distribution-connected sites hold #n6.dist_share of it.
]

#v(4mm)
#text(size: 19pt, weight: "bold", fill: ink)[
  Four analyses, four boundaries — not one sample
]
#v(2mm)
#text(size: 17pt)[
  *Counterfactual* · 60 days, summer 2026 · 50 MW / 2 h reference battery \
  *Observed response* · 2018–2026 · the 87-site BM-registered census \
  *Revenue stack* · 60 days of EAC · sites with attributable awards \
  *Robustness* · Q1 2018 and winter 2019–20 · reference battery
]

#v(6mm)

#section("International Context: Who Prices Scarcity in Real Time", mid-amber)

Every market here runs the same wholesale, intraday and balancing stack. They
differ in whether scarcity reaches the price an asset schedules against.

#v(2mm)
#text(size: 17pt)[
  #table(
    columns: (auto, 1fr),
    stroke: none,
    inset: (x: 3mm, y: 1.6mm),
    fill: (_, row) => if row == 0 { rule-grey.lighten(55%) },
    table.header([*Market*], [*How scarcity enters the dispatch signal*]),
    [*Belgium*], [An alpha adder steepens the imbalance price once system
      imbalance passes a threshold; ORDC scarcity prices have run since 2019],
    [*Ireland*], [The imbalance price is the extremum of three components, one
      an explicit scarcity function],
    [*Netherlands*], [Continuously published activation and price make passive
      balancing a core battery revenue, not a residual cost],
    [*France*], [TURPE 7, live this month: up to €69/MWh to charge in
      solar-heavy zones, rewards for discharge at winter peaks],
    [*GB*], [VoLL × LoLP in cash-out — #metric[#n4.scarcity_mean] here — and nothing in
      the day-ahead price],
  )
]
#v(2mm)

The others price scarcity *continuously*. GB prices it in a step that almost
never fires, and in a settlement price rather than a scheduling one. REMA
(July 2025) ruled out zonal pricing and chose to deliver locational signals
through network charges instead — which is precisely the TURPE 7 route, already
running in France. This study is a measurement of what that choice has to fix.

#colbreak()

#section("2 · Why the Gap Exists, and What It Costs", cost-red)

A profit-optimised #metric[#n4.asset] battery delivers #metric[#n4.forgone_pct]
#text(size: 17pt)[#n4.forgone_ci] less stress-period energy than the same battery run
on a system-value objective — #metric[#n4.forgone_mwh]. That
counterfactual is our own objective, not a NESO instruction.

It is not mistimed: discharge peaks at #metric[#n4.peak_hour], exactly when stress does.
It simply empties, hitting its #metric[#n4.soc_floor] floor by #n4.floor_hour while the system is
still tight #metric[#n4.tight_at_floor] of the time — because nothing pays it not to. GB prices scarcity as
#metric[VoLL × LoLP] in the *imbalance* price: across this window that is
#metric[#n4.scarcity_mean] on average, exactly zero in #metric[#n4.scarcity_zero] of periods, and it
never reaches the day-ahead objective the battery actually maximises.

The gap runs both ways. A battery serves the system by absorbing surplus as well
as discharging into scarcity, and the profit schedule captures #metric[#n4.surplus_pct] of
surplus against #metric[#n4.stress_pct] of stress. It does track the system — dispatch
correlates #metric[#n4.dispatch_corr] with residual load — it stops short in both
directions.

Sweeping a blended objective prices it. The 2 h profit schedule already delivers
#metric[#n4.free_share] of everything *that* battery can deliver, and the rest costs under
#metric[#n4.cost_all_share] — about #metric[#n4.cost_all]
#text(size: 17pt)[#n4.cost_all_range], under the production model
(degradation £5/MWh, slippage £2/MWh, 1.5 cycles/day). The ceiling is energy,
not incentives: a #metric[6 h] battery reaches #metric[#n4.dur6_free] free where a
#metric[2 h] one caps at #metric[#n4.dur2_best] at any price.

#panel("nb04_fig2_diurnal_mismatch.svg", ratio: 62%)[
  Fig 2 — The mean day across all 34 days containing a stress hour. Discharge
  peaks at the same hour as stress, so the gap is not one of timing. It is
  duration: the battery reaches its floor by 21:00 while the system is still
  tight #n4.tight_at_floor of the time.
]

#panel("nb04_fig_duration_frontier.svg", ratio: 68%)[
  Fig 3 — The frontier is a family. Each curve sweeps the weight on system value
  for one duration; the dot is the profit schedule. Moving up beats moving right.
  Capital cost of the extra energy is not modelled.
]

#colbreak()

#section("3 · Real Fleet Performance Under Stress", discharge)

Measured against operator-grade scarcity (De-Rated Margin #metric[#n5.drm_threshold]), the
GB fleet discharges in #metric[#n5.discharge_share] of periods, delivering
#metric[#n5.response] against a #metric[#n5.baseline] baseline. That mean
hides a tail: #metric[#n5.tail_half] of site-periods run above half of nameplate.

The fleet does not empty: across #metric[#n5.events] events only
#metric[#n5.duration_gap] of event time is spent below its own low-water mark. It charges into
an event too — but so it does on any ordinary evening. Against controls matched
on the same half-hour, month *and year*, it arrives no fuller than usual, so the
run-up is the daily cycle rather than a response to the warning.

Its shortfall is dispatch, not duration: #metric[#n5.dispatch_gap] of usable energy is
still held at the deepest point of the average event, #n5.dispatch_multiple the
duration gap. Declared duration does not predict response either
(#metric[#n5.dur_corr] across #n5.dur_sites sites). Figures are on the primary
state-of-charge inference.

#panel("nb05_fig_gap_decomposition.svg", ratio: 72%)[
  Fig 4 — Readiness into the event, and which of the three gaps binds, on the
  primary state-of-charge inference. These do not sum: three questions, three
  denominators. For the modelled 2 h battery the
  answer is duration; for the real fleet it is dispatch.
]

#section("4 · The Full Revenue Stack", mid-amber)

If scarcity carries no rent, then earning more should *not* buy better scarcity
coverage — and it does not. Across revenue quartiles median earnings
rise from #metric[#n4.q_low] to #metric[#n4.q_high] while median stress coverage
stays flat at #metric[#n4.coverage_range]. The #n4.coverage_corr correlation is a line through noise.

Ancillary services do lift earnings — #metric[#n4.anc_site] in #n4.window_days — but only
#metric[#n4.anc_site_share] of the pound reaches a named site. Participation is a plausible
contributor to the fleet's response, not an identified cause.

#panel("nb04_fig5_revenue_stack.svg", ratio: 65%)[
  Fig 5 — The third stream lifts median earnings from #n4.median_base to #n4.median_full per MW per
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
    *Scarcity value never reaches the price batteries schedule against.* It is
    paid in cash-out, at #metric[#n4.scarcity_mean] across this window, and only inside
    a declared stress event — #metric[#n5.n_cmn] of those in eight years. So the fleet
    holds #metric[#n5.dispatch_gap] of its energy at an event's deepest point: nothing
    pays it to spend that energy. Duration bounds what any signal could buy — a
    2 h battery caps at #n4.dur2_best — but the binding problem here is the signal.
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
#text(size: 16pt)[
- *Public feeds only.* Elexon per-BMU notifications, acceptances and cashflows;
  NESO capacity, connection and auction registers; PV_Live. No subscription data.
- *The census is built, not downloaded.* Elexon labels no unit a battery.
- *Sites are found by symmetry* — declared import ≈ declared export. The rule
  admits #n6.curated_recovered of the #n6.curated_bmus hand-researched BM Units unaided.
]

#colbreak()

#text(size: 21pt, weight: "bold", fill: ink)[What these numbers cannot say]
#v(2mm)
#text(size: 16pt)[
- *State of charge is inferred* from notified position, never metered.
  Re-anchoring the inference daily moves levels about ten points, not the
  ordering.
- *Three quarters of ancillary revenue reaches no site* — portfolios name a
  trading unit, not an asset. It is quantified and attributed to nobody.
- *Duration is declared, not metered* — energy capacity for a third of the
  census rests on operator disclosure rather than a register.
- *The benchmark has perfect foresight* of realised intraday price — an upper
  bound; real dispatch tracks these curves from below.
- *Nothing here is priced socially or in capex.* Avoided balancing cost,
  unserved energy and reserve procurement are unvalued, and building 6 h is not
  costed: incentives cannot substitute for energy, but energy is not free.
- *Rare samples are exhibits, not statistics.* Capacity Market Notices
  (#metric[n=#n5.n_cmn]) and DRM < 1 GW (#metric[n=#n5.n_drm]) carry nothing like the weight
  of tiers with thousands of periods.
]

#colbreak()

#text(size: 21pt, weight: "bold", fill: ink)[Robustness]
#v(2mm)
#text(size: 16pt)[
- *Four definitions, one severe winter.* On winter 2019–20 (margin to
  #metric[#n4.winter_drm], LoLP #metric[#n4.winter_lolp]) the gap lands in #metric[#n4.winter_gap_range] across
  definitions spanning #metric[#n4.winter_periods_max] periods down to #metric[#n4.winter_periods_min] — and the
  summer's #metric[#n4.forgone_pct] sits inside it.
- *Why a winter?* Operator scarcity does not occur in a GB summer — margin stays
  far above any scarcity threshold throughout. 2019–20 is also the last priceable
  one: no GB day-ahead price is published after the single market ended.
- *Where the stress line is drawn* barely matters — at the top 5%, 10% and 15%
  of residual load the gap is #metric[#n4.thresh_gap_range].
- *Cost model against calendar.* Resampling days gives #metric[#n4.resample_range],
  and sweeping degradation #metric[£0–10] with slippage #metric[£0–4/MWh] gives
  #metric[#n4.cost_model_range]. Assumptions move it less than the sample does, and
  the frontier's shape shifts by #metric[#n4.frontier_shift].
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
    and read date. Policy: *Ofgem* LDES window 1, *EMRS* capacity-market
    guidance, *Terna* MACSE, *CRE* TURPE 7, *BNetzA*.
  ],
  [
    #image("../figures/poster/repo_qr.svg", width: 100%)
    #v(1mm)
    #text(size: 13pt, fill: ink.lighten(25%), hyphenate: false)[Repo]
  ],
)

]
