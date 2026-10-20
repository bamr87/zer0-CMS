# frozen_string_literal: true

require_relative "../../support/py_random"

module Zer0ImageGenerator
  module Svg
    module Generators
      # Radial-symmetry mandala — port of `tools/svg/examples/mandala.py`.
      #
      # Concentric rings of a motif repeated with N-fold rotational symmetry.
      # Each ring's motif, radius, count, and palette role is seeded; one ring
      # is deliberately offset in phase so the piece isn't a perfect test
      # pattern (house rule: break symmetry in one place). Motifs are defined
      # once in <defs> and instanced with <use> + rotate, so a dense mandala
      # stays a few KB.
      #
      # The committed artwork under `docs/samples/mandala-*.svg` was produced by
      # the Python original, so this port is pinned to byte-identical output:
      # every draw comes off `Support::PyRandom` in the same order, and every
      # interpolated number is formatted to the same width the f-strings used.
      module Mandala
        # [bg, ring-a, ring-b, accent, highlight]
        PALETTES = {
          "jewel" => ["#120a24", "#3d2c8d", "#00a8a8", "#f25f5c", "#ffe066"].freeze,
          "solar" => ["#1a1005", "#7a3b12", "#e08a1e", "#f2c14e", "#fff3d6"].freeze,
          "ocean" => ["#04121f", "#0b3a5b", "#1c88a8", "#5bc0be", "#e8f1f2"].freeze,
          "rose" => ["#1a0f16", "#5a2244", "#a83e6f", "#e58fb0", "#f7e0e8"].freeze,
        }.freeze

        DEFAULT_PALETTE = "jewel"

        SIZE = 800
        R_MAX = 356

        KINDS = ["petal", "diamond", "dot", "spoke"].freeze
        FOLDS = [12, 16, 18, 20, 24].freeze

        HALF = Rational(1, 2)
        private_constant :HALF

        class << self
          # Returns the finished SVG document, newline-terminated.
          def build(seed, palette = DEFAULT_PALETTE)
            rng = Support::PyRandom.new(seed)
            pal = PALETTES.fetch(palette)
            # Python's `S / 2` is true division, so the center lands in the
            # markup as "400.0", not "400" — keep it a Float.
            center = SIZE / 2.0
            defs = []
            layers = []

            fold = rng.choice(FOLDS)
            bands = rng.randint(5, 7)
            gap = R_MAX / (bands + 1).to_f
            radii = Array.new(bands) { |i| gap * (i + 1) } # even bands, no dead space
            quirk = rng.randrange(bands) # the one band that breaks phase

            parts = [
              %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 #{SIZE} #{SIZE}" role="img">),
              "<title>Mandala, seed #{seed}, #{fold}-fold, palette #{palette}</title>",
              %(<rect width="#{SIZE}" height="#{SIZE}" fill="#{pal[0]}"/>),
              %(<circle cx="#{center}" cy="#{center}" r="#{R_MAX + 22}" fill="none" ) +
                %(stroke="#{pal[1]}" stroke-width="3"/>),
              %(<circle cx="#{center}" cy="#{center}" r="#{R_MAX + 12}" fill="none" ) +
                %(stroke="#{pal[3]}" stroke-width="1.5" opacity="0.7"/>),
            ]

            radii.each_with_index do |r, i|
              kind = rng.choice(KINDS)
              count = i.even? ? fold : fold * 2 # denser alternating bands
              color = pal[(i % 3) + 1]
              stroke = rng.random < 0.6 ? pal[4] : "none"
              h = gap * 0.5 * (kind == "dot" ? 0.5 : 0.95)
              w = gap * (%w[petal diamond].include?(kind) ? 0.3 : 0.22)
              mid = "m#{i}"
              defs << motif_def(mid, kind, h, w, color, stroke)
              phase = i == quirk ? 180.0 / count : 0.0
              uses = [%(<g transform="translate(#{center} #{center})">)]
              count.times do |k|
                ang = phase + (k * 360.0 / count)
                uses << %(<use href="##{mid}" transform="rotate(#{fmt(ang, 2)}) ) +
                         %(translate(0 #{fmt(-r, 1)})"/>)
              end
              uses << "</g>"
              layers << uses.join("\n")
            end

            # Center rosette: a small ring of petals, then concentric discs
            defs << motif_def("mc", "petal", gap * 0.55, gap * 0.22, pal[3], pal[4])
            rosette = [%(<g transform="translate(#{center} #{center})">)]
            fold.times do |k|
              rosette << %(<use href="#mc" transform="rotate(#{fmt(k * 360.0 / fold, 2)}) ) +
                          %(translate(0 #{fmt(-gap * 0.6, 1)})"/>)
            end
            rosette << "</g>"
            layers << rosette.join("\n")
            layers << %(<circle cx="#{center}" cy="#{center}" r="#{fmt(gap * 0.42, 1)}" fill="#{pal[3]}"/>)
            layers << %(<circle cx="#{center}" cy="#{center}" r="#{fmt(gap * 0.24, 1)}" fill="#{pal[4]}"/>)
            layers << %(<circle cx="#{center}" cy="#{center}" r="#{fmt(gap * 0.09, 1)}" fill="#{pal[0]}"/>)

            parts << "<defs>\n#{defs.join("\n")}\n</defs>"
            parts.concat(layers)
            parts << "</svg>"
            "#{parts.join("\n")}\n"
          end

          private

          # Motif centered at the local origin, long axis radial (±y).
          #
          # `sw` collapses to the empty string when there is no stroke, which
          # leaves a double space in the markup. The samples were generated
          # that way, so the spacing is part of the contract, not a typo.
          def motif_def(mid, kind, h, w, color, stroke)
            sw = stroke == "none" ? "" : %(stroke="#{stroke}" stroke-width="1.5")
            case kind
            when "petal"
              %(<ellipse id="#{mid}" rx="#{fmt(w, 1)}" ry="#{fmt(h, 1)}" ) +
                %(fill="#{color}" #{sw} opacity="0.92"/>)
            when "diamond"
              %(<path id="#{mid}" d="M0 #{fmt(-h, 1)} L #{fmt(w, 1)} 0 ) +
                %(L 0 #{fmt(h, 1)} L #{fmt(-w, 1)} 0 Z" ) +
                %(fill="#{color}" #{sw} opacity="0.92"/>)
            when "dot"
              %(<circle id="#{mid}" r="#{fmt([3.0, w * 0.8].max, 1)}" fill="#{color}" #{sw}/>)
            else
              # spoke: a short radial tick, decorative between bands
              %(<path id="#{mid}" d="M0 #{fmt(-h, 1)} L 0 #{fmt(h, 1)}" stroke="#{color}" ) +
                %(stroke-width="#{fmt([1.5, w * 0.35].max, 1)}" stroke-linecap="round"/>)
            end
          end

          # Python's `f"{x:.1f}"` correctly rounds the *exact* binary value,
          # half-to-even. Ruby's `format("%.1f", x)` and `Float#round` both
          # round the shortest decimal representation instead, half-away —
          # `13.35` prints "13.3" in Python and "13.4" in Ruby, which is enough
          # to desync a band of motifs from the committed samples. Rational
          # arithmetic gives the exact value, so the rounding decision is made
          # on the same number Python sees.
          def fmt(value, places)
            negative = value.negative? || (value.zero? && (1.0 / value).negative?)
            scaled = value.abs.to_r * (10**places)
            whole = scaled.floor
            remainder = scaled - whole
            whole += 1 if remainder > HALF || (remainder == HALF && whole.odd?)

            digits = whole.to_s.rjust(places + 1, "0")
            text = places.zero? ? digits : "#{digits[0...-places]}.#{digits[-places..]}"
            negative ? "-#{text}" : text
          end
        end
      end
    end
  end
end
