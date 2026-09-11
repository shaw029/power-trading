# Beyond the Spread

**Quantifying the Alignment Gap Between Battery Arbitrage and Energy System Resilience**
Abhinav Shaw · A0 landscape (1189 × 841 mm)

> Energy prices already secure about four-fifths of the modelled battery's
> high-load alignment. Response during scarcity and readiness before scarcity
> emerge as distinct dimensions of battery behaviour.

## Build

```bash
make poster                    # from the repo root
./research/poster/build.sh     # or directly
```

Requires [Typst](https://typst.app) (`brew install typst`). Output lands beside the
source as `poster.pdf`, gitignored — the layout source is the artifact under
version control, the board is a render of it.

## Reading design

A poster session gives five seconds walking past, sixty seconds if the reader
stops, and after that the author is the medium. So the board is built in three
tiers rather than two: every finding opens with a bold statement that stands on
its own, with two or three lines of support beneath it. A reader who takes only
the bold lines leaves with the whole argument; a judge who reads everything still
finds the caveats. Material that exists to defend rather than to inform sits
behind the QR.

**No computed number on the board is typed by hand.** Every result is read from
`assets/`, written by the notebook that computes it, so the board cannot drift
from the analysis: change an analysis, re-run its notebook, and the board moves
with it.

Exactly two literals remain in `poster.typ`, and neither is a result:

- `£2/MWh`, the modelled execution cost — an *input* stated in the Method note,
  and set in `configs/config.example.yaml`.
- `€69/MWh`, the French TURPE 7 charging bonus — an external figure cited from
  CRE, not something any notebook computes.

That distinction is the whole point of the rule, and it was not always kept. The
September 2026 audit found five *results* sitting in the source as literals,
reading identically to the generated references beside them: the 2,075 scarcity
half-hours, the fleet's 87% net-discharging share, `+0.060 MW per MW online`,
the `£50/MW/day` system-value figure and its `(£38 to £62)` bounds. Two had gone
stale — the embedded-solar correction to residual load moved the system-value
figure to £80/MW/day, and it rendered beside a `(£3.5 to £9.0)` interval that no
longer contained its own point estimate. All five are now exported keys
(`n5.n_lolp`, `n5.lolp_discharge_share`, `n5.lolp_response`,
`n4.cost_full_align`, `n4.cost_all_ci`).

One trap worth recording, because the fix is not obvious: `nb05` already
exported `discharge_share` and `response`, which look like the keys the fleet
sentence wants. They are not. Those describe the **DRM < 1 GW** subset (n = 39);
the sentence is about the **LoLP ≥ 1e-4** set (n = 2,075). Substituting them
would have swapped the population while looking like a tidy-up.

## Structure

| Section | Question | Source |
|---|---|---|
| 1 · Population and measurement basis | Who is in the GB battery fleet, and how much of it can we see? | nb06 |
| 2 · The modelled incentive | What would a profit-maximising battery do, and what does alignment cost it? | nb04 |
| 3 · The observed fleet on the same basis | Does the real fleet behave like the model, measured the same way? | nb09 |
| 4 · Behaviour under operator scarcity | What did the fleet do when the system was genuinely tight? | nb05, nb07, nb08, nb10 |

The utilisation basis measures against top-decile residual load, the scarcity
basis against the operator's own instruments over 2018 to 2026. They are
different measures, which is the reason section 3 exists.

## Inputs — why `assets/` is tracked

The notebooks export every figure three ways into `exports/`, which is
gitignored: bulky, derived, and rebuilt whenever a notebook is re-run. But a
clone cannot rebuild it. The store those notebooks read is 18 GB and is not in
the repository, so for anyone but the author those exports are unreproducible,
and a board whose inputs are missing is a layout file nobody can render.

So `build.sh` publishes the subset the board actually places into `assets/`, and
that subset is tracked — 16 files, 456 KB:

- `nb{04,05,06,07,08,09,10}_metrics.json` and `stats_metrics.json` — the
  generated numbers on the board, written by the notebook that computes each.
  See the caveat above for the literals that are not yet among them.
- eight `*.svg` panels, vectors so they stay sharp at a metre wide.

The set is derived by parsing the `.typ` sources rather than listed anywhere, so
a board that gains a panel picks it up automatically instead of breaking for the
next person to clone. Everything else in `exports/` — the 300 DPI
PNGs, the print PDFs, and the panels no board places — stays untracked.
