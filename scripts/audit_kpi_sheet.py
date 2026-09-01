"""Check that docs/specs/dashboard_kpis.md still describes the dashboard.

The sheet is the plan and the record, so it is only worth having if it stays
true. This compares it against ``dashboard/live_app.py`` page by page and
prints what disagrees.

Two counting traps it avoids, both of which produced wrong answers by hand:

* **Metric calls are not tiles.** An empty-state branch re-renders the same
  column slot with an em dash, so ``.metric(`` overcounts. Tiles are counted as
  distinct column slots *within a page function*, which is also why the count
  cannot be done with one file-wide grep — ``cols[0]`` appears on every page.
* **Charts are counted as renders, not builders.** A parameterised builder can
  legitimately draw two different charts on one page — the regimes page draws
  the state-of-charge profile and the intraday-deviation profile from the same
  function — and the sheet lists what a reader sees, so ``st.plotly_chart``
  calls are what match it. The case this gets wrong is the mirror image: a
  fallback drawing the *same* builder in two mutually exclusive branches, which
  a reader only ever sees once. No page does that today, and if one starts this
  audit will flag it, which is the right moment for a human to decide whether
  the sheet wants one row or two.

Run it after touching either file::

    python scripts/audit_kpi_sheet.py
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "dashboard" / "live_app.py"
SHEET = REPO_ROOT / "docs" / "specs" / "dashboard_kpis.md"

# Which page each rendering function belongs to. Helpers that draw part of a
# page are attributed to that page.
OWNER = {
    "_page_day": "DAY",
    "_page_history": "HIS",
    "_page_system": "SYS",
    "_page_fleet": "FLT",
    "_render_fleet": "FLT",
    "_fleet_filters": "FLT",
    "_page_day_types": "DTY",
    "_page_sim_vs_fleet": "SVF",
    "_page_alignment": "ALN",
    "_page_methodology": "MTH",
}
PAGE_NAMES = {
    "DAY": "Daily summary", "HIS": "Optimiser performance", "SYS": "GB system overview",
    "FLT": "Fleet performance", "DTY": "Market regimes", "SVF": "Execution gap",
    "ALN": "Alignment gap", "MTH": "Methodology",
}


def _page_bodies() -> dict[str, str]:
    """Source of each page, with helper functions folded into their page."""
    parts = re.split(r"\ndef (\w+)\(", APP.read_text())
    bodies: dict[str, str] = collections.defaultdict(str)
    for i in range(1, len(parts), 2):
        name, body = parts[i], parts[i + 1].split("\ndef ")[0]
        if name in OWNER:
            bodies[OWNER[name]] += body
    return bodies


def _code_counts() -> dict[str, collections.Counter]:
    counts: dict[str, collections.Counter] = {}
    for page, body in _page_bodies().items():
        slots = set(re.findall(r"(\w+\[\d+\])\.metric\(", body))
        # A page may render a lone tile without indexing a column.
        bare = len(re.findall(r"(?<!\])\.metric\(", body))
        counts[page] = collections.Counter(
            {
                "Number": len(slots) + bare,
                "Graph": len(re.findall(r"plotly_chart\(", body)),
                "Table": len(re.findall(r"\.dataframe\(", body)),
                "Download": len(re.findall(r"download_button\(", body)),
            }
        )
    return counts


def _sheet_counts() -> dict[str, collections.Counter]:
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    row = re.compile(r"^\| ([A-Z]{3})-\d+ \| [^|]+\| (\w+) \|")
    for line in SHEET.read_text().splitlines():
        match = row.match(line)
        if match:
            counts[match.group(1)][match.group(2)] += 1
    return counts


def main() -> int:
    code, sheet = _code_counts(), _sheet_counts()
    problems = []
    for page in sorted(set(code) | set(sheet)):
        for kind in ("Number", "Graph", "Table", "Download"):
            in_code = code[page][kind] if page in code else 0
            in_sheet = sheet[page][kind]
            if in_code != in_sheet:
                problems.append(
                    f"  {PAGE_NAMES.get(page, page):24} {kind:9} "
                    f"code {in_code}, sheet {in_sheet}"
                )
    if problems:
        print("KPI sheet disagrees with the dashboard:")
        print("\n".join(problems))
        print("\nFilters and Notes are not counted: one row often covers several "
              "widgets on purpose (the fleet's four site multiselects), and a "
              "Note has no single call to match.")
        return 1
    print("KPI sheet matches the dashboard on every page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
