#!/usr/bin/env bash
# svg-sweep.sh — run a parametric generator across N seeds, render each, and
# stitch one labelled contact sheet.
#
#   ./tools/svg/svg-sweep.sh tools/svg/banner-seed.py 12
#
# Why: reading 12 PNGs costs ~12x the tokens of reading 1 contact sheet, and
# the model judges variation far better side-by-side than sequentially.
set -euo pipefail

GEN="${1:?usage: svg-sweep.sh <generator.py> [count]}"
N="${2:-9}"
DIR=".sweep"
rm -rf "$DIR" && mkdir -p "$DIR"

for i in $(seq 1 "$N"); do
  python3 "$GEN" --seed "$i" --out "$DIR/seed-$i.svg"
  bash "$(dirname "$0")/svg-render.sh" "$DIR/seed-$i.svg" 400 >/dev/null
done

COLS=$(python3 -c "import math,sys; print(math.ceil(math.sqrt(int(sys.argv[1]))))" "$N")
MONTAGE=$(command -v montage || true)
[[ -n "$MONTAGE" ]] || { echo "install ImageMagick for contact sheets" >&2; exit 127; }

"$MONTAGE" -label '%f' -background '#111' -fill '#eee' -tile "${COLS}x" \
           -geometry '400x400+8+8' .preview/seed-*.png "$DIR/contact-sheet.png"

echo "$DIR/contact-sheet.png"
echo "Read the contact sheet, name the 2-3 strongest seeds and say why."
