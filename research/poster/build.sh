#!/usr/bin/env bash
#
# Compile the A0 board, and keep its tracked inputs honest.
#
# The notebooks export every figure three ways into ./exports,
# which is gitignored: it is bulky, it is derived, and it is rebuilt whenever a
# notebook is re-run. But a clone cannot rebuild it. The data store those
# notebooks read is 18 GB and not in the repository, so for anyone but the
# author those exports are unreproducible, and a board whose inputs are missing
# is a layout file nobody can render.
#
# So the subset the board actually places is published into ./assets, which is
# tracked. That set is derived by reading the .typ source rather than listed
# here, which means a panel added to the board is picked up automatically instead
# of being forgotten until someone clones and the build breaks.
set -euo pipefail

cd "$(dirname "$0")"
HERE="$PWD"
EXPORTS="$HERE/exports"

command -v typst >/dev/null 2>&1 || {
  echo "typst not found. Install it with: brew install typst" >&2
  exit 1
}

# Everything the board references, read straight out of its source.
needed=$(
  { grep -ohE '"[a-z0-9_]+\.svg"' ./*.typ | tr -d '"'
    grep -ohE 'json\("assets/[a-z0-9_]+\.json"\)' ./*.typ | grep -oE '[a-z0-9_]+\.json'
  } | sort -u
)

mkdir -p assets
missing=""
for f in $needed; do
  # Refresh from the notebook exports when they are present and newer, so a
  # re-run notebook reaches the board without anyone copying files by hand.
  if [ -f "$EXPORTS/$f" ] && [ "$EXPORTS/$f" -nt "assets/$f" ]; then
    cp "$EXPORTS/$f" "assets/$f"
    echo "  refreshed  assets/$f"
  fi
  [ -f "assets/$f" ] || missing="$missing $f"
done

if [ -n "$missing" ]; then
  echo "missing poster inputs:" >&2
  for f in $missing; do echo "    assets/$f" >&2; done
  echo "Re-run the notebook that exports it, then build again." >&2
  echo "See research/README.md for which notebook owns which figure." >&2
  exit 1
fi

typst compile --root . poster.typ poster.pdf
printf '  poster -> research/poster/poster.pdf (%s)\n' "$(du -h poster.pdf | cut -f1)"
