# frozen_string_literal: true

# Temporary in-tree stub of the retro pixel toolkit that a sibling slice ports
# to lib/zer0_image_generator/svg/pixel_kit.rb. It exists ONLY so the
# invaders/pixelquest generator tests can pin byte-identity as a fallback when
# that shared file is not yet on disk; the harness prefers the real file
# whenever present (see test_invaders.rb / test_pixelquest.rb). It is a faithful
# port of tools/svg/pixelkit.py (the oracle) and mirrors the shared slice's
# namespace: PALETTES + hmirror under PixelKit, Canvas directly under Svg.
module Zer0ImageGenerator
  module Svg
    module PixelKit
      SVG_NS = "http://www.w3.org/2000/svg"

      # [bg, shadow, low-mid, mid, accent, highlight]
      PALETTES = {
        "dusk" => ["#1a1423", "#3d2b3d", "#7a3045", "#f24236", "#f5a623", "#f7e8d3"].freeze,
        "cyanic" => ["#0b132b", "#1c2541", "#1c7293", "#5bc0be", "#9fd8d6", "#e8f1f2"].freeze,
        "moss" => ["#16211b", "#243b2a", "#3e6b48", "#6f9e6f", "#a3c9a8", "#e9edc9"].freeze,
        "magma" => ["#120b16", "#2d1b2e", "#5c2a4a", "#b3324b", "#f2542d", "#ffd166"].freeze,
      }.freeze

      # Mirror each row left-to-right. With shared_center the last column is the
      # axis and is not doubled.
      def self.hmirror(half, shared_center: true)
        half.map do |row|
          tail = shared_center ? (row[0..-2] || "").reverse : row.reverse
          row + tail
        end
      end
    end

    # Canvas lives directly under Svg (matching the shared slice's layout), not
    # under PixelKit — the generators reference Zer0ImageGenerator::Svg::Canvas.
    class Canvas
      attr_reader :cols, :rows, :px, :bg

      def initialize(cols, rows, px: 8, bg: "#000000")
        @cols = cols
        @rows = rows
        @px = px
        @bg = bg
        @cells = {}
      end

      def set(col, row, color)
        @cells[[col, row]] = color if col >= 0 && col < @cols && row >= 0 && row < @rows
      end

      def fill(col, row, width, height, color)
        (row...(row + height)).each do |r|
          (col...(col + width)).each { |c| set(c, r, color) }
        end
      end

      # '.' and ' ' are transparent; any other char must be in `colors`
      # (typos should fail loudly, not silently).
      def blit(art, colors, col, row)
        art.each_with_index do |line, dr|
          line.chars.each_with_index do |ch, dc|
            next if ch == "." || ch == " "

            set(col + dc, row + dr, colors.fetch(ch))
          end
        end
      end

      # Blocky pixel disc. Python's int() truncates toward zero, as does to_i.
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
          (0...h).step(6).each do |y|
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

      def row_runs(row)
        runs = []
        start = nil
        color = nil
        (0..@cols).each do |col|
          cell = @cells[[col, row]]
          if cell != color || col == @cols
            runs << [start, col - start, color] if !color.nil? && !start.nil?
            if cell.nil?
              start = nil
              color = nil
            else
              start = col
              color = cell
            end
          end
        end
        runs
      end
    end
  end
end
