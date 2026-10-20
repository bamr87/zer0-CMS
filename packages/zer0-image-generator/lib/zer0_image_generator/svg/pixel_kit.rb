# frozen_string_literal: true

module Zer0ImageGenerator
  module Svg
    # Retro pixel-art SVG toolkit — a port of `tools/svg/pixelkit.py`, which
    # stays the oracle. The style, codified:
    #
    # - Integer pixel grid. Every mark is an axis-aligned run of whole cells;
    #   nothing lives off-grid, so nothing can be half a pixel wrong.
    # - `shape-rendering="crispEdges"` on the root, so no engine anti-aliases
    #   the art into mush.
    # - Small palettes (6 tokens, engine-kin) declared once. Sprites are ASCII
    #   maps, chars -> tokens.
    # - Horizontal runs of same-colored cells merge into single <rect>s: a
    #   64x48 scene stays a few KB instead of thousands of one-cell rects.
    # - Optional CRT dressing (scanline veil + vignette bars).
    #
    # This is a LIBRARY the generator slices (invaders, pixelquest) build on, so
    # both the API shape and the exact output bytes are contract. The committed
    # scenes under `docs/samples/` and `docs/showcase/` were emitted through
    # this code; the run-length merge in particular is output-shaping, and any
    # difference there changes the SVG bytes.
    module PixelKit
      SVG_NS = "http://www.w3.org/2000/svg"

      # [bg, shadow, low-mid, mid, accent, highlight] — same shape as the
      # engine's RETRO_PALETTES rows so scenes read as kin to its banners.
      PALETTES = {
        "dusk" => ["#1a1423", "#3d2b3d", "#7a3045", "#f24236", "#f5a623", "#f7e8d3"],
        "cyanic" => ["#0b132b", "#1c2541", "#1c7293", "#5bc0be", "#9fd8d6", "#e8f1f2"],
        "moss" => ["#16211b", "#243b2a", "#3e6b48", "#6f9e6f", "#a3c9a8", "#e9edc9"],
        "magma" => ["#120b16", "#2d1b2e", "#5c2a4a", "#b3324b", "#f2542d", "#ffd166"],
      }.freeze

      module_function

      # Mirror each row left-to-right (classic invader symmetry). With
      # shared_center the last column is the axis and is not doubled.
      #
      # Python slices `row[-2::-1]` (reverse minus last char) and `row[::-1]`
      # (full reverse); the Ruby equivalents must agree on the empty and
      # single-char rows, hence `row[0..-2]` rather than chopping by index.
      def hmirror(half, shared_center: true)
        half.map do |row|
          tail = shared_center ? (row[0..-2] || "").reverse : row.reverse
          row + tail
        end
      end
    end

    # A fixed-size integer cell grid. Colors are stored per cell and only
    # collapsed into <rect> runs at serialization time (see #to_svg).
    class Canvas
      attr_reader :cols, :rows, :px, :bg

      def initialize(cols, rows, px: 8, bg: "#000000")
        @cols = cols
        @rows = rows
        @px = px
        @bg = bg
        @cells = {}
      end

      # Off-grid writes are silently ignored — the same clamp the oracle uses
      # so blits and discs can run off the edge without special-casing callers.
      def set(col, row, color)
        return unless col >= 0 && col < @cols && row >= 0 && row < @rows

        @cells[[col, row]] = color
      end

      def fill(col, row, width, height, color)
        (row...(row + height)).each do |r|
          (col...(col + width)).each do |c|
            set(c, r, color)
          end
        end
      end

      # Stamp an ASCII sprite. '.' and ' ' are transparent; any other char must
      # be in `colors`. A missing key is a typo in the sprite or its map, and
      # like the oracle's `colors[ch]` it fails loudly (KeyError) rather than
      # painting nothing and hiding the mistake.
      def blit(art, colors, col, row)
        art.each_with_index do |line, dr|
          line.chars.each_with_index do |ch, dc|
            next if ch == "." || ch == " "

            set(col + dc, row + dr, colors.fetch(ch))
          end
        end
      end

      # Blocky pixel disc — the engine's celestial-body look on a grid. `r` may
      # be fractional; Python's `int()` truncates toward zero, which Ruby's
      # `Integer#to_i`/`Float#to_i` also does, so the row/col spans line up.
      def disc(cx, cy, r, color)
        rr = r * r
        ((cy - r).to_i..(cy + r).to_i).each do |row|
          ((cx - r).to_i..(cx + r).to_i).each do |col|
            set(col, row, color) if (((col - cx)**2) + ((row - cy)**2)) <= rr
          end
        end
      end

      def to_svg(title, crt: false)
        w = @cols * @px
        h = @rows * @px
        px = @px
        safe = title.gsub("&", "&amp;").gsub("<", "&lt;")

        parts = [
          %(<svg xmlns="#{PixelKit::SVG_NS}" viewBox="0 0 #{w} #{h}" role="img" ) +
            %(shape-rendering="crispEdges">),
          "<title>#{safe}</title>",
          %(<rect width="#{w}" height="#{h}" fill="#{@bg}"/>),
        ]

        (0...@rows).each do |row|
          row_runs(row).each do |col, length, color|
            parts << %(<rect x="#{col * px}" y="#{row * px}" width="#{length * px}" ) +
                     %(height="#{px}" fill="#{color}"/>)
          end
        end

        if crt
          (0...h).step(6) do |y|
            parts << %(<rect y="#{y}" width="#{w}" height="1" fill="#000" opacity="0.10"/>)
          end
          [0, h - px].each do |y|
            parts << %(<rect y="#{y}" width="#{w}" height="#{px}" fill="#000" opacity="0.30"/>)
          end
        end

        parts << "</svg>"
        "#{parts.join("\n")}\n"
      end

      private

      # Merge each row's horizontal runs of identical color into (start, length,
      # color) tuples. The sentinel column at `@cols` flushes the final run; a
      # cell whose color differs from the current run closes it and opens the
      # next. This mirrors the oracle exactly because the emitted rect list —
      # and therefore the byte output — depends on precisely where runs break.
      def row_runs(row)
        runs = []
        start = nil
        color = nil
        (0..@cols).each do |col|
          cell = @cells[[col, row]]
          next unless cell != color || col == @cols

          runs << [start, col - start, color] unless color.nil? || start.nil?
          if cell.nil?
            start = nil
            color = nil
          else
            start = col
            color = cell
          end
        end
        runs
      end
    end
  end
end
