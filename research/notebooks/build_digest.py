"""Regenerate the notebook digest — every metric and every chart, 04 onward.

Writes research/notebooks/_digest/notebook_digest.md, gitignored by design: it is
derived from the notebooks and goes stale the moment one is re-run. Rebuild with
``make digest`` after re-running any notebook.

Metrics are read from the ``nb*_metrics.json`` files rather than retyped, and
charts are extracted from the notebooks' own stored outputs, so the digest
cannot drift from what the notebooks last produced. Only the prose findings are
written by hand.
"""

from __future__ import annotations

import base64
import json
import pathlib
import re

# Located from this file rather than the working directory, so the digest builds
# the same whether it is invoked by `make digest` or run from anywhere else.
HERE = pathlib.Path(__file__).resolve().parent
NB_DIR = HERE
POSTER = HERE.parent / "poster" / "exports"
DIGEST = HERE / "_digest"
OUT = DIGEST / "notebook_digest.md"

FINDING = {
    "04": (
        "Beyond the Spread: the alignment gap",
        "utilisation",
        """
    The scarcity price signal barely exists. Reserve scarcity price is **exactly zero
    in 99.5% of periods**, and **peaks at £0.03/MWh** even at its maximum. Quote it
    that way: `scarcity_mean` is formatted to 2dp, so its "£0.00/MWh" is a *rounded
    mean over all periods*, not a literal zero, and a reader who checks will find
    the three pence. The frequency claim and the peak are both exact; the mean is
    the one number here that can be attacked. Yet making a battery deliver into peak
    anyway is cheap:
    **£6/MW/day, about 6% of benchmark revenue**. A profit-optimal 50 MW / 2 h asset
    already delivers 82% of achievable top-decile energy. The gap is an
    incentive-design problem, not an economics-of-storage problem.""",
    ),
    "05": (
        "Stress Response Study — full history, DRM < 1 GW",
        "scarcity",
        """
    Across 428 scarcity events since 2018 the fleet does respond — **+0.051 MW per MW
    online, roughly 4x its own baseline** — but arrives only 61% full and leaves a
    **48% dispatch gap**. Responding is not the problem; being ready is.""",
    ),
    "06": (
        "Fleet Census",
        "population",
        """
    The rule recovers **all 47 curated BM Units unaided**, which is what licenses
    using the generated registry everywhere. The binding constraint is energy
    capacity: known for 65 of 87 sites, so **22 sites have no published MWh**
    and any metric dividing by duration must be reported over the known subset.""",
    ),
    "07": (
        "Regime Shift — did the fleet change, or the control room?",
        "scarcity",
        """
    A structural break in **October 2023**, best fit by **step + slope** on AIC. Not
    a composition artefact: a **fixed panel of 35 sites / 1,708 MW** across the break
    gives 4.2x, *larger* than the fleet's 3.4x. Something changed in how the fleet is
    dispatched, not in which batteries exist. Strongly margin-dependent — 2.5x in the
    tightest band, 21x in the loosest.""",
    ),
    "08": (
        "Stress Response, Modern Era — from April 2024",
        "scarcity",
        """
    On modern data the fleet responds far harder — **+0.121 vs +0.051 MW per MW** —
    and the dispatch gap narrows from 48% to **30%**. But it arrives *emptier* (47%
    vs 61%), so the preparedness gap widens to 54%. Better at responding, worse at
    being ready. Realised LOLE averaged **1.0 h** against the 3 h GB standard.""",
    ),
    "09": (
        "The model and the fleet, on one yardstick",
        "utilisation",
        """
    Measured on notebook 04's *own* ruler — same window, same ``classify_periods``
    call, verified identical at **2,878 half-hours / 23.3 GW** — the fleet delivers
    **46%** of achievable top-decile energy against nameplate but **85%** against the
    capability it actually declared (MELS). The model delivers 82%. Two independent
    cuts land on the model's number: MELS-bounded (85%) and the least-ancillary
    quartile (80%). The shortfall is **availability and revenue-stack allocation,
    not misalignment**.

    **Do not concede more than the data requires.** The −0.50 earnings correlation
    is *not* contaminated: it survives a duration control (partial −0.48), and
    duration alone predicts nothing (r = +0.10, ns). The quantity that tracks
    service mix is the **volume** measure `mw_hours`, which sums MW over a variable
    block count (Quick Reserve 35/day vs Response 9) and is therefore unusable as an
    exposure measure — ranked on it the relationship does not hold (+0.28). So the
    association is robust and the *mechanism* is unsettled, for want of a clean
    exposure measure. The correct framing is "association, survives a duration
    control, mechanism unproven" — never "the ancillary penalty", and never that the
    correlation itself is an artefact.

    **Window limit, stated up front:** all of this is 60 days, late June to late
    August. The 80/40 gradient is untested against a January peak.""",
    ),
    "10": (
        "What the Balancing Mechanism does to every fleet figure",
        "both",
        """
    Every fleet number in 05, 08 and 09 is measured from **notifications** — what a
    unit said it would do — not from delivery. Netting BM acceptances splits the two
    lanes cleanly. **Section 3 moves hard: top-decile delivery falls 27%**, because in
    high-load hours the operator instructs batteries *down*, so part of the distance
    between declared capability and delivered energy is post-gate instruction rather
    than battery choice. **Section 4 barely moves**: response +0.060 → +0.056 and
    charge at onset by about two points, so the 61% → 47% readiness decline is a
    property of the fleet, not of the measurement.

    Read together, the operator reshapes battery output at the evening peak and
    barely touches it when short — which is why the two lanes cannot share a
    correction any more than they can share a threshold. Quote the corrected figure
    whenever a delivery claim is made from 09; quote 05 and 08 as they stand.""",
    ),
}


def extract_charts() -> list[dict]:
    """Every inline chart in notebooks 04+, written out with its best caption."""
    DIGEST.mkdir(parents=True, exist_ok=True)
    for old in DIGEST.glob("*.png"):
        old.unlink()
    exported = {p.stem for p in POSTER.glob("*.png")}
    manifest: list[dict] = []
    for path in sorted(NB_DIR.glob("[01][0-9]*.ipynb")):
        nbid, nb, heading, k = path.name[:2], json.loads(path.read_text()), "", 0
        for ci, cell in enumerate(nb["cells"]):
            src = "".join(cell["source"])
            if cell["cell_type"] == "markdown":
                for line in src.splitlines():
                    if line.startswith("##"):
                        heading = line.lstrip("# ").strip()
                continue
            imgs = [o for o in cell.get("outputs", []) if "image/png" in o.get("data", {})]
            if not imgs:
                continue
            # An axes title is the closest thing a cell has to a caption.
            titles = re.findall(r'set_title\(\s*[rf]?["\']([^"\']{4,120})', src) + re.findall(
                r'suptitle\(\s*[rf]?["\']([^"\']{4,120})', src
            )
            stems = re.findall(r'save_poster_fig\(\s*\w+\s*,\s*["\']([\w\d_]+)["\']', src)
            for j, out in enumerate(imgs):
                k += 1
                name = f"nb{nbid}_{k:02d}"
                (DIGEST / f"{name}.png").write_bytes(base64.b64decode(out["data"]["image/png"]))
                cap = titles[j] if j < len(titles) else (titles[0] if titles else "")
                stem = stems[j] if j < len(stems) else (stems[0] if stems else None)
                manifest.append(
                    {
                        "nb": nbid,
                        "file": f"{name}.png",
                        "cell": ci,
                        "section": heading,
                        "caption": re.sub(r"\{[^}]*\}", "…", cap).strip(" -—"),
                        "poster": stem if stem in exported else None,
                    }
                )
    return manifest


def console_text() -> dict[str, str]:
    """Everything notebooks 04+ printed, keyed by notebook id.

    The ``*_metrics.json`` files are a curated subset chosen for the poster.
    Numbers that never made that cut still matter — nb04's £0.03/MWh scarcity
    peak is printed and not exported — so the digest carries the raw output too.
    """
    out: dict[str, str] = {}
    for path in sorted(NB_DIR.glob("[01][0-9]*.ipynb")):
        nb = json.loads(path.read_text())
        chunks: list[str] = []
        for cell in nb["cells"]:
            for o in cell.get("outputs", []):
                if o.get("output_type") == "stream":
                    chunks.append("".join(o.get("text", [])))
                elif "text/plain" in o.get("data", {}):
                    chunks.append("".join(o["data"]["text/plain"]))
        out[path.name[:2]] = "\n".join(c.rstrip() for c in chunks if c.strip())
    return out


def main() -> None:
    charts = extract_charts()
    CONSOLE = console_text()
    metrics = {
        p.name[2:4]: json.loads(p.read_text()) for p in sorted(POSTER.glob("nb*_metrics.json"))
    }
    L: list[str] = []
    w = L.append

    w("# Notebook digest — every metric and every chart, notebook 04 onward\n")
    w(
        "**Not git-tracked.** Lives under `research/notebooks/_digest/`, which `.gitignore` "
        "excludes because it is derived from the notebooks.\n"
    )
    w(
        "Regenerate with `make digest` after re-running any notebook. "
        "Metrics are read from `nb*_metrics.json`; charts are extracted from the "
        "notebooks' own stored outputs. Only the findings are hand-written.\n"
    )
    w("| | |\n|---|---|")
    w("| Census snapshot (pinned) | **2026-08-24** — set `census.SNAPSHOT = None` to go live |")
    w("| Population | 87 sites · 124 BM Units · 6,234 MW |")
    w("| Long window (05, 07) | 2018-01-01 → 2026-08-24 |")
    w("| Short window (04, 09) | 2026-06-26 → 2026-08-24 (60 days) |")
    w("| Modern era (08) | from 2024-04-01 |")
    w(
        f"| Contents | {sum(len(m) for m in metrics.values())} exported metrics · "
        f"{sum(len(c.splitlines()) for c in CONSOLE.values()):,} lines of console output · "
        f"{len(charts)} charts |\n"
    )
    w(
        "Notebooks 01–03 export no poster metrics and are excluded: they are the "
        "superseded strategy-development lineage.\n"
    )

    w("## The two lanes — read before comparing any two numbers\n")
    w(
        "The commonest error here is quoting a utilisation number as a resilience "
        "finding. The lanes use different rulers and are not commensurable.\n"
    )
    w("| Lane | Question | Threshold | Notebooks |\n|---|---|---|---|")
    w(
        "| **Utilisation / incentives** | What happens when the system works *hardest*? "
        "| top-decile residual load (23.3 GW) | **04, 09** |"
    )
    w(
        "| **Operator scarcity** | What happens when the operator has *least slack*? "
        "| `DRM < 1 GW`, CMN, LoLP | **05, 07, 08** |"
    )
    w("| **Population** | How much fleet is there, how well measured? | — | **06** |\n")
    w(
        "Top-decile load is **not** a shortage. No number from 04 or 09 may be quoted "
        "as a resilience finding.\n"
    )

    w("## Chart inventory\n")
    w("| Notebook | Charts | Poster-exported | Notebook-only |\n|---|---|---|---|")
    for nb in sorted(FINDING):
        rows = [c for c in charts if c["nb"] == nb]
        ex = sum(1 for r in rows if r["poster"])
        w(f"| {nb} | {len(rows)} | {ex} | {len(rows) - ex} |")
    w(
        f"| **total** | **{len(charts)}** | **{sum(1 for c in charts if c['poster'])}** "
        f"| **{sum(1 for c in charts if not c['poster'])}** |\n"
    )

    for nb in sorted(FINDING):
        title, lane, finding = FINDING[nb]
        w("---\n")
        w(f"# {nb} — {title}\n")
        w(f"*Lane: {lane}.*\n")
        w(f"**Finding.**{finding.rstrip()}\n")

        md = metrics.get(nb, {})
        w(f"### Metrics ({len(md)})\n")
        if md:
            w("| Key | Value |\n|---|---|")
            for k, v in sorted(md.items()):
                w(f"| `{k}` | {v} |")
            w("")

        # The metrics files are a curated subset; plenty of numbers are printed
        # and never exported (nb04's £0.03/MWh peak among them). The full console
        # output is carried verbatim so the sheet is genuinely complete.
        console = CONSOLE.get(nb, "")
        w(
            f"### Console output — every number this notebook printed "
            f"({len(console.splitlines())} lines)\n"
        )
        if console.strip():
            w("<details><summary>Expand</summary>\n")
            w("```text")
            w(console.rstrip())
            w("```\n")
            w("</details>\n")
        else:
            w("> No text output.\n")

        rows = [c for c in charts if c["nb"] == nb]
        w(f"### Charts ({len(rows)})\n")
        if not rows:
            w(
                "> **None.** This notebook produces no figures — a real gap for a "
                "notebook carrying a headline finding.\n"
            )
            continue
        section = None
        for c in rows:
            if c["section"] != section:
                section = c["section"]
                if section:
                    w(f"**{section}**\n")
            tag = f"poster: `{c['poster']}`" if c["poster"] else "_notebook-only_"
            cap = c["caption"] or "(untitled)"
            w(f"<sub>`{c['file']}` · cell {c['cell']} · {tag}</sub>\n")
            w(f"![{cap}](figures/digest/{c['file']})\n")
            w(f"*{cap}*\n")

    w("---\n")
    w("## Numbers that must agree, and where they are checked\n")
    w("| Anchor | Value | Enforced by |\n|---|---|---|")
    w("| Census snapshot | 2026-08-24 | `census.SNAPSHOT`, set identically in every notebook |")
    w("| Census size | 87 sites / 6,234 MW | nb06; quoted by 05, 09 |")
    w(
        "| Top-decile threshold | 23.3 GW, 2,878 half-hours | printed by **both** 04 and 09 — same function |"
    )
    w(
        "| Cycling rule | 0.3 cycles/day | `ANCILLARY_CYCLES_THRESHOLD`, one definition, test-guarded |"
    )
    w(
        "| Poster figures | read from `nb*_metrics.json` | `poster.typ` substitutes; never retyped |\n"
    )
    w("## Known gaps\n")
    w(
        "1. **nb08 has no charts.** It carries a headline finding (modern-era response, "
        "LOLE 1.0 h) with nothing to show for it.\n"
    )
    w(
        "2. **nb09 has no winter cut.** Its 60 days are late June–August; whether the "
        "80/40 ancillary gradient holds against a January peak is untested.\n"
    )
    w(
        "3. **The nb09 mechanism is unproven.** The ancillary association is robust and "
        "survives a duration control, but `mw_hours` sums MW over a variable block count "
        "(Quick Reserve 35/day vs Response 9), so it tracks service mix. Settling it needs "
        "per-unit contracted MW by service from NESO auction results.\n"
    )
    w(
        "4. **The poster does not yet carry nb09.** Its metrics file is readable by "
        "`poster.typ`, but no panel references it.\n"
    )
    w(
        "5. **`nb04_fig6_money_vs_coverage` is an orphan** — byte-identical to "
        "`nb04_fig_money_vs_coverage`, left behind by a rename, referenced nowhere.\n"
    )
    w(
        "6. **`stress` survives as a code identifier**, deliberately: printed labels in "
        'nb04 were relabelled to "top-decile", but the column returned by '
        "`classify_periods` feeds the dashboard, settlement engine and six test files.\n"
    )

    # ---------------------------------------------------------------------
    # Editorial. Nothing below is measured — it is inference from the numbers
    # above, kept here so the digest carries the "so what" the notebooks
    # deliberately refuse to state. Fenced and confidence-labelled so it can
    # never be lifted into the poster as a finding.
    # ---------------------------------------------------------------------
    w("---\n")
    w("# Policy and fixes — *not in any notebook*\n")
    w(
        "> **This section is editorial.** Every claim above it is measured and traceable "
        "to a metric file. Nothing here is. It is inference drawn from those numbers, "
        "written down because the notebooks deliberately stop at what they can prove. "
        "Each item names the evidence it rests on and how far that evidence actually "
        "carries. **Do not quote anything from this section as a finding.**\n"
    )

    w("## What the numbers imply for market design\n")
    w("| # | Implication | Rests on | Confidence |\n|---|---|---|---|")
    for i, (claim, basis, conf) in enumerate(
        [
            (
                "**Batteries cannot follow a signal that is not there.** Scarcity cash-out is "
                "zero almost always, so peak-hour delivery is currently unpriced — the fleet is "
                "not ignoring an incentive, it is responding to its absence.",
                "nb04 `scarcity_zero` 99.5%, `scarcity_mean` £0.00/MWh",
                "**High** — direct measurement",
            ),
            (
                "**Procuring alignment would be cheap.** Full alignment costs ~6% of benchmark "
                "revenue, and 81% of the delivery is free at the margin. A targeted peak "
                "obligation is a small payment, not a subsidy programme.",
                "nb04 `cost_all_share` 6%, `free_share` 81%, `cost_all` £6/MW/day",
                "**High** — direct, with a cost-model range (£2–6) and a winter check (20–24%)",
            ),
            (
                "**Target availability, not dispatch behaviour.** Conditional on being available "
                "the fleet already delivers ~85%, against the model's 82%. The shortfall to 46% "
                "is capacity never offered at peak. Rules aimed at *how* batteries dispatch are "
                "aimed at the part that already works.",
                "nb09 `fleet_vs_declared` 85% vs `fleet_vs_nameplate` 46%, `model_delivered` 82%",
                "**High** — two independent cuts (MELS 85%, low-ancillary 80%) agree",
            ),
            (
                "**Readiness is the failure mode, not responsiveness.** The fleet responds at 4x "
                "baseline but arrives 61% full, and on modern data it responds harder (+0.121) "
                "while arriving emptier (47%). An obligation should bite on state of charge "
                "*ahead* of tight periods, not on response during them.",
                "nb05 `response`/`soc_at_onset`; nb08 `response` +0.121, `soc_at_onset` 47%, "
                "`preparedness_gap` 54%",
                "**High** — consistent across two windows, and the trend is the wrong way",
            ),
            (
                "**Credit the control room, not new steel.** The October 2023 break survives "
                "holding the panel fixed — a fixed 35-site panel shifts *more* (4.2x) than the "
                "whole fleet (3.4x). Attributing the improvement to fleet growth would "
                "misallocate the credit and the next intervention.",
                "nb07 `break_date`, `panel_ratio` 4.2x vs `fleet_ratio` 3.4x, `preferred_model`",
                "**Medium-high** — break test is AIC-selected; panel control is the strong part",
            ),
            (
                "**Response procurement may be competing with peak energy.** Sites earning most "
                "from ancillary deliver 40% where the least-earning deliver 80%. If real, GB is "
                "buying frequency response and paying part of the price in peak-hour energy.",
                "nb09 `anc_corr` −0.50 (p<0.001), `low_anc_delivered` 80% vs "
                "`high_anc_delivered` 40%, `anc_partial_r` −0.48",
                "**Low-medium** — association robust, *mechanism unproven*; no clean exposure "
                "measure exists in the data",
            ),
            (
                "**A register MW is not a peak MW.** Roughly half of nameplate capacity is not "
                "delivering at top-decile load. Capacity adequacy arithmetic that counts "
                "battery nameplate at face value is overstating what arrives.",
                "nb09 `fleet_vs_nameplate` 46%, `availability_gap` 39%; nb06 `census_mw` 6,234 MW",
                "**Medium** — measured on 90% of fleet MW, one 60-day summer window only",
            ),
        ],
        start=1,
    ):
        w(f"| {i} | {claim} | {basis} | {conf} |")
    w("")
    w(
        "**The honest caveat on all seven.** Items 1–3 and 7 rest on a single 60-day "
        "summer window. Items 4–5 use the long window and the modern era. None of this "
        "is a claim about *scarcity*: the utilisation-lane numbers describe a system "
        "working hard, not a system short of power.\n"
    )

    w("## Safe phrasings — how these claims survive scrutiny\n")
    w(
        "The riskiest numbers here are not the wrong ones, they are the ones whose "
        "*wording* overclaims. Left column is what an examiner can break; right "
        "column says the same thing and holds.\n"
    )
    w("| Claim | Breaks under scrutiny | Holds |\n|---|---|---|")
    for weak, breaks, holds in [
        (
            "Scarcity price",
            '"the scarcity price is £0.00/MWh" — a rounded mean; the series peaks at '
            "£0.03/MWh and a checker will find it",
            "**exactly zero in 99.5% of periods, and £0.03/MWh even at its peak**",
        ),
        (
            "nb09 ancillary gradient",
            '"the ancillary penalty" — asserts a mechanism the data cannot support',
            "**a robust association that survives a duration control; mechanism unproven "
            "for want of a clean exposure measure — and summer-only**",
        ),
        (
            "nb09 fleet delivery",
            '"the fleet delivers 46%" alone — reads as batteries ignoring price signals',
            "**46% against nameplate, 85% against declared availability, model 82%** — "
            "all three, or none",
        ),
        (
            "Anything from 04 or 09",
            '"resilience" / "scarcity" / "security of supply" — top-decile load is '
            "utilisation, not shortage",
            "**when the system is working hardest** — utilisation lane, separate from " "05/07/08",
        ),
        (
            "nb07 regime shift",
            '"the fleet improved" — conflates new capacity with changed behaviour',
            "**a fixed 35-site panel shifts more (4.2x) than the fleet (3.4x)**",
        ),
        (
            "nb08 modern era",
            '"the fleet got better" — half the result, and the flattering half',
            "**responds harder (+0.121 vs +0.051), arrives emptier (47% vs 61%), "
            "preparedness gap widened to 54%**",
        ),
    ]:
        w(f"| **{weak}** | {breaks} | {holds} |")
    w("")

    w("## Fixes, in the order I would do them\n")
    w("| # | Fix | Why it is first/last | Cost |\n|---|---|---|---|")
    for i, (fix, why, cost) in enumerate(
        [
            (
                "**Give nb08 charts.** It carries the modern-era headline — response +0.121, "
                "LOLE 1.0 h against a 3 h standard — and produces no figure at all.",
                "Largest gap between what a notebook knows and what it can show; the poster "
                "cannot use a finding it cannot draw.",
                "~1 h",
            ),
            (
                "**Add nb09's winter cut.** Recompute the 46/85/80/40 split on a winter window "
                "with the top-decile bar held at its pinned absolute level.",
                "The whole notebook rests on 60 summer days. nb04 already carries a winter "
                "sensitivity; nb09 only inherits the exposure.",
                "~2 h, no refetch",
            ),
            (
                "**Pull per-unit contracted MW by service from NESO auction results.** Then "
                "re-run nb09's section 5 against commitment instead of earnings.",
                "The one thing that would convert the strongest policy implication (item 6) "
                "from association to mechanism.",
                "~half a day",
            ),
            (
                "**Point the poster at nb09.** `nb09_metrics.json` exists and `poster.typ` can "
                "already read it; no panel references it.",
                "Cheapest real gain — the bridge between the model and the fleet is the "
                "argument the poster currently lacks.",
                "~1 h",
            ),
            (
                "**Delete `nb04_fig6_money_vs_coverage`.** Byte-identical orphan of "
                "`nb04_fig_money_vs_coverage`, left by a rename, referenced nowhere.",
                "Pure hygiene, but a duplicate figure is exactly how a stale chart reaches a "
                "printed board.",
                "~1 min",
            ),
            (
                "**Leave `stress` alone as a code identifier.** Printed labels are already "
                "relabelled; the column feeds the dashboard, settlement engine and six test "
                "files.",
                "Listed so the decision is recorded rather than rediscovered. Tier 1 "
                "(the column key, ~30 min) is optional; tiers 2–3 cost a store rebuild.",
                "0",
            ),
        ],
        start=1,
    ):
        w(f"| {i} | {fix} | {why} | {cost} |")
    w("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n")
    print(
        f"wrote {OUT.relative_to(HERE.parent)} — {sum(len(m) for m in metrics.values())} "
        f"metrics, {len(charts)} charts"
    )


if __name__ == "__main__":
    main()
