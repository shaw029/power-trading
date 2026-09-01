# Beyond the Spread

**Quantifying the Alignment Gap Between Battery Arbitrage and Energy System Resilience**
Abhinav Shaw · A0 landscape (1189 × 841 mm)

> Energy prices already secure about four-fifths of the modelled battery's
> high-load alignment. What remains unpriced is readiness for scarcity.

## Build

```bash
make poster          # both variants, from the repo root
```

or directly:

```bash
./research/poster/build.sh
```

Requires [Typst](https://typst.app) (`brew install typst`). Output lands beside
the source as `poster.pdf` and `poster_lean.pdf`, both gitignored — the layout
source is the artifact under version control, the board is a render of it.

## Two variants, one set of numbers

| | length | reading tiers | for |
|---|---|---|---|
| `poster.typ` | ~2,290 words, a nine minute read | title, body | the reader who stops and reads |
| `poster_lean.typ` | about a third shorter | title, **bold finding line**, body | the reader walking past |

The lean variant exists because a poster session gives five seconds walking past
and sixty seconds if the reader stops. The dense board asks for time the format
does not give. The lean one adds the middle tier it lacks: every finding opens
with a bold statement that stands alone, with two or three lines of support
beneath. A reader who takes only the bold lines still leaves with the whole
argument.

Both read the **same** metric JSONs and the **same** SVG panels from `assets/`,
so they cannot disagree about a number. Change an analysis, re-run the notebook
that owns it, and both boards move together.

## Structure

| Section | Question | Source |
|---|---|---|
| 1 · One fleet, two rulers | Who is in the GB battery fleet, and how much of it can we see? | nb06 |
| 2 · The incentive, modelled | What would a profit-maximising battery do, and what does alignment cost it? | nb04 |
| 3 · The fleet, on the same yardstick | Does the real fleet behave like the model, measured the same way? | nb09 |
| 4 · When the operator is short | What did the fleet do when the system was genuinely tight? | nb05, nb07, nb08, nb10 |

Lane A measures against top-decile residual load; Lane B against the operator's
own scarcity instruments over 2018 to 2026. They are different rulers, which is
the reason section 3 exists.

## Inputs — why `assets/` is tracked

The notebooks export every figure three ways into `exports/`, which is
gitignored: bulky, derived, and rebuilt whenever a notebook is re-run. But a
clone cannot rebuild it. The store those notebooks read is 18 GB and is not in
the repository, so for anyone but the author those exports are unreproducible,
and a board whose inputs are missing is a layout file nobody can render.

So `build.sh` publishes the subset the boards actually place into `assets/`, and
that subset is tracked — 16 files, 456 KB:

- `nb{04,05,06,07,08,09,10}_metrics.json` and `stats_metrics.json` — every number
  on the board, written by the notebook that computes it. Nothing is typed by hand.
- eight `*.svg` panels, vectors so they stay sharp at a metre wide.

The set is derived by parsing the `.typ` sources rather than listed anywhere, so
a board that gains a panel picks it up automatically instead of breaking for the
next person to clone. Everything else in `exports/` — the 300 DPI
PNGs, the print PDFs, and the panels no board places — stays untracked.
