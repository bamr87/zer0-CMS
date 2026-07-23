#!/usr/bin/env bash
# svg-render.sh — rasterize an SVG so the model can actually LOOK at it.
#
#   ./tools/svg/svg-render.sh banner.svg [width_px]
#
# Prints the PNG path on stdout. Picks the first available engine.
# Engine choice matters: resvg and Chromium disagree on filters and blend
# modes. Render with whatever your *target* consumer uses.
set -euo pipefail

SRC="${1:?usage: svg-render.sh <file.svg> [width]}"
W="${2:-1200}"
OUT_DIR="${SVG_PREVIEW_DIR:-.preview}"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/$(basename "${SRC%.svg}").png"

have() { command -v "$1" >/dev/null 2>&1; }

if have resvg; then
  resvg --width "$W" "$SRC" "$OUT"                                   # fastest
elif have rsvg-convert; then
  rsvg-convert -w "$W" -o "$OUT" "$SRC"
elif have inkscape; then
  inkscape "$SRC" --export-type=png --export-width="$W" --export-filename="$OUT"
elif python3 -c "import cairosvg" 2>/dev/null; then
  python3 -c "import cairosvg,sys; cairosvg.svg2png(url=sys.argv[1], write_to=sys.argv[2], output_width=int(sys.argv[3]))" "$SRC" "$OUT" "$W"
elif have cairosvg; then
  cairosvg "$SRC" -o "$OUT" --output-width "$W"
elif have chromium || have google-chrome; then
  BROWSER=$(command -v chromium || command -v google-chrome)
  "$BROWSER" --headless --disable-gpu --screenshot="$OUT" \
             --window-size="$W,$W" --default-background-color=00000000 \
             "file://$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
elif have npx; then
  # portable last resort: no global install, ~5s cold start
  npx -y @resvg/resvg-js-cli --width "$W" "$SRC" "$OUT"
else
  echo "no SVG rasterizer found. Install one:" >&2
  echo "  cargo install resvg      # or" >&2
  echo "  brew install librsvg     # rsvg-convert" >&2
  echo "  pip install cairosvg" >&2
  exit 127
fi

echo "$OUT"
