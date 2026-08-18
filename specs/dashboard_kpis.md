# Dashboard KPI sheet

Source of truth for **everything the live dashboard displays**. One row per visible element.

## How this is used

1. **Plan here.** A new metric starts as a `proposed` row in this file — never as code.
2. **Design from here.** The design pass reads the rows: `type` says what shape the element is,
   `format` says what it looks like, `source` says whether the data already exists.
3. **Build from here.** Implementation quotes the row `id` in the PR, flips `status` to `built`,
   and lands the sheet edit in the *same commit* as the code.

A row and its code go in together. If the sheet and `dashboard/live_app.py` disagree, the sheet is wrong.

## Conventions

**ID** — `<PAGE>-<TYPE><n>`, stable forever. Retire an ID (`status: removed`) rather than reuse it.
Page codes: `GLB` global · `DAY` · `HIS` history · `SYS` system · `FLT` fleet · `DTY` day types ·
`SVF` benchmark vs fleet · `ALN` alignment gap · `MTH` methodology.

**Type** — the distinction that drives design:

| Type | Means | Streamlit |
|---|---|---|
| `number` | Single headline figure, optional delta line | `st.metric` |
| `chart` | Plot | `st.plotly_chart` |
| `table` | Rows the reader scans or sorts | `st.dataframe` |
| `control` | Filter or selector that changes what is shown | widget |
| `text` | Caption carrying a *computed* value (not static prose) | `st.caption` |
| `file` | Download | `st.download_button` |

**Status** — `built` · `proposed` · `removed`.

**Source** — the feed, then the function that computes it. This column is what says whether a
proposed row is cheap (data already flows) or expensive (needs a new downloader).

---

## GLB — global controls

Sidebar, present on every page.

| ID | Element | Type | Format | Source | Status |
|---|---|---|---|---|---|
| GLB-X1 | Period | control | segmented: 7D/14D/30D/60D/Custom, default 30D | `_global_filters` | built |
| GLB-X2 | Custom range | control | date pair, bounded to available days; shown only when Period=Custom | `_global_filters` | built |
| GLB-X3 | Day types | control | multiselect, 10 tags + `untagged`, none = all | `live.classify` tags | built |
| GLB-X4 | Duration | control | radio 1h/2h/4h | `live.assets.REFERENCE_DURATIONS` | built |
| GLB-X5 | Cycle target | control | slider 0.5–3.0 cycles/day, step 0.5 | `_benchmark_parameters` | built |
| GLB-X6 | Degradation cost | control | slider £0–20/MWh, step 0.5 | `_benchmark_parameters` | built |
| GLB-X7 | SOC band | control | range slider 0–100%, step 5 | `_benchmark_parameters` | built |
| GLB-X8 | DA commitment | control | slider 0–100%, step 5 | `_benchmark_parameters` | built |

Levers X4–X8 sit in a form: nothing re-settles until **Apply**. They are hidden on SYS and FLT,
which show a "levers do not affect this page" caption instead.

## DAY — Day (`/latest`, landing page)

| ID | Element | Type | Format | Source | Status |
|---|---|---|---|---|---|
| DAY-X1 | Day picker | control | selectbox, defaults to latest settled day; persists across pages | `_page_day` | built |
| DAY-N1 | Net PnL | number | £X/MW + delta vs window avg | `settle_day` → `net_pnl` | built |
| DAY-N2 | DA benchmark | number | £X/MW | `settle_day` → `benchmark_da_revenue` | built |
| DAY-N3 | Cycles | number | X.XX | `settle_day` → `cycles` | built |
| DAY-N4 | Capture | number | X% | `settle_day` → `capture` | built |
| DAY-N5 | DA spread | number | £X/MWh | Nord Pool DA, peak−trough of the day | built |
| DAY-C1 | Day composite | chart | 4 panels: prices / dispatch vs DA / SOC band / residual load | `chart_day_composite` | built |
| DAY-C2 | Dispatch vs system state | chart | 2 panels, stress+surplus shading; falls back to realised shape | `chart_alignment_day` | built |
| DAY-C3 | System prices | chart | DA vs MID | `chart_system_prices` | built |
| DAY-C4 | SOC tracker | chart | SOC path in band | `chart_soc_tracker` | built |
| DAY-C5 | PnL waterfall | chart | attribution | `chart_pnl_waterfall` | built |
| DAY-C6 | Day in window | chart | where this day sits in the window | `chart_day_in_window` | built |
| DAY-C7 | Generation mix | chart | in **System detail** expander | `chart_generation_mix` | built |
| DAY-C8 | Realised shape | chart | in **Battery detail** expander | `chart_realized_shape` | built |
| DAY-T1 | Raw half-hourly system | table | in **System detail** expander | `fetch_live.get_day_system` | built |
| DAY-T2 | Fleet this day | table | top sites by £/MW | `fleet_perf.day_site_metrics` | built |
| DAY-Z1 | Stress half-hours on this day | text | "N stress half-hour(s)" | `_window_flags` | built |
| DAY-F1 | System CSV | file | download | `fetch_live.get_day_system` | built |

## HIS — History (`/history`)

| ID | Element | Type | Format | Source | Status |
|---|---|---|---|---|---|
| HIS-N1 | Avg net PnL | number | £X/MW/day | window mean of `net_pnl` | built |
| HIS-N2 | Total net PnL | number | £X absolute | window sum | built |
| HIS-N3 | Positive days | number | n / N | count `net_pnl > 0` | built |
| HIS-N4 | Best day | number | £X/MW + date delta | window max | built |
| HIS-C1 | Daily attribution | chart | stacked PnL components per day | `chart_daily_attribution` | built |
| HIS-C2 | Price capture | chart | charge/discharge by hour vs avg DA | `chart_price_capture` | built |

## SYS — System overview (`/system`) — observed data only

| ID | Element | Type | Format | Source | Status |
|---|---|---|---|---|---|
| SYS-N1 | Days shown | number | N | filtered window | built |
| SYS-N2 | Avg peak demand | number | X.X GW | Elexon ITSDO → `_system_summary_day` | built |
| SYS-N3 | Low-carbon generation | number | X% of GB generation | Elexon FUELHH + PV_Live | built |
| SYS-N4 | Net interconnectors | number | ±X GWh (+ = import) | Elexon FUELHH INT* | built |
| SYS-C1 | Daily generation stack | chart | by fuel group | `chart_generation_daily` | built |
| SYS-C2 | Low-carbon share | chart | over time | `chart_low_carbon_daily` | built |
| SYS-C3 | Daily avg wholesale price | chart | DA vs MID | `chart_system_prices` | built |

## FLT — Fleet performance (`/fleet`) — observed data only

| ID | Element | Type | Format | Source | Status |
|---|---|---|---|---|---|
| FLT-X1 | Sites / Optimisers / Regions / Battery hours | control | 4 multiselects, default all | `_fleet_filters` | built |
| FLT-X2 | Metric | control | segmented: Revenue/Volume/Cycles/Capacity | `_render_fleet` | built |
| FLT-N1 | Fleet tracked | number | X MW nameplate | `fleet.registry` | built |
| FLT-N2 | Top vs median spread | number | £X/MW/day + median delta | `summarise_by_site` | built |
| FLT-N3 | Fleet avg | number | £X/MW/day, MW-day weighted | `summarise_by_site` | built |
| FLT-N4 | Top site | number | site name + £/MW/day | `summarise_by_site` | built |
| FLT-C1 | Site leaderboard | chart | by selected metric | `chart_fleet_leaderboard` | built |
| FLT-C2 | Fleet daily | chart | series by selected metric | `chart_fleet_daily` | built |
| FLT-T1 | Per-site detail | table | one row per site | `summarise_by_site` | built |

Revenue = Physical Notifications × MID + indicative BM cashflows. Ancillary income is not public,
so ancillary-tilted sites read low and are flagged, never silently mixed in.

## DTY — Day types (`/day-types`)

| ID | Element | Type | Format | Source | Status |
|---|---|---|---|---|---|
| DTY-C1 | Capture by day type | chart | bar | `chart_daytype_capture` | built |
| DTY-C2 | Tag co-occurrence | chart | matrix | `chart_daytype_matrix` | built |
| DTY-C3 | Tag frequency | chart | bar | `chart_daytype_frequency` | built |
| DTY-C4 | Dispatch profiles by tag | chart | profiles | `chart_daytype_profiles` | built |
| DTY-T1 | Days behind the tags | table | day → tags | `live.classify` | built |

**No KPI row on this page.** Deliberate gap or oversight — decide before adding one (see backlog).

## SVF — Benchmark vs fleet (`/sim-vs-fleet`)

| ID | Element | Type | Format | Source | Status |
|---|---|---|---|---|---|
| SVF-X1 | Include ⚠ ancillary-tilted sites | control | toggle, default off | `_page_sim_vs_fleet` | built |
| SVF-N1 | Sim ceiling | number | £X/MW/day | benchmark over common days | built |
| SVF-N2 | Fleet wholesale avg | number | £X/MW/day, PN×MID leg only | `summarise_by_site` | built |
| SVF-N3 | Realisation | number | X% of ceiling | N2 ÷ N1 | built |
| SVF-N4 | Sites compared | number | n × duration + excluded count | `summarise_by_site` | built |
| SVF-C1 | Sim vs fleet daily | chart | paired series | `chart_sim_vs_fleet_daily` | built |
| SVF-C2 | Dispatch shape overlay | chart | mean shapes | `chart_shape_overlay` | built |
| SVF-C3 | Capture ratio by day type | chart | bar | `chart_daytype_ratio` | built |

## ALN — Alignment gap (`/alignment`)

Two KPI rows. The heaviest page in the app — check crowding before adding a ninth number.

| ID | Element | Type | Format | Source | Status |
|---|---|---|---|---|---|
| ALN-X1 | Exemplar day | control | selectbox, auto = highest residual-load day | `_page_alignment` | built |
| ALN-N1 | Stress coverage | number | X% of discharge in stress | `resilience.alignment_scores` | built |
| ALN-N2 | Surplus absorption | number | X% of charge in surplus | `resilience.alignment_scores` | built |
| ALN-N3 | Readiness at stress | number | X% mean SOC at onset | `resilience.readiness_at_stress` | built |
| ALN-N4 | Cost of full alignment | number | £X/MW/day + MWh forgone | `resilience.alignment_gap` | built |
| ALN-N5 | Min de-rated margin | number | X MW + timestamp | Elexon LOLPDRM → `tier_metrics` | built |
| ALN-N6 | Periods LoLP > 0 | number | N of periods with data | Elexon LOLPDRM → `tier_metrics` | built |
| ALN-N7 | Tier-2 stress coverage | number | X% | `resilience.tier_metrics` | built |
| ALN-N8 | Capacity Market Notices | number | "N in window" + last notice date | NESO CMN → `_cmn_notices` | built |
| ALN-C1 | Exemplar day dispatch | chart | 2 panels, stress shading | `chart_alignment_day` | built |
| ALN-C2 | System tightness | chart | DRM line + threshold + LoLP markers + tier shading + dispatch | `chart_system_tightness` | built |
| ALN-C3 | Profit vs alignment | chart | fleet scatter, benchmark starred | `chart_alignment_scatter` | built |
| ALN-C4 | Cost of alignment by day type | chart | bar | `chart_gap_by_daytype` | built |
| ALN-T1 | Top stress periods | table | 10 rows: residual, benchmark MW, fleet MW | `_window_flags` | built |
| ALN-Z1 | System confirmation rate | text | "X% of tier-1 stress was tier-2 confirmed" | `tier_metrics` | built |

## MTH — Methodology (`/methodology`)

Static prose and the glossary. No computed elements; nothing to track here beyond keeping
definitions in step with rows above.

---

## Backlog — proposed

Candidates from `notebooks/05_stress_response_study.ipynb`, which already computes all of these
over 2023-10 → 2026-08. Nothing here is committed to; the point is that each row states its cost.

| ID | Element | Type | Source | Cost | Note |
|---|---|---|---|---|---|
| ALN-N9 | Fleet response at stress | number | `fleet_pn` + LOLPDRM | data flows already | Fleet net MW per MW online in top-LoLP periods vs baseline. The single strongest number in the study. |
| ALN-C5 | Cannibalistic charging by margin band | chart | `fleet_pn` + LOLPDRM | data flows already | Charging share falls monotonically as margin tightens — the "does the fleet deepen stress" answer. |
| ALN-N10 | Advance visibility | number | LOLPDRM all horizons | needs horizon-resolved accessor | % of critical periods already over threshold at the 12 h print. |
| ALN-C6 | SoC run-up into stress | chart | inferred SoC + matched controls | needs SoC estimator in repo | Contested methodology — promote only with its caveats and sensitivity check. |
| FLT-N5 | Availability factor | number | Elexon MELS | fetcher exists, not wired to dashboard | Declared export limit ÷ online nameplate. |
| DTY-N1 | Capture spread across tags | number | existing day-type data | trivial | Fills the page's missing KPI row, if the gap is judged real. |

## Maintenance

- Sheet and code change together, one commit.
- Built totals across 8 pages: **29 `number`**, 26 `chart`, 5 `table`, 13 `control`, 1 `file`, 2 `text`.
- The sheet must agree with the source. Both sides of this must print the same number:

```bash
grep -cE '^\|.*\| number \|.*\| built \|' specs/dashboard_kpis.md   # sheet says
grep -c '\.metric(' dashboard/live_app.py                           # code says
```

  The `| built |` guard keeps the backlog out of the count, and the `^\|` anchor keeps this
  snippet from counting itself.
