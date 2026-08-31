// Beyond the Spread — A0 landscape research poster (1189 x 841 mm).
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
#let n7 = json("../figures/poster/nb07_metrics.json")
#let n8 = json("../figures/poster/nb08_metrics.json")

#let ink        = rgb("#0b0b0b")
#let da-blue    = rgb("#2a78d6")
#let discharge  = rgb("#1baf7a")
#let cost-red   = rgb("#e34948")
#let mid-amber  = rgb("#c98500")
#let paper      = rgb("#fcfcfb")
#let rule-grey  = rgb("#d8d7d0")

#let FIG = "../figures/poster/"

// A0 landscape. Margins are generous because a poster is read standing up and
// crowding the edge is what makes a board feel dense.
#set page(
  width: 1189mm, height: 841mm,
  margin: (x: 40mm, top: 32mm, bottom: 28mm),
  fill: paper,
)

// Body copy at 16pt, read from roughly 1.5 m. Well above the 11pt floor this
// board sets itself; the columns were tightened first, and this is what bought
// the footer strip its room.
#set text(font: ("Helvetica Neue", "Helvetica", "Arial"), size: 16pt, fill: ink)
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
// Gutters were 3/2/5mm. The board is exactly full at A0, so the six panels'
// surrounding whitespace is the cheapest place to find the ~20 lines the
// modern-era callout and the connective lines need — it costs no content.
#let panel(path, caption, ratio: 97%) = block(width: 100%, breakable: false)[
  #v(2mm)
  #align(center)[#image(FIG + path, width: ratio)]
  #v(1.5mm)
  #text(size: 16pt, fill: ink.lighten(35%), style: "italic")[#caption]
  #v(3mm)
]

// ─── Title banner ────────────────────────────────────────────────────────────
#block(width: 100%)[
  #text(size: 62pt, weight: "bold", fill: ink)[
    Beyond the Spread
  ]
  #v(3mm)
  #text(size: 32pt, fill: da-blue)[
    Quantifying the Alignment Gap Between Battery Arbitrage and System Value
  ]
  #v(3mm)
  #line(length: 100%, stroke: 3pt + rule-grey)
  #v(1.5mm)
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
    GB does not put scarcity in the price batteries trade against — so the fleet
    finds the peak and stops.
  ]
  #v(2.5mm)
  // Two different quantities, deliberately in two rows: the modelled gap is a
  // utilisation figure, the price is a scarcity one, and a reader who merges
  // them has the argument backwards.
  #grid(
    columns: (1fr, 1fr),
    gutter: 12mm,
    [
      #text(size: 20pt)[
        *The gap, modelled.* #text(fill: da-blue, weight: "bold")[#n4.forgone_pct] of
        stress-period energy left undelivered — stress meaning the top decile of
        residual load, a utilisation measure.
      ]
    ],
    [
      #text(size: 20pt)[
        *The price, measured.* Scarcity itself settles at
        #text(fill: da-blue, weight: "bold")[#n4.scarcity_mean], inside
        #text(fill: da-blue, weight: "bold")[#n5.n_cmn] declared events in eight years.
      ]
    ],
  )
  #v(2.5mm)
  #text(size: 19pt, fill: ink.lighten(20%))[
    Nearly free today, because GB barely has scarcity — expected loss of load
    averages #n8.lole_mean_h a year against a 3 h standard. The warning is for when
    it does.
  ]
]

#v(4mm)

// ─── Three columns ───────────────────────────────────────────────────────────
#columns(3, gutter: 20mm)[

#section("1 · The choice, and the fleet to measure it", da-blue)

Measuring the gap at fleet level needs a fleet, and no public census of GB
batteries exists — Elexon labels no BM Unit a battery. So we built one:
#metric[#n6.census_sites], #metric[#n6.census_bmus], #metric[#n6.census_mw], found by declared
import matching declared export and corroborated against four public registers.
Sections 2–4 all measure this population.

Energy capacity is barely published: #metric[#n6.mwh_hand] read by hand off operator
pages, #metric[#n6.mwh_cm] from Capacity Market filings, #metric[#n6.mwh_none] with none.

#panel("nb06_fig1_census_composition.svg", ratio: 78%)[
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

#section("The gap is a design choice", mid-amber)

Every market here runs the same wholesale, intraday and balancing stack. They
differ in whether the system's real-time needs reach the price an asset schedules
against. The first three rows are scarcity; France's is locational congestion —
the same question asked of a different need.

#v(2mm)
#text(size: 17pt)[
  #table(
    columns: (auto, 1fr),
    stroke: none,
    inset: (x: 3mm, y: 1.6mm),
    fill: (_, row) => if row == 0 { rule-grey.lighten(55%) },
    table.header([*Market*], [*How a system need reaches the battery's schedule*]),
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

#section("2 · Route 1 — the incentive, modelled", cost-red)

#block(
  width: 100%,
  fill: cost-red.lighten(93%),
  stroke: (left: 4pt + cost-red),
  inset: (x: 5mm, y: 3mm),
  radius: 2pt,
)[
  #text(size: 18pt)[
    *This is a model of the incentive alone — not the real fleet.* One
    #n4.asset optimiser, perfect foresight, #n4.window_days.
  ]
]

#v(3mm)

A profit-optimised #metric[#n4.asset] battery delivers #metric[#n4.forgone_pct]
#text(size: 17pt)[#n4.forgone_ci] less energy than the same battery run on a system-value
objective — #metric[#n4.forgone_mwh] — across the *tightest decile of residual load*.
That is system utilisation, not operator scarcity: sections 3 and 4 use the operator's
own measures. The counterfactual is our objective, not a NESO instruction.

It is not mistimed: discharge peaks at #metric[#n4.peak_hour], exactly when load does.
It simply empties, hitting its #metric[#n4.soc_floor] floor by #n4.floor_hour while the system is
still tight #metric[#n4.tight_at_floor] of the time — because nothing pays it not to. GB prices scarcity as
#metric[VoLL × LoLP] in the *imbalance* price: across this window that is
#metric[#n4.scarcity_mean] on average, exactly zero in #metric[#n4.scarcity_zero] of periods, and it
never reaches the day-ahead objective the battery actually maximises.

The gap runs both ways. A battery serves the system by absorbing surplus as well
as discharging into scarcity, and the profit schedule captures #metric[#n4.surplus_pct] of
surplus against #metric[#n4.stress_pct] of top-decile load. It tracks the system — dispatch
correlates #metric[#n4.dispatch_corr] with residual load — it stops short in both
directions.

Sweeping a blended objective prices it. The 2 h profit schedule already delivers
#metric[#n4.free_share] of everything *that* battery can deliver, and the rest costs under
#metric[#n4.cost_all_share] — about #metric[#n4.cost_all]
#text(size: 17pt)[#n4.cost_all_range], under the production model
(degradation £5/MWh, slippage £2/MWh, 1.5 cycles/day). The ceiling is energy,
not incentives: a #metric[6 h] battery reaches #metric[#n4.dur6_free] free where a
#metric[2 h] one caps at #metric[#n4.dur2_best] at any price.

#panel("nb04_fig2_diurnal_mismatch.svg", ratio: 66%)[
  Fig 2 — The mean day across all 34 days containing a top-decile load hour.
  Discharge peaks at the same hour, so the gap is not one of timing. It is
  duration: the battery reaches its floor by 21:00 while the system is still
  tight #n4.tight_at_floor of the time.
]

#panel("nb04_fig_duration_frontier.svg", ratio: 70%)[
  Fig 3 — The frontier is a family. Each curve sweeps the weight on system value
  for one duration; the dot is the profit schedule. Moving up beats moving right.
  It is the ceiling, not the cause: a perfect signal stops at these curves, and
  GB's never starts. Capital cost of the extra energy is not modelled.
]

#colbreak()

#section("3 · Route 2 — the fleet, measured", discharge)

#block(
  width: 100%,
  fill: discharge.lighten(93%),
  stroke: (left: 4pt + discharge),
  inset: (x: 5mm, y: 3mm),
  radius: 2pt,
)[
  #text(size: 18pt)[
    *Measured, not modelled.* Every BM-registered GB battery — the
    #n6.census_sites census — against the operator's own signals, 2018–2026.
  ]
]

#v(3mm)

*Section 2 is what the incentive alone produces.* The real fleet does better —
operator signals pull it in where price does not — yet still holds roughly half its
energy at the deepest point. Two routes, one missing signal.

Measured against operator-grade scarcity (De-Rated Margin #metric[#n5.drm_threshold]), the
GB fleet discharges in #metric[#n5.discharge_share] of periods, delivering
#metric[#n5.response] against a #metric[#n5.baseline] baseline. That mean
hides a tail: #metric[#n5.tail_half] of site-periods run above half of nameplate.

The fleet does not empty: across #metric[#n5.events] events only
#metric[#n5.duration_gap] of event time is spent below its own low-water mark. It charges into
an event too — but so it does on any ordinary evening. Against controls matched
on the same half-hour, month *and year*, it arrives no fuller than usual, so the
run-up is the daily cycle rather than a response to the warning.

Its shortfall is dispatch, not duration, and declared duration does not predict
response (#metric[#n5.dur_corr] across #n5.dur_sites sites). Figures are on the primary
state-of-charge inference.

*Since #n8.era_start the gap moves.* On the same rules the modern fleet responds
#metric[#n8.ratio_low–#n8.ratio_high] harder but arrives *emptier*: SoC at onset
#n5.soc_at_onset → #metric[#n8.soc_at_onset], dispatch gap #n5.dispatch_gap →
#metric[#n8.dispatch_gap], preparedness #n5.preparedness_gap → #metric[#n8.preparedness_gap]
and now the larger. It trades in ordinary conditions, so less is left in the tank
(#n8.events events).

#panel("nb07_fig_regime_shift.svg", ratio: 47%)[
  Fig 4 — The fleet stopped hoarding and started running empty. Modern against
  skip-era response by margin band, same absolute rules: the change is largest
  where the system was #emph[loosest] (#n7.loosest_ratio at #n7.loosest_band, from
  near zero), so this is a fleet becoming active at all rather than learning to
  chase scarcity. Same-site panel moves #n7.panel_ratio against the fleet's
  #n7.fleet_ratio. Hatched = thin sample.
]

#text(size: 24pt, weight: "bold", fill: ink)[Why it arrives empty]
#v(2mm)

If scarcity carries no rent, earning more should *not* buy better coverage — and
it does not.

#panel("nb04_fig_money_vs_coverage.svg", ratio: 42%)[
  Fig 5 — Paying a battery more does not buy the system more. Revenue rises
  #n4.revenue_multiple across quartiles while coverage stays flat at
  #n4.coverage_range (#n4.coverage_corr — a line through noise). The fleet chases
  merchant value all day, which is why it reaches the next tight period depleted.
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

#v(3mm)
#line(length: 100%, stroke: 3pt + rule-grey)
#v(3mm)

// A footer strip, not a block: one line per guardrail. Anything that needs a
// paragraph belongs in the notebooks, which are a QR code away.
#columns(3, gutter: 16mm)[

#text(size: 18pt, weight: "bold", fill: ink)[Methodological guardrails]
#v(1mm)
#text(size: 14pt)[
- *Public feeds only; the census is built, not downloaded.* Elexon labels no unit
  a battery, so sites are found by symmetry — the rule admits
  #n6.curated_recovered of #n6.curated_bmus hand-researched BM Units unaided.
- *State of charge is inferred, not metered* — re-anchoring moves levels about
  ten points, not the ordering. Duration is declared for a third of the census.
- *Rare samples are exhibits, never blended* — CMN (#metric[n=#n5.n_cmn]) and
  DRM < 1 GW (#metric[n=#n5.n_drm]) carry their counts.
- *Every figure is a strict lower bound.* Perfect foresight, unpriced social
  value and uncosted duration all push the gap down, not up.
]

#colbreak()

#text(size: 18pt, weight: "bold", fill: ink)[Robustness]
#v(1mm)
#text(size: 14pt)[
- *Four definitions, one severe winter.* On 2019–20 (margin to
  #metric[#n4.winter_drm]) the gap lands in #metric[#n4.winter_gap_range] across
  definitions — the summer's #n4.forgone_pct sits inside it.
- *Where the load line is drawn barely matters* — top 5%, 10% and 15% give
  #metric[#n4.thresh_gap_range].
- *Cost model against calendar.* Resampling gives #metric[#n4.resample_range];
  sweeping cost models gives #n4.cost_model_range. The sample moves it more than
  the assumptions do.
]

#colbreak()

#text(size: 18pt, weight: "bold", fill: ink)[Sources & code]
#v(1mm)
#text(size: 14pt)[
*Elexon* BMRS / Insights 2018–2026 · *NESO Data Portal* — Capacity Market
register and notices, TEC and Embedded registers, per-unit auction results ·
*PV_Live* · *ENTSO-E* · *Nord Pool N2EX* · *operator disclosures*, each carrying
its source and read date. Policy: *Ofgem* LDES window 1, *EMRS*, *Terna* MACSE,
*CRE* TURPE 7, *BNetzA*.
]

#v(1.5mm)
#align(center)[
  #image(FIG + "repo_qr.svg", width: 9%)
]

]
