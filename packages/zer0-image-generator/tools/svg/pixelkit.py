#!/usr/bin/env python3
"""
pixelkit.py — retro pixel-art SVG toolkit. Stdlib only.

The style, codified:

- Integer pixel grid. Every mark is an axis-aligned run of whole cells;
  nothing lives off-grid, so nothing can be half a pixel wrong.
- `shape-rendering="crispEdges"` on the root, so no engine anti-aliases
  the art into mush.
- Small palettes (6 tokens, engine-kin: bg, two shadows, mid, accent,
  highlight) declared once. Sprites are ASCII maps, chars -> tokens.
- Horizontal runs of same-colored cells merge into single <rect>s: a
  64x48 scene stays a few KB instead of thousands of one-cell rects.
- Optional CRT dressing (scanline veil + vignette bars) — the same trick
  render_local_svg uses, so pieces read as kin to the engine's banners.

Use from a generator script (see examples/invaders.py, examples/pixelquest.py):

    from pixelkit import Canvas, PALETTES
    c = Canvas(64, 48, px=12, bg=PALETTES["cyanic"][0])
    c.blit(SHIP, {"#": PALETTES["cyanic"][5]}, 28, 40)
    svg = c.to_svg("Invader wave", crt=True)
"""
from typing import Dict, Iterable, List, Tuple

SVG_NS = "http://www.w3.org/2000/svg"

# [bg, shadow, low-mid, mid, accent, highlight] — same shape as the
# engine's RETRO_PALETTES rows so scenes read as kin to its banners.
PALETTES: Dict[str, List[str]] = {
    "dusk":   ["#1a1423", "#3d2b3d", "#7a3045", "#f24236", "#f5a623", "#f7e8d3"],
    "cyanic": ["#0b132b", "#1c2541", "#1c7293", "#5bc0be", "#9fd8d6", "#e8f1f2"],
    "moss":   ["#16211b", "#243b2a", "#3e6b48", "#6f9e6f", "#a3c9a8", "#e9edc9"],
    "magma":  ["#120b16", "#2d1b2e", "#5c2a4a", "#b3324b", "#f2542d", "#ffd166"],
}

Art = Iterable[str]


def hmirror(half: Art, shared_center: bool = True) -> List[str]:
    """Mirror each row left-to-right (classic invader symmetry). With
    shared_center the last column is the axis and is not doubled."""
    out = []
    for row in half:
        tail = row[-2::-1] if shared_center else row[::-1]
        out.append(row + tail)
    return out


class Canvas:
    def __init__(self, cols: int, rows: int, px: int = 8, bg: str = "#000000"):
        self.cols, self.rows, self.px, self.bg = cols, rows, px, bg
        self.cells: Dict[Tuple[int, int], str] = {}

    def set(self, col: int, row: int, color: str) -> None:
        if 0 <= col < self.cols and 0 <= row < self.rows:
            self.cells[(col, row)] = color

    def fill(self, col: int, row: int, w: int, h: int, color: str) -> None:
        for r in range(row, row + h):
            for c in range(col, col + w):
                self.set(c, r, color)

    def blit(self, art: Art, colors: Dict[str, str], col: int, row: int) -> None:
        """Stamp an ASCII sprite. '.' and ' ' are transparent; any other
        char must be in `colors` (typos should fail loudly, not silently)."""
        for dr, line in enumerate(art):
            for dc, ch in enumerate(line):
                if ch in ". ":
                    continue
                self.set(col + dc, row + dr, colors[ch])

    def disc(self, cx: int, cy: int, r: float, color: str) -> None:
        """Blocky pixel disc — the engine's celestial-body look on a grid."""
        rr = r * r
        for row in range(int(cy - r), int(cy + r) + 1):
            for col in range(int(cx - r), int(cx + r) + 1):
                if (col - cx) ** 2 + (row - cy) ** 2 <= rr:
                    self.set(col, row, color)

    def _row_runs(self, row: int) -> List[Tuple[int, int, str]]:
        runs: List[Tuple[int, int, str]] = []
        start, color = None, None
        for col in range(self.cols + 1):
            cell = self.cells.get((col, row))
            if cell != color or col == self.cols:
                if color is not None and start is not None:
                    runs.append((start, col - start, color))
                start, color = (col, cell) if cell is not None else (None, None)
        return runs

    def to_svg(self, title: str, crt: bool = False) -> str:
        w, h, px = self.cols * self.px, self.rows * self.px, self.px
        safe = title.replace("&", "&amp;").replace("<", "&lt;")
        parts = [
            f'<svg xmlns="{SVG_NS}" viewBox="0 0 {w} {h}" role="img" '
            f'shape-rendering="crispEdges">',
            f"<title>{safe}</title>",
            f'<rect width="{w}" height="{h}" fill="{self.bg}"/>',
        ]
        for row in range(self.rows):
            for col, length, color in self._row_runs(row):
                parts.append(
                    f'<rect x="{col * px}" y="{row * px}" width="{length * px}" '
                    f'height="{px}" fill="{color}"/>'
                )
        if crt:
            for y in range(0, h, 6):
                parts.append(
                    f'<rect y="{y}" width="{w}" height="1" fill="#000" opacity="0.10"/>'
                )
            for y in (0, h - px):
                parts.append(
                    f'<rect y="{y}" width="{w}" height="{px}" fill="#000" opacity="0.30"/>'
                )
        parts.append("</svg>")
        return "\n".join(parts) + "\n"
