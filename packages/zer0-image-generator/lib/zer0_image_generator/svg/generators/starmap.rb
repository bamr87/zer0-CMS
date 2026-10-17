# frozen_string_literal: true

require_relative "../../support/py_random"

module Zer0ImageGenerator
  module Svg
    module Generators
      # Composed scene from library assets + generated elements — port of
      # `tools/svg/examples/starmap.py`.
      #
      # The "reuse gathered content" path: it inlines MIT-licensed line icons
      # from tools/svg/library/external/ (lucide, feather, tabler) as the cast,
      # over a generated seeded starfield and a low-poly hill silhouette. Icons
      # are stroke="currentColor", so each is recolored and scaled on placement
      # with a counter-scaled stroke width to keep line weight constant
      # regardless of size.
      #
      # Byte-identity contract: `docs/samples/starmap-5.svg` was produced here.
      # The starfield, hill ridges, and per-facet shading all draw from
      # `Support::PyRandom` in a data-dependent order (a star's size/opacity is
      # only drawn when the star survives the thinning test), so the stream must
      # be reproduced draw-for-draw and every float formatted like Python's.
      module Starmap
        # Resolved like the Python original: relative to this file, walk up to
        # the repo root and into the tracked icon library. Kept overridable so a
        # host that vendors the icons elsewhere can point at them without a fork;
        # the default preserves byte-identity with the committed sample.
        DEFAULT_LIBRARY_ROOT = File.join(
          File.expand_path("../../../..", __dir__), "tools", "svg", "library", "external"
        ).freeze

        PALETTE = {
          "sky_top" => "#0a1330", "sky_bot" => "#1b2a4a", "haze" => "#2a3f66",
          "hill_far" => "#213a63", "hill_near" => "#0c1c38",
          "star" => "#e8f1f2", "moon" => "#f2e9c9", "moon_glow" => "#8bbfd6",
          "rocket" => "#f7e8d3", "planet" => "#5bc0be", "accent" => "#f2a541"
        }.freeze

        WIDTH = 1200
        HEIGHT = 800

        STAR_SIZES = [0.6, 0.9, 1.2, 1.8].freeze

        HALF = Rational(1, 2)
        private_constant :HALF

        class << self
          def build(seed, library_root: DEFAULT_LIBRARY_ROOT)
            rng = Support::PyRandom.new(seed)
            w = WIDTH
            h = HEIGHT
            horizon = (h * 0.72).to_i
            p = PALETTE
            out = [
              %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 #{w} #{h}" role="img">),
              "<title>Star map: a rocket among planets over low-poly hills " \
              "(composed from MIT library icons)</title>",
              "<defs>",
              %(<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">) +
                %(<stop offset="0" stop-color="#{p['sky_top']}"/>) +
                %(<stop offset="1" stop-color="#{p['sky_bot']}"/></linearGradient>),
              %(<radialGradient id="glow"><stop offset="0" stop-color="#{p['moon_glow']}" stop-opacity="0.5"/>) +
                %(<stop offset="1" stop-color="#{p['moon_glow']}" stop-opacity="0"/></radialGradient>),
              "</defs>",
              %(<rect width="#{w}" height="#{h}" fill="url(#sky)"/>),
            ]

            # Seeded starfield, thinning toward the horizon
            150.times do
              x = rng.randrange(w)
              y = rng.randrange(horizon)
              next if rng.random > ((1 - (y / horizon.to_f)) * 0.9)

              r = rng.choice(STAR_SIZES)
              out << %(<circle cx="#{x}" cy="#{y}" r="#{py_float(r)}" fill="#{p['star']}" ) +
                     %(opacity="#{fmt(rng.uniform(0.3, 0.95), 2)}"/>)
            end

            # Moon with glow, upper right
            mx = (w * 0.78).to_i
            my = (h * 0.24).to_i
            out << %(<circle cx="#{mx}" cy="#{my}" r="150" fill="url(#glow)"/>)
            out << %(<circle cx="#{mx}" cy="#{my}" r="62" fill="#{p['moon']}"/>)
            out << %(<circle cx="#{mx + 22}" cy="#{my - 14}" r="54" fill="#{p['sky_top']}" opacity="0.55"/>)

            # Low-poly hill silhouettes: two ridges triangulated into facets
            out << ridge(rng, horizon, 70, p["hill_far"], 90)
            out << ridge(rng, horizon + 60, 46, p["hill_near"], 70)

            # Cast: gathered MIT icons, recolored and scaled
            rocket = inner(library_root, "lucide/lucide-rocket.svg")
            planet = inner(library_root, "tabler/tabler-planet.svg")
            star = inner(library_root, "feather/feather-star.svg")
            moon_i = inner(library_root, "feather/feather-moon.svg")

            out << place(planet, (w * 0.2).to_i, (h * 0.3).to_i, 5.2, p["planet"], sw: 2.6)
            out << place(rocket, (w * 0.52).to_i, (h * 0.44).to_i, 9.0, p["rocket"], sw: 2.2)
            out << place(star, (w * 0.36).to_i, (h * 0.16).to_i, 2.0, p["accent"], sw: 2.4)
            out << place(star, (w * 0.64).to_i, (h * 0.6).to_i, 1.5, p["accent"], sw: 2.4, op: 0.8)
            out << place(star, (w * 0.88).to_i, (h * 0.52).to_i, 1.8, p["accent"], sw: 2.4, op: 0.9)
            out << place(moon_i, (w * 0.1).to_i, (h * 0.12).to_i, 2.4, p["moon_glow"], sw: 2.2)

            out << "</svg>"
            "#{out.join("\n")}\n"
          end

          private

          # Strip the outer <svg> wrapper from a library icon, keep its marks.
          # Mirrors Python's slicing: from the first '>' at/after '<svg' up to
          # the last '</svg>', then whitespace-trimmed.
          def inner(library_root, rel)
            t = File.read(File.join(library_root, rel), encoding: "utf-8")
            t = t[(t.index(">", t.index("<svg")) + 1)..]
            t[0...t.rindex("</svg>")].strip
          end

          # Place a 24x24 icon centered at (cx,cy), scaled, stroke width held
          # constant on screen by counter-scaling it against the group scale.
          def place(frag, cx, cy, s, color, sw: 2.4, op: 1.0)
            %(<g transform="translate(#{fmt(cx - (12 * s), 1)} #{fmt(cy - (12 * s), 1)}) ) +
              %(scale(#{fmt(s, 3)})" fill="none" stroke="#{color}" stroke-width="#{fmt(sw / s, 3)}" ) +
              %(stroke-linecap="round" stroke-linejoin="round" opacity="#{py_float(op)}">#{frag}</g>)
          end

          # Two ridges triangulated into facets. Draw order is load-bearing:
          # every column's height (randrange) is drawn first as a batch, then
          # one shade (random) per triangle — matching Python's list
          # comprehension followed by the per-facet loop.
          def ridge(rng, base, amp, color, step)
            cols = (-40...(WIDTH + 80)).step(step).to_a
            top = cols.map { base - rng.randrange(amp) }
            # smooth once
            top = Array.new(top.length) do |i|
              (top[[0, i - 1].max] + top[i] + top[[top.length - 1, i + 1].min]) / 3
            end
            tris = []
            (0...(cols.length - 1)).each do |i|
              x0 = cols[i]
              x1 = cols[i + 1]
              y0 = top[i]
              y1 = top[i + 1]
              shade = 0.68 + (0.42 * rng.random) # wider spread so facets read
              c = "#" + [1, 3, 5].map do |j|
                v = [0, [255, (color[j, 2].to_i(16) * shade).to_i].min].max
                format("%02x", v)
              end.join
              tris << %(<polygon points="#{x0},#{y0} #{x1},#{y1} #{x1},#{HEIGHT} #{x0},#{HEIGHT}" ) +
                      %(fill="#{c}" stroke="#{c}" stroke-width="1"/>)
            end
            tris.join("\n")
          end

          # Exact correctly-rounded fixed-point, matching Python's `f"{x:.Nf}"`
          # (round-half-to-even on the exact binary value). Ruby's `%f`/`round`
          # round the shortest decimal instead, which diverges on ties.
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

          # Bare `{x}` interpolation in Python prints float's shortest
          # round-tripping repr. Ruby's Float#to_s does the same for the values
          # used here (small non-integral and integral-valued floats).
          def py_float(value)
            value.to_s
          end
        end
      end
    end
  end
end
