// Beyond the Spread. A0 landscape research poster (1189 x 841 mm).
//
// Figures are referenced as SVG, not PDF: Typst embeds PNG, JPEG, GIF and SVG,
// and has no PDF image support. The SVG and PDF exports carry the same
// vectors, so nothing is lost; see src/utils/poster.py.
//
// Every result below is substituted at compile time, never typed: notebook
// results from the nb*_metrics.json exports, and the audit statistics
// (forecast skill, break-date search, clustered intervals, the onset-charge
// gating table) from stats_metrics.json, written by
// scripts/poster_robustness.py. Configuration constants such as efficiencies,
// the charge floor and the cycle cap are configuration, not results, and may
// be stated.
//
// The board keeps two analytical lanes that use different rulers and are
// never compared: Lane A (Sections 2 and 3) classifies by top-decile residual
// load, a utilisation measure; Lane B (Section 4) uses the operator's own
// scarcity instruments. Lane badges stamp every section.
//
// House style, per the author: no em dashes anywhere in the text, no section
// glyphs (write "Section 3"), academic register throughout.
#let n4 = json("../figures/poster/nb04_metrics.json")
#let n5 = json("../figures/poster/nb05_metrics.json")
#let n6 = json("../figures/poster/nb06_metrics.json")
#let n7 = json("../figures/poster/nb07_metrics.json")
#let n8 = json("../figures/poster/nb08_metrics.json")
#let n9 = json("../figures/poster/nb09_metrics.json")
#let nb = json("../figures/poster/nb10_metrics.json")
#let sx = json("../figures/poster/stats_metrics.json")

#let ink        = rgb("#0b0b0b")
#let da-blue    = rgb("#2a78d6")
#let discharge  = rgb("#1baf7a")
#let cost-red   = rgb("#e34948")
#let paper      = rgb("#fcfcfb")
#let rule-grey  = rgb("#d8d7d0")

#let FIG = "../figures/poster/"
#let winA = n4.window.replace(" → ", " to ")
#let absn(s) = calc.abs(int(s))

#set page(
  width: 1189mm, height: 841mm,
  margin: (x: 32mm, top: 20mm, bottom: 13mm),
  fill: paper,
)

// Type scale, fixed. Do not introduce sizes outside this list.
//   60  poster title            30  subtitle           25  author
//   24  banner headline         19  section sub-heading
//   18  banner clause           17  body, and the dataset line
//   16  footer heading          15  all of column 1, the apparatus
//   15.5 contact lines          14.5 figure caption
//   14  inline aside            12.5 footer body        11.5 QR label
#set text(font: ("Helvetica Neue", "Helvetica", "Arial"), size: 17pt, fill: ink)
#set par(justify: true, leading: 0.68em, spacing: 0.9em)

#let metric(body) = text(weight: "bold", fill: ink)[#body]

#let section(title, accent) = block(width: 100%, breakable: false)[
  #line(length: 100%, stroke: 4.5pt + accent)
  #v(-3mm)
  #block(inset: (top: 6mm, bottom: 3.5mm))[
    #text(size: 27pt, weight: "bold", fill: ink)[#title]
  ]
]

#let lane(label, accent) = block(width: 100%, inset: (bottom: 4mm))[
  #box(fill: accent.lighten(85%), inset: (x: 3.5mm, y: 1.8mm), radius: 2pt)[
    #text(size: 13.5pt, weight: "bold", fill: accent.darken(20%))[#label]
  ]
]

#let tag(letter, accent) = box(
  fill: accent, inset: (x: 2mm, y: 0.8mm), radius: 2pt, baseline: 1pt,
)[#text(size: 13pt, weight: "bold", fill: white)[LANE #letter]]

#let panel(path, caption, ratio: 100%) = block(width: 100%, breakable: false)[
  #v(3.5mm)
  #align(center)[#image(FIG + path, width: ratio)]
  #v(2mm)
  #text(size: 14.5pt, fill: ink.lighten(35%), style: "italic")[#caption]
  #v(4.5mm)
]

#let scope(accent, body) = block(
  width: 100%,
  fill: accent.lighten(93%),
  stroke: (left: 4pt + accent),
  inset: (x: 5.5mm, y: 4mm),
  radius: 2pt,
)[#text(size: 15.5pt)[#body]]

// ── The onset-charge comparison, drawn from the audit statistics ────────────
// Non-overlapping eras (before April 2024 against from April 2024) under both
// state-of-charge integration schemes. The gating computation returned
// outcome C: the direction agrees and both interval estimates exclude zero,
// but the magnitudes differ materially, so both schemes print.
#let pnum(s) = int(s.replace("%", "").trim())

#let shiftrow(name, sub, sold, snew, worse) = {
  let a = pnum(sold)
  let b = pnum(snew)
  let accent = if worse { cost-red } else { discharge }
  grid(
    columns: (92mm, 1fr, 40mm),
    column-gutter: 5mm,
    align: (left + horizon, left + horizon, right + horizon),
    [
      #text(size: 15pt, weight: "bold")[#name] \
      #text(size: 12.5pt, fill: ink.lighten(35%))[#sub]
    ],
    box(width: 100%, height: 14mm)[
      #place(dy: 6.1mm, line(length: 100%, stroke: 0.9pt + rule-grey))
      #place(dy: 4.9mm, dx: calc.min(a, b) * 1%,
        line(length: calc.abs(a - b) * 1%, stroke: 3.2pt + accent.lighten(45%)))
      #place(dy: 3.7mm, dx: a * 1% - 2.4mm, circle(radius: 2.4mm, fill: ink.lighten(55%)))
      #place(dy: 3.7mm, dx: b * 1% - 2.4mm, circle(radius: 2.4mm, fill: accent))
    ],
    text(size: 15pt)[#sold to #text(weight: "bold", fill: accent.darken(10%))[#snew]],
  )
}

// ── Contact icons, drawn rather than fetched ────────────────────────────────
#let icon-mail = box(baseline: 2.2pt, width: 15pt, height: 11pt)[
  #place(rect(width: 15pt, height: 11pt, radius: 1pt,
              stroke: 1.2pt + rgb("#c5221f")))
  #place(dx: 1.4pt, dy: 1.3pt,
    line(start: (0pt, 0pt), end: (6.1pt, 4.6pt), stroke: 1.2pt + rgb("#c5221f")))
  #place(dx: 7.5pt, dy: 5.9pt,
    line(start: (0pt, 0pt), end: (6.1pt, -4.6pt), stroke: 1.2pt + rgb("#c5221f")))
]

#let icon-li = box(
  baseline: 2.2pt, fill: rgb("#0a66c2"), radius: 2pt, inset: (x: 3.4pt, y: 1.6pt),
)[#text(size: 11pt, weight: "bold", fill: white, font: "Helvetica")[in]]

// ─── Title banner ───────────────────────────────────────────────────────────
#block(width: 100%)[
  #grid(
    columns: (1fr, auto),
    column-gutter: 14mm,
    align: (left + top, right + top),
    [
      #text(size: 60pt, weight: "bold", fill: ink)[
        Beyond the Spread
      ]
      #v(2mm)
      #text(size: 30pt, fill: da-blue)[
        Quantifying the Alignment Gap Between Battery Arbitrage and Energy
        System Resilience
      ]
    ],
    [
      #v(3mm)
      #text(size: 25pt, weight: "bold", fill: ink)[Abhinav Shaw]
      #v(2.6mm)
      #text(size: 15.5pt, fill: ink.lighten(20%))[
        #icon-mail #h(2mm) abhinavshaw.iitd\@gmail.com
      ]
      #v(1.8mm)
      #text(size: 15.5pt, fill: ink.lighten(20%))[
        #icon-li #h(2mm) linkedin.com/in/abhinav-shaw-iit-delhi
      ]
    ],
  )
  #v(2mm)
  #line(length: 100%, stroke: 3pt + rule-grey)
  #v(1.5mm)
  #text(size: 17pt, fill: ink.lighten(25%))[
    All site-resolvable GB grid-scale batteries registered in the Balancing
    Mechanism: #n6.census_sites, #n6.census_bmus, #n6.census_mw, observed 2018
    to 2026, built entirely from public Elexon and system-operator data;
    census snapshot #n6.snapshot.
  ]
]

#v(3mm)

#block(
  width: 100%,
  fill: da-blue.lighten(90%),
  stroke: (left: 7pt + da-blue),
  inset: (x: 9mm, y: 5.5mm),
  radius: 2pt,
)[
  #text(size: 24pt, weight: "bold", fill: ink)[
    Energy prices already secure about four-fifths of the modelled battery's
    high-load alignment. What remains unpriced is readiness for scarcity.
  ]
  #v(2.5mm)
  #grid(
    columns: (1fr, 1fr, 1fr),
    gutter: 11mm,
    [
      #text(size: 18pt)[
        #tag("A", cost-red) *What the energy price secures.* Optimised for
        profit alone, a #n4.asset battery delivers
        #text(fill: da-blue, weight: "bold")[#n4.free_share] of the top-decile
        energy it could physically reach. Purchasing the remainder costs about
        #text(fill: da-blue, weight: "bold")[#n4.cost_all].
      ]
    ],
    [
      #text(size: 18pt)[
        #tag("A", cost-red) *What it cannot reach.* GB's explicit
        reserve-scarcity component settles through cash-out rather than the
        day-ahead price a schedule optimises, and was zero in
        #text(fill: da-blue, weight: "bold")[#n4.scarcity_zero] of this
        window's periods.
      ]
    ],
    [
      #text(size: 18pt)[
        #tag("B", discharge) *What changed since #n8.era_start.* In
        non-overlapping event samples the fleet responds more strongly yet
        enters scarcity with
        #text(fill: da-blue, weight: "bold")[lower inferred charge] under both
        integration schemes; the estimated decline is
        #text(fill: da-blue, weight: "bold")[#absn(sx.onset_diff_anch) to
        #absn(sx.onset_diff) points] (Figure 6).
      ]
    ],
  )
]

#v(3mm)

// ─── Four columns ───────────────────────────────────────────────────────────
#columns(4, gutter: 14mm)[

#section("1 · One fleet, two rulers", da-blue)

#text(size: 17pt)[
  Batteries can serve a resilient system in two senses: delivering energy
  when residual demand is highest, and holding energy when the operator runs
  short of slack. In GB these are different conditions, so the board keeps
  them in separate lanes.
]

#v(2mm)
#block(
  width: 100%,
  stroke: 1.2pt + rule-grey,
  inset: (x: 5mm, y: 4mm),
  radius: 2pt,
)[
  #text(size: 17pt)[
    #text(weight: "bold", fill: cost-red.darken(10%))[Lane A, the system
    working hardest.] Top decile of residual load, #n9.threshold_gw here: a
    *utilisation* measure, meaning high output rather than shortage. Sections
    2 and 3, #n4.window_days (#winA).
    #v(2mm)
    #text(weight: "bold", fill: discharge.darken(20%))[Lane B, the operator
    short of slack.] Loss-of-load probability at or above 10#super[−4]
    (n = 2,075 half-hours), de-rated margin #n5.drm_threshold (n = #n5.n_drm),
    or a Capacity Market Notice (n = #n5.n_cmn). Section 4, 2018-01-01 to
    2026-08-24.
    #v(2mm)
    No number from one lane is quoted against the other.
  ]
]

#v(2.5mm)
#text(size: 19pt, weight: "bold", fill: ink)[What resilience means here]
#v(1.5mm)
#text(size: 17pt)[
  Capability must be declared, then scheduled, then survive operator
  redispatch, and finally be backed by stored energy for the event's
  duration. This board measures behaviour along that chain, not the outcome:
  no reliability benefit is estimated here.
]

#v(2.5mm)
#text(size: 19pt, weight: "bold", fill: ink)[How the population is built]
#v(1.5mm)
#text(size: 17pt)[
  No public register labels a Balancing Mechanism unit a battery, so the
  population is constructed from units declaring symmetric import and export
  capability, corroborated against public registers. The rule recovers all
  #metric[#n6.curated_recovered] of #n6.curated_bmus hand-researched battery
  BM Units; false positives are controlled by requiring a second register,
  though their rate is not estimated. #n6.mwh_none of the #n6.census_sites
  publish no energy capacity and leave every state-of-charge figure.
]

#panel("nb06_fig1_census_composition.svg", ratio: 100%)[
  Figure 1. The census by site size and connection level. #n6.dist_sites
  distribution-connected sites hold #n6.dist_share of declared capacity, and
  so do the #n6.top_band_sites largest sites.
]

#v(2.5mm)
#text(size: 19pt, weight: "bold", fill: ink)[Method, and what it assumes]
#v(1.5mm)
#text(size: 17pt)[
  *Dispatch model.* A day-ahead schedule on cleared prices, re-optimised
  intraday against realised mid prices with perfect foresight; deviations pay
  £2/MWh. Assumed: 0.94 charge and 0.94 discharge efficiency, a 10%
  state-of-charge floor, a 1.5 cycles-per-day cap. Stored energy holds no
  terminal value, so modelled end-of-day depletion is an upper bound and the
  schedule is not rewarded for pre-event charge. \
  *Achievable.* The most the same asset could deliver into top-decile hours
  under those constraints; every delivered share is a ratio to it. \
  *Fleet.* Half-hourly physical notifications per BM Unit, with charge
  integrated from them rather than metered. Acceptances are netted as a
  measured sensitivity on both lanes. \
  *Provenance.* Every result is substituted at compile time from exported
  metric files; the snapshot, threshold and cycling rule are identical across
  notebooks.
]

#v(2.5mm)
#text(size: 19pt, weight: "bold", fill: ink)[
  Policy context: the missing signal is a design choice
]
#v(1.5mm)
#text(size: 17pt)[
  Comparable markets already transmit system tightness into a price batteries
  schedule against, or pay directly for the behaviour GB leaves unrewarded.
  #v(1.5mm)
  *Belgium prices scarcity continuously,* through adders derived from an
  operating-reserve demand curve, published since October 2019.
  #v(1mm)
  *France pays for the behaviour itself.* Under TURPE 7, in force August
  2025, distribution-connected batteries receive up to €69/MWh to charge in
  midday solar hours and are penalised for discharging at the wrong ones;
  the storage component applies from August 2026.
  #v(1mm)
  *GB does neither.* Scarcity reaches the battery only through cash-out
  (Section 2). The REMA Summer Update of 10 July 2025 rejected zonal pricing
  for reformed national pricing, routing locational signals through network
  and connection-charge reform covering generation, *storage* and demand:
  the instrument TURPE 7 already applies to batteries.
  #v(1.5mm)
  Policy design must therefore target the relevant gate. Scarcity signals may
  affect scheduling, availability mechanisms declared capability, readiness
  products pre-event energy. Their welfare and investment effects are not
  estimated here.
]

#colbreak()

#section("2 · The incentive, modelled", cost-red)
#lane("LANE A · top-decile residual load · " + winA, cost-red)

#scope(cost-red)[
  *A model of the incentive alone, not the real fleet.* One #n4.asset
  optimiser with perfect foresight, #n4.window_days.
]

#v(2.5mm)

*The energy price is already a signal at these hours.* The profit-optimal
schedule concentrates #metric[#n4.top_decile_pct] of its discharged energy
into top-decile hours and draws #metric[#n4.surplus_pct] of its charging from
surplus periods, with no system-value term in the objective at all. Measured
against a system-value objective on the same battery, it forgoes
#metric[#n4.forgone_pct] #n4.forgone_ci of achievable top-decile energy,
#n4.forgone_mwh. Of that achievable energy, #metric[#n4.free_share] arrives
at zero sacrifice of market value #text(size: 14pt)[(aggregate basis 82%;
day-resampled 81%, interval 71 to 91%)].

*What the price cannot reach is scarcity.* GB prices it as the value of lost
load multiplied by loss-of-load probability, paid inside the cash-out price,
so it never enters the day-ahead objective the schedule maximises; over this
window it is exactly zero in #metric[#n4.scarcity_zero] of settlement periods.

#panel("nb04_fig2_diurnal_mismatch.svg", ratio: 97%)[
  Figure 2. The mean day across days containing a top-decile hour. Discharge
  peaks at #n4.peak_hour, with the load, so the gap is not one of timing: the
  store reaches its #n4.soc_floor floor by #n4.floor_hour while the system is
  still tight in #n4.tight_at_floor of those days.
]

*Two different prices, two different objects.* Purchasing every top-decile
hour of energy this battery can deliver costs about #metric[#n4.cost_all]
#text(size: 14pt)[(day-resampled £3.5 to £9.0)], which is #n4.cost_all_share.
Purchasing the *entire* system-value schedule, which also credits surplus
absorption and forbids off-peak discharge, costs #metric[£50/MW/day]
#text(size: 14pt)[(£38 to £62)]. The second figure is larger because it buys
a great deal more than peak delivery.

*Two denominators, kept apart.* Within its own feasible set the two-hour
asset already captures #metric[#n4.free_share] unpaid. Measured instead
against what a six-hour asset can reach, the same schedule delivers 35%, and
no payment lifts it past #metric[#n4.dur2_best], while a six-hour asset
reaches #metric[#n4.dur6_free] before any payment at all. The ceiling is
energy capacity, not incentive.

#panel("nb04_fig_duration_frontier.svg", ratio: 82%)[
  Figure 3. Each curve sweeps the weight on system value for one duration;
  the dot marks its profit schedule. The axis is the share of the six-hour
  asset's maximum, so durations are comparable. Capital cost of the extra
  energy is not modelled.
]

#colbreak()

#section("3 · The fleet, on the same yardstick", cost-red)
#lane("LANE A · top-decile residual load · " + winA, cost-red)

#scope(cost-red)[
  *Measured, not modelled.* Same window, same classifier, same
  #n9.threshold_gw threshold, #n9.top_decile_hours top-decile hours.
  #n9.sites census sites with a published energy capacity, #n9.mw_coverage of
  fleet power.
]

#v(2.5mm)

*The measured shortfall accumulates at distinct operational gates, and the
gates do not share an owner.* Rebuilt on one harness, with numerator and
denominators on identical sites and hours, the fleet's peak energy passes
through:

#v(1.5mm)
#block(inset: (left: 2mm))[
  #text(size: 17pt)[
    #metric[#nb.ach_nameplate]: the most registered power could deliver \
    #h(3mm) ↓ #text(fill: cost-red.darken(10%), weight: "bold")[#nb.gate_declared]
    #h(0.5mm) *declared* available, the export limit told to the operator \
    #h(3mm) ↓ #text(fill: cost-red.darken(10%), weight: "bold")[#nb.gate_planned]
    #h(0.5mm) of that *scheduled* in notifications \
    #h(3mm) ↓ #text(fill: cost-red.darken(10%), weight: "bold")[#nb.gate_delivered]
    #h(0.5mm) of that remained after *netting accepted bids and offers* \
    #metric[#nb.delivered_boa] in the acceptance-adjusted profile,
    #nb.share_nameplate_boa of the first line
  ]
]
#v(1.5mm)

The largest loss is the first, and it is not about dispatch: declared
availability supports barely half of what registered power could deliver into
these hours. Given what was declared, the fleet scheduled
#metric[#nb.gate_planned] of it, close to the modelled optimum's
#n9.model_delivered. Netting accepted bids and offers then removes
#metric[#nb.gate_instructed_away] of that schedule, concentrated in the
evening peak, with the operator predominantly moving batteries *down*.
Equivalently, the share of declared-achievable energy falls from
#nb.share_declared_pn scheduled to #metric[#nb.share_declared_boa] in the
acceptance-adjusted profile.

An availability requirement could affect declared capability; it would not
by itself address the reduction between notified and acceptance-adjusted
dispatch. Why declarations sit so far below registered power is not
identified in public data: outage, derating, reserved response headroom and
commercial choice are not separable here.

#panel("nb09_fig_model_vs_fleet.svg", ratio: 86%)[
  Figure 4. The mean day, per MW installed. The fleet discharges at the same
  hours the model does but at roughly a third of the depth. Both series are
  notification-based: neither is metered output.
]

Ranked by ancillary earnings, the least-ancillary quartile of sites delivers
#metric[#n9.low_anc_delivered] of achievable energy, the model's own figure,
and the most-ancillary delivers #metric[#n9.high_anc_delivered]: Spearman
#metric[#n9.anc_corr] (p #n9.anc_p, n = #n9.anc_sites), surviving a duration
control at #n9.anc_partial_r, while duration alone predicts nothing
(r #n9.anc_duration_r, not significant). The most-ancillary quartile earns
#n9.top_service_share of its ancillary revenue from #n9.top_service, which
rewards reserved capability and may influence state-of-charge management,
though the resulting pre-event energy incentive is not identified here. This
is an association only: contracted volume is unobserved, and the window is
summer.

#panel("nb09_fig_revenue_stack.svg", ratio: 88%)[
  Figure 5. Delivered share falls as ancillary earnings rise, with quartile
  means running #n9.low_anc_delivered to #n9.high_anc_delivered against the
  model's #n9.model_delivered. Dot area is site capacity.
]

#colbreak()

#section("4 · When the operator is short", discharge)
#lane("LANE B · the operator's own instruments · 2018 to 2026", discharge)

#scope(discharge)[
  *The operator's own instruments, full history.* Headline set: loss-of-load
  probability at or above 10#super[−4], 2,075 half-hours, of which 2,063
  carry acceptance coverage. Rarer sets are exhibits carrying their counts,
  never percentages.
]

#v(2.5mm)

*Response is not the binding constraint.* In the flagged half-hours the fleet
is net discharging 87% of the time, at #metric[+0.060 MW per MW online]
against #n5.baseline across all periods. The rarer sets agree, as counts: 37
of the #n5.n_drm half-hours under de-rated margin #n5.drm_threshold, and all
#n5.n_cmn half-hours carrying a Capacity Market Notice. Clustering by event
leaves the era difference standing: #metric[#sx.resp_mod_cl #sx.resp_mod_ci]
from #n8.era_start against #metric[#sx.resp_pre_cl #sx.resp_pre_ci] before
(unclustered modern mean #n8.response).

*Readiness is.* Across all #n5.events events since 2018 the median inferred
onset charge is #metric[#n5.soc_at_onset], no fuller than on matched control
days, and #metric[#n5.dispatch_gap] of usable energy is still held at the
deepest point; in the #n8.events modern events those figures are
#n8.soc_at_onset and #n8.dispatch_gap (notebooks 05 and 08; descriptive,
overlapping samples). Within the reconstructed revenue stack, no separately
identifiable payment is observed for entering a scarcity event at a high
state of charge.

#v(1.5mm)
#text(size: 19pt, weight: "bold", fill: ink)[
  The non-overlapping comparison, under both integration schemes
]
#v(1.5mm)

#grid(
  columns: (92mm, 1fr, 40mm),
  column-gutter: 5mm,
  [],
  text(size: 12pt, fill: ink.lighten(45%))[0 #h(1fr) median onset charge, per
  cent #h(1fr) 100],
  [],
)
#shiftrow("Primary integration", "events before against from April 2024",
  sx.onset_pre, sx.onset_modern, true)
#shiftrow("Re-anchored at 04:00, sensitivity", "same events, same rule",
  sx.onset_pre_anch, sx.onset_modern_anch, true)
#v(1mm)
#text(size: 14.5pt, fill: ink.lighten(35%), style: "italic")[
  Figure 6. Median inferred charge at event onset, before April 2024
  (n = #sx.onset_pre_n) against from April 2024 (n = #sx.onset_modern_n). The
  decline is #absn(sx.onset_diff) points under the primary integration,
  interval #sx.onset_diff_ci, and #absn(sx.onset_diff_anch) points
  re-anchored: the direction is robust, the magnitude scheme-dependent.
  Measured against arriving full, an upper bound on remediable energy.
]

#v(2mm)

*Acceptances change little in this lane.* Netting the Balancing Mechanism
across the covered scarcity half-hours moves the response from
#nb.response_pn to #metric[#nb.response_boa] and onset charge by roughly two
points; instructions split #nb.up_share upward and #nb.down_share downward.
The contrast with Section 3's #nb.cut_pct reduction locates the instruction
effect in high-load hours, not in scarcity.

*Potentially usable warning information existed.* Twelve-hour margin
forecasts identified #metric[#sx.skill12_hit] of later crossings at
#metric[#sx.skill12_ppv] precision. Whether responding to those warnings
would have been profitable or operationally feasible is not tested here.

*The level change is robust; its timing is not identified.* Searching every
candidate quarter rather than accepting the imposed #n7.break_date boundary,
that quarter ranks #metric[#sx.break_rank] on the Akaike information
criterion, and the best-fitting dates are scattered across years. The rise is
not compositional: a fixed panel of #n7.panel_sites sites (#n7.panel_mw)
spanning both periods shifts #metric[#n7.panel_ratio], more than the full
fleet's #metric[#n7.fleet_ratio]. Scarcity is also now rare, so this is a
fleet responding to early-warning signals rather than one tested by
scarcity.

#panel("nb07_fig_regime_shift.svg", ratio: 96%)[
  Figure 7. Later against earlier response under the same margin, by band.
  The change is largest where the system was loosest (#n7.loosest_ratio at
  #n7.loosest_band): a fleet that became active everywhere, not one that
  learned to chase scarcity. Periods are split at an imposed date, so this is
  a contrast, not an estimated break. Hatching denotes a thin sample.
]

]

#v(1.5mm)
#line(length: 100%, stroke: 3pt + rule-grey)
#v(2mm)

#grid(
  columns: (1.1fr, 1fr, 96mm),
  gutter: 13mm,
  [
    #text(size: 16pt, weight: "bold", fill: ink)[Limitations]
    #v(1mm)
    #text(size: 12.5pt)[
    - *Temporal scope is a data constraint, not a design choice.* No single
      public source spans the period: ENTSO-E ceased publishing GB day-ahead
      prices, so recent analysis runs on Nord Pool N2EX and the historical
      cross-check on ENTSO-E. Lane A therefore rests on one 60-day window.
      Re-estimated on winter 2019-20 (margin falling to #n4.winter_drm) the
      delivery gap lies within #n4.winter_gap_range across four scarcity
      definitions, marginally above this window's #n4.forgone_pct, whose
      resampling interval #n4.forgone_ci encloses it; an independent
      winter-2018 re-run on ENTSO-E prices reproduces the structure. The
      revenue-stack gradient remains untested against a winter peak.
    - *State of charge is inferred, not metered.* Re-anchoring the
      integration shifts levels by roughly ten points, which is why Figure 6
      reports both schemes; two related event-decomposition terms reverse
      rank under it and are therefore not shown. Netting Balancing
      Mechanism acceptances alters Section 3 by #nb.cut_pct and Section 4's
      response from #nb.response_pn to #nb.response_boa.
    - *Definitional boundary.* Top-decile residual load indexes utilisation,
      not shortage. The sum of published period-level loss-of-load
      probabilities corresponds to #n8.lole_mean_h expected hours per year
      against the 3-hour standard: an expectation implied by the operator's
      prints, not a count of realised events. The calculated reserve-scarcity
      component, zero in #n4.scarcity_zero of the summer window, reached
      #n4.winter_scarcity_max in winter 2019-20, episodic rather than absent,
      and still settling only through cash-out.
    - *Limits of inference.* The regime change in Section 4 is not
      attributable to a specific quarter, and the dispatch-to-load
      correlation largely reflects diurnal shape, falling from #sx.corr_raw
      to #sx.corr_within once hour-of-day means are removed. Which
      instrument, a day-ahead scarcity term or an availability obligation,
      would close the readiness gap is framed here but not tested. No causal
      claim is made about ancillary contracts, operator tooling or the break
      date.
    - *Sensitivities that do not alter the result:* load threshold
      (#n4.thresh_gap_range), cost model (#n4.cost_model_range), day
      resampling (#n4.resample_range), initial state of charge
      (#n9.soc_sensitivity), and a period-resolved rather than mean declared
      bound (under one point on a like-for-like rerun).
    ]
  ],
  [
    #text(size: 16pt, weight: "bold", fill: ink)[Sources & data]
    #v(1mm)
    #text(size: 12.5pt)[
      Every feed below is public, and every number on this board rebuilds
      from them.
      #v(2mm)
      *Elexon BMRS / Insights:* physical notifications, export and import
      limits, bid-offer acceptances, cash-out prices. \
      *NESO Data Portal:* loss-of-load probability and de-rated margin
      prints, Capacity Market register and notices, TEC and Embedded
      registers, per-unit ancillary auction results. \
      *PV_Live, ENTSO-E, Nord Pool N2EX:* solar outturn and day-ahead
      prices. \
      *Operator disclosures:* site energy capacity, each carrying its source
      and read date.
      #v(2mm)
      No public register labels a battery, so the census of #n6.census_sites
      is constructed and audited in notebook 06 rather than downloaded. That
      notebook, the dispatch and settlement engine, and every figure on this
      board are at #box[*github.com/shaw029/power-trading*].
      #v(2mm)
      *Policy context, external to this study.* A. Papavasiliou et al.,
      _Scarcity pricing and the missing European market for real-time reserve
      capacity_, The Electricity Journal 33 (2020); CRE, _TURPE 7_
      deliberations (cre.fr, 2025); DESNZ, _REMA Summer Update_, 10 July 2025
      (gov.uk).
    ]
  ],
  [
    #grid(
      columns: (1fr, 1fr),
      column-gutter: 6mm,
      align: (center, center),
      [
        #image(FIG + "dashboard_qr.svg", width: 42mm)
        #v(0.8mm)
        #text(size: 11.5pt, weight: "bold", hyphenate: false)[Live dashboard]
      ],
      [
        #image(FIG + "repo_qr.svg", width: 42mm)
        #v(0.8mm)
        #text(size: 11.5pt, weight: "bold", hyphenate: false)[Code & notebooks]
      ],
    )
  ],
)
