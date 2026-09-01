// Beyond the Spread. A0 landscape (1189 x 841 mm).
//
// A poster session gives five seconds walking past, sixty seconds if the reader
// stops, and after that the author is the medium. So the board is built in three
// reading tiers rather than two. Every finding opens with a bold statement line
// that stands on its own, and the supporting prose beneath it is two or three
// lines. A reader who takes only the bold lines leaves with the whole argument;
// a judge who reads everything still finds the caveats. Material that exists to
// defend rather than to inform moves behind the QR.
//
// Every number is read from assets/, written by the notebook that computes it.
// Nothing on the board is typed by hand.
//
// House style: no em dashes, no section glyphs, academic register.
#let n4 = json("assets/nb04_metrics.json")
#let n5 = json("assets/nb05_metrics.json")
#let n6 = json("assets/nb06_metrics.json")
#let n7 = json("assets/nb07_metrics.json")
#let n8 = json("assets/nb08_metrics.json")
#let n9 = json("assets/nb09_metrics.json")
#let nb = json("assets/nb10_metrics.json")
#let sx = json("assets/stats_metrics.json")

#let ink        = rgb("#0b0b0b")
#let da-blue    = rgb("#2a78d6")
#let discharge  = rgb("#1baf7a")
#let cost-red   = rgb("#e34948")
#let paper      = rgb("#fcfcfb")
#let rule-grey  = rgb("#d8d7d0")

#let FIG = "assets/"
#let winA = n4.window.replace(" → ", " to ")
#let absn(s) = calc.abs(int(s))

#set page(
  width: 1189mm, height: 841mm,
  margin: (x: 32mm, top: 19mm, bottom: 11mm),
  fill: paper,
)

// Type ramp, raised one point throughout so every relationship holds:
// 60 title, 30 subtitle, 25 author, 26 banner, 23 finding lead, 28 section,
// 19.5 body, 18 supporting block, 17 caption, 15.5 footer.
#set text(font: ("Helvetica Neue", "Helvetica", "Arial"), size: 19.5pt, fill: ink)
#set par(justify: true, leading: 0.72em, spacing: 1.0em)

#let metric(body) = text(weight: "bold", fill: ink)[#body]

#let section(title, accent) = block(width: 100%, breakable: false)[
  #line(length: 100%, stroke: 5pt + accent)
  #v(-3mm)
  #block(inset: (top: 6mm, bottom: 2mm))[
    #text(size: 28pt, weight: "bold", fill: ink)[#title]
  ]
]

// The middle reading tier. A reader who takes only these lines, in order,
// gets the argument without reading a paragraph.
#let lead(body) = block(width: 100%, breakable: false, inset: (top: 3.5mm, bottom: 1.2mm))[
  #text(size: 23pt, weight: "bold", fill: ink)[#body]
]

#let basis(label, accent) = block(width: 100%, inset: (bottom: 3mm))[
  #box(fill: accent.lighten(85%), inset: (x: 3.5mm, y: 1.8mm), radius: 2pt)[
    #text(size: 15pt, weight: "bold", fill: accent.darken(20%))[#label]
  ]
]

#let tag(basis, accent) = box(
  fill: accent, inset: (x: 2mm, y: 0.8mm), radius: 2pt, baseline: 1pt,
)[#text(size: 13pt, weight: "bold", fill: white)[#upper(basis)]]

#let panel(path, caption, ratio: 100%) = block(width: 100%, breakable: false)[
  #v(2.5mm)
  #align(center)[#image(FIG + path, width: ratio)]
  #v(1.8mm)
  #text(size: 17pt, fill: ink.lighten(35%), style: "italic")[#caption]
  #v(3mm)
]

#let pnum(s) = int(s.replace("%", "").trim())

#let shiftrow(name, sub, sold, snew) = {
  grid(
    columns: (78mm, 1fr, 40mm),
    column-gutter: 5mm,
    align: (left + horizon, left + horizon, right + horizon),
    [
      #text(size: 16pt, weight: "bold")[#name] \
      #text(size: 13pt, fill: ink.lighten(35%))[#sub]
    ],
    box(width: 100%, height: 13mm)[
      #place(dy: 6.2mm, line(length: 100%, stroke: 0.9pt + rule-grey))
      #place(dy: 4.9mm, dx: calc.min(pnum(sold), pnum(snew)) * 1%,
        line(length: calc.abs(pnum(sold) - pnum(snew)) * 1%,
             stroke: 3.8pt + cost-red.lighten(45%)))
      #place(dy: 3.5mm, dx: pnum(sold) * 1% - 2.9mm,
        circle(radius: 2.9mm, fill: ink.lighten(55%)))
      #place(dy: 3.5mm, dx: pnum(snew) * 1% - 2.9mm,
        circle(radius: 2.9mm, fill: cost-red))
    ],
    text(size: 16pt)[#sold to #text(weight: "bold", fill: cost-red.darken(10%))[#snew]],
  )
}

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

// ─── Title ──────────────────────────────────────────────────────────────────
#block(width: 100%)[
  #grid(
    columns: (1fr, auto),
    column-gutter: 14mm,
    align: (left + top, right + top),
    [
      #text(size: 60pt, weight: "bold", fill: ink)[Beyond the Spread]
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
    All site-resolvable GB grid-scale batteries in the Balancing Mechanism:
    #n6.census_sites, #n6.census_mw, observed 2018 to 2026 from public Elexon
    and system-operator data.
  ]
]

#v(3mm)

#block(
  width: 100%,
  fill: da-blue.lighten(90%),
  stroke: (left: 7pt + da-blue),
  inset: (x: 9mm, y: 6mm),
  radius: 2pt,
)[
  #text(size: 26pt, weight: "bold", fill: ink)[
    Energy prices deliver #n4.free_share of the modelled battery's high-load
    alignment. Readiness for scarcity is not priced.
  ]
  #v(3mm)
  #grid(
    columns: (1fr, 1fr, 1fr),
    gutter: 11mm,
    [#text(size: 18pt)[
      #tag("utilisation", cost-red) A profit-optimised #n4.asset battery delivers
      #text(fill: da-blue, weight: "bold")[#n4.free_share] of the top-decile
      energy it could reach. The remainder costs
      #text(fill: da-blue, weight: "bold")[#n4.cost_all].
    ]],
    [#text(size: 18pt)[
      #tag("utilisation", cost-red) GB's reserve-scarcity component settles through
      cash-out, not the day-ahead price a schedule optimises, and was zero in
      #text(fill: da-blue, weight: "bold")[#n4.scarcity_zero] of this window.
    ]],
    [#text(size: 18pt)[
      #tag("scarcity", discharge) Since #n8.era_start the fleet responds more
      strongly yet enters scarcity with
      #text(fill: da-blue, weight: "bold")[lower charge], by
      #text(fill: da-blue, weight: "bold")[#absn(sx.onset_diff_anch) to
      #absn(sx.onset_diff) points] under two integration schemes.
    ]],
  )
]

#v(3mm)

#columns(4, gutter: 14mm)[

#section("1 · Population and measurement basis", da-blue)

#block(
  width: 100%,
  stroke: 1.2pt + rule-grey,
  inset: (x: 5mm, y: 4mm),
  radius: 2pt,
)[
  #text(size: 18pt)[
    #text(weight: "bold", fill: cost-red.darken(10%))[Utilisation: the system
    working hardest.] Top decile of residual load, #n9.threshold_gw.
    A utilisation measure, not shortage. Sections 2 and 3, #n4.window_days.
    #v(2mm)
    #text(weight: "bold", fill: discharge.darken(20%))[Scarcity: the operator
    short of slack.] Loss-of-load probability at or above 10⁻⁴, 2,075
    half-hours, with de-rated margin below 1 GW (n = #n5.n_drm) and Capacity
    Market Notices (n = #n5.n_cmn) as rarer exhibits. Section 4, 2018 to 2026.
    #v(2mm)
    No number from one basis is quoted against the other.
  ]
]

#lead[Scope]

Sections 3 and 4 measure declared availability, notified schedules and
acceptance-adjusted dispatch. Reliability outcomes, such as avoided unserved
energy, are not estimated.

#lead[Constructing the population]

No public register labels a Balancing Mechanism unit a battery. Units
declaring symmetric import and export capability, corroborated against public
registers, recover all #metric[#n6.curated_recovered] of #n6.curated_bmus
hand-researched BM Units. #n6.mwh_none sites publish no energy capacity and
are excluded from every state-of-charge figure.

#panel("nb06_fig1_census_composition.svg", ratio: 100%)[
  Figure 1. The census by site size and connection level. #n6.dist_sites
  distribution-connected sites hold #n6.dist_share of declared capacity, as do
  the #n6.top_band_sites largest sites.
]

#lead[Method]

#text(size: 18pt)[
  A day-ahead schedule on cleared prices, re-optimised intraday with perfect
  foresight. Efficiency 0.94 each way, 10% charge floor, 1.5 cycles per day,
  £2/MWh execution cost. Stored energy holds no terminal value, so modelled
  end-of-day depletion is an upper bound and the schedule is never rewarded
  for pre-event charge. Fleet behaviour comes from half-hourly physical
  notifications, with charge integrated rather than metered; Balancing
  Mechanism acceptances are netted as a measured sensitivity on both bases.
]

#lead[How other markets price tightness]

#text(size: 18pt)[
  Some European markets transmit system tightness into a price batteries
  schedule against, or pay directly for the charging behaviour that GB leaves
  unrewarded.
  #v(1.5mm)
  *Belgium prices scarcity continuously,* through adders derived from an
  operating-reserve demand curve, published since October 2019.
  #v(1mm)
  *France pays for the charging behaviour directly.* Under TURPE 7, in force
  August 2025,
  distribution-connected batteries receive up to €69/MWh to charge in midday
  solar hours and are penalised for discharging at the wrong ones; the storage
  component applies from August 2026.
  #v(1mm)
  *GB applies neither instrument.* Scarcity reaches the battery only through
  cash-out. The
  REMA Summer Update of 10 July 2025 rejected zonal pricing for reformed
  national pricing, routing locational signals through network and
  connection-charge reform covering generation, *storage* and demand: the
  instrument TURPE 7 already applies to batteries.
  #v(1.5mm)
  Policy design must therefore target the relevant gate. Scarcity signals may
  affect scheduling, availability mechanisms declared capability, readiness
  products pre-event energy, and duration mechanisms the investment that sets
  the ceiling in Figure 3. Their welfare and investment effects are not
  estimated here.
]

#colbreak()

#section("2 · The modelled incentive", cost-red)
#basis("UTILISATION · top-decile residual load · " + winA, cost-red)

#lead[Profit-optimal dispatch concentrates in peak hours]

With no system-value term in the objective, the profit-optimal schedule still
places #metric[#n4.top_decile_pct] of its discharge in top-decile hours and
draws #metric[#n4.surplus_pct] of its charging from surplus. It delivers
#metric[#n4.free_share] of achievable energy at no sacrifice of market value
#text(size: 16pt)[(aggregate basis 82%)], forgoing #metric[#n4.forgone_pct]
#n4.forgone_ci.

#lead[Scarcity settles outside the scheduling price]

GB prices it as the value of lost load times loss-of-load probability, paid in
cash-out, so it never enters the day-ahead objective. It was exactly zero in
#metric[#n4.scarcity_zero] of settlement periods.

#panel("nb04_fig2_diurnal_mismatch.svg", ratio: 100%)[
  Figure 2. Discharge peaks at #n4.peak_hour with the load, so the shortfall
  is not one of timing: the store reaches its #n4.soc_floor floor by
  #n4.floor_hour while the system remains tight in #n4.tight_at_floor of those
  days.
]

#lead[The cost of alignment and the duration constraint]

Buying every top-decile hour costs #metric[#n4.cost_all]
#text(size: 16pt)[(£3.5 to £9.0)], which is #n4.cost_all_share. Buying the
entire system-value schedule, a broader objective that also credits surplus
absorption, costs #metric[£50/MW/day] #text(size: 16pt)[(£38 to £62)]. No
payment lifts the two-hour asset past #metric[#n4.dur2_best] of what six hours
of storage reaches, a level the longer asset attains at
#metric[#n4.dur6_free] before any payment.

#panel("nb04_fig_duration_frontier.svg", ratio: 100%)[
  Figure 3. Each curve sweeps the weight on system value for one duration; the
  dot marks its profit schedule. Capital cost of the extra energy is not
  modelled.
]

#colbreak()

#section("3 · The observed fleet on the same basis", cost-red)
#basis("UTILISATION · top-decile residual load · " + winA, cost-red)

#lead[The shortfall accumulates at three gates on this basis]

#v(1mm)
#block(inset: (left: 1mm))[
  #text(size: 18.5pt)[
    #metric[#nb.ach_nameplate], the most registered power could deliver \
    #h(3mm) ↓ #text(fill: cost-red.darken(10%), weight: "bold")[#nb.gate_declared]
    #h(0.5mm) *declared* available to the operator \
    #h(3mm) ↓ #text(fill: cost-red.darken(10%), weight: "bold")[#nb.gate_planned]
    #h(0.5mm) of that *scheduled* in notifications \
    #h(3mm) ↓ #text(fill: cost-red.darken(10%), weight: "bold")[#nb.gate_delivered]
    #h(0.5mm) of that remaining after *netting accepted bids and offers* \
    #metric[#nb.delivered_boa] in the acceptance-adjusted profile
  ]
]
#v(2mm)

The fourth, whether stored energy lasts the event, is the subject of Section 4.
The largest loss occurs at the first gate, and it does not concern dispatch:
declared availability supports barely half of registered power. Given what was
declared, the fleet scheduled #metric[#nb.gate_planned] of it, close to the
modelled optimum's #n9.model_delivered. Netting acceptances then removes
#metric[#nb.gate_instructed_away], concentrated in the evening peak, with the
operator moving batteries *down*.

An availability requirement could affect the first gate but would not by
itself address the third. Why declared availability falls so far below
registered power is not identified in public data: outage, derating, reserved response headroom and commercial
choice are not separable here.

#panel("nb09_fig_model_vs_fleet.svg", ratio: 100%)[
  Figure 4. The mean day, per MW installed. The fleet discharges at the same
  hours as the model, at roughly a third of the depth. Neither series is
  metered output.
]

#lead[Delivery falls as ancillary earnings rise]

The least-ancillary quartile delivers #metric[#n9.low_anc_delivered], the
most-ancillary #metric[#n9.high_anc_delivered]: Spearman
#metric[#n9.anc_corr] (p #n9.anc_p, n = #n9.anc_sites), surviving a duration
control. The relationship is associational: contracted volume is unobserved
and the window is summer.

#panel("nb09_fig_revenue_stack.svg", ratio: 100%)[
  Figure 5. Quartile means run #n9.low_anc_delivered to
  #n9.high_anc_delivered against the model's #n9.model_delivered. Dot area is
  site capacity.
]

#colbreak()

#section("4 · Behaviour under operator scarcity", discharge)
#basis("SCARCITY · the operator's own instruments · 2018 to 2026", discharge)

#lead[Response is not the binding constraint]

In the flagged half-hours the fleet is net discharging 87% of the time, at
#metric[+0.060 MW per MW online] against #n5.baseline overall. Clustering by event
preserves the era difference:
#metric[#sx.resp_mod_cl #sx.resp_mod_ci] from #n8.era_start against
#metric[#sx.resp_pre_cl #sx.resp_pre_ci] before.

#lead[Readiness has changed]

Across #n5.events events the median inferred onset charge is
#metric[#n5.soc_at_onset], no fuller than on matched control days, and
#metric[#n5.dispatch_gap] of usable energy is still held at the deepest point.
No separately identifiable payment is observed for entering a scarcity event
at a high state of charge.

#v(2mm)
#grid(
  columns: (78mm, 1fr, 40mm),
  column-gutter: 5mm,
  [],
  text(size: 13pt, fill: ink.lighten(45%))[0 #h(1fr) median onset charge, per
  cent #h(1fr) 100],
  [],
)
#shiftrow("Primary integration", "before against from April 2024",
  sx.onset_pre, sx.onset_modern)
#shiftrow("Re-anchored at 04:00", "sensitivity, same events",
  sx.onset_pre_anch, sx.onset_modern_anch)
#v(1.5mm)
#text(size: 17pt, fill: ink.lighten(35%), style: "italic")[
  Figure 6. Median charge at onset, before April 2024 (n = #sx.onset_pre_n)
  against from April 2024 (n = #sx.onset_modern_n). The decline is
  #absn(sx.onset_diff) points under the primary integration, interval
  #sx.onset_diff_ci, and #absn(sx.onset_diff_anch) points re-anchored:
  direction
  robust, magnitude scheme-dependent. Measured against arriving full, an
  upper bound on remediable energy, since a battery providing Response holds
  headroom in both directions. These #sx.gate_events_total events use the
  loss-of-load rule alone, so both eras are scored on one instrument; the
  #n5.events and #n8.events quoted above bridge the union of all three
  instruments defined in Section 1.
]

#lead[Acceptances change little on this basis]

The response moves from #nb.response_pn to #metric[#nb.response_boa] and onset
charge by two points, against the #metric[#nb.cut_pct] reduction in Section 3.
The
instruction effect is concentrated in high-load hours rather than in
scarcity.

#lead[The level change is robust but its timing is not]

Searching every candidate quarter, the imposed #n7.break_date boundary ranks
#metric[#sx.break_rank] on the Akaike information criterion. The rise is not
compositional: a fixed panel of #n7.panel_sites sites shifts
#metric[#n7.panel_ratio], more than the fleet's #metric[#n7.fleet_ratio].

#panel("nb07_fig_regime_shift.svg", ratio: 100%)[
  Figure 7. Later against earlier response under the same margin, by band.
  The change is largest where the system was loosest. Periods are split at an
  imposed date, so this is a contrast rather than an estimated break.
]

]

#v(1.5mm)
#line(length: 100%, stroke: 3pt + rule-grey)
#v(2mm)

#grid(
  columns: (1.5fr, 1fr, 92mm),
  gutter: 13mm,
  [
    #text(size: 18pt, weight: "bold", fill: ink)[Limitations]
    #v(1.5mm)
    #text(size: 15.5pt)[
    - *The utilisation basis is one 60-day window,* because no single public source spans the
      period: ENTSO-E stopped publishing GB day-ahead prices. A winter re-run
      puts the gap at #n4.winter_gap_range against this window's
      #n4.forgone_pct.
    - *Charge is inferred, not metered.* Re-anchoring shifts levels by about
      ten points, which is why Figure 6 reports both schemes.
    - *Top-decile load is utilisation, not shortage.* Published loss-of-load
      probability sums to #n8.lole_mean_h per year against the 3-hour
      standard, an expectation rather than realised events. The
      reserve-scarcity component is episodic rather than absent: zero in
      #n4.scarcity_zero of this window, but #n4.winter_scarcity_max in winter
      2019-20, and still settling only through cash-out.
    - *Timing is not identified,* and the dispatch-to-load correlation is
      mostly diurnal shape (#sx.corr_raw falling to #sx.corr_within). No
      causal claim is made about ancillary contracts or the break date.
    - *Unchanged by* load threshold, cost model, day resampling, initial
      charge, and a period-resolved declared bound.
    ]
  ],
  [
    #text(size: 18pt, weight: "bold", fill: ink)[Sources & data]
    #v(1.5mm)
    #text(size: 15.5pt)[
      *Elexon BMRS/Insights:* physical notifications, export limits, bid-offer
      acceptances, cash-out. \
      *NESO Data Portal:* loss-of-load probability, de-rated margin, Capacity
      Market notices, TEC and Embedded registers, ancillary auction
      results. \
      *Nord Pool N2EX, ENTSO-E:* day-ahead prices. *PV_Live:* solar
      outturn. \
      *Operator disclosures:* site energy capacity, each carrying its source
      and read date.
      #v(2.5mm)
      All feeds are public. The census, the dispatch engine and every figure
      here rebuild from them at #box[*github.com/shaw029/power-trading*], with the
      full methods and limitations.
      #v(2.5mm)
      *Policy, external to this study:* Papavasiliou et al., _The Electricity
      Journal_ 33 (2020); CRE, _TURPE 7_ (2025); DESNZ, _REMA Summer Update_
      (10 July 2025).
    ]
  ],
  [
    #grid(
      columns: (1fr, 1fr),
      column-gutter: 6mm,
      align: (center, center),
      [
        #image(FIG + "dashboard_qr.svg", width: 44mm)
        #v(1mm)
        #text(size: 12.5pt, weight: "bold", hyphenate: false)[Live dashboard]
      ],
      [
        #image(FIG + "repo_qr.svg", width: 44mm)
        #v(1mm)
        #text(size: 12.5pt, weight: "bold", hyphenate: false)[Code & notebooks]
      ],
    )
  ],
)
