# frozen_string_literal: true

require_relative "../../support/py_random"

module Zer0ImageGenerator
  module Svg
    module Generators
      # Faceted low-poly gradient field — port of `tools/svg/examples/lowpoly.py`.
      #
      # A jittered triangle grid (interior vertices perturbed, borders pinned so
      # there are no gaps) painted with a vertical palette gradient, then each
      # facet is brightened/darkened by smooth value noise so the surface reads
      # as folded planes catching light, with an off-center radial "sun" glow.
      # Each facet is stroked in its own fill to close the sub-pixel seams that
      # float rounding leaves between triangles.
      #
      # The committed artwork under `docs/samples/lowpoly-*.svg` was produced by
      # the Python original, so this port is pinned to byte-identical output:
      # the sun/jitter draws come off `Support::PyRandom` in the same order,
      # `math.hypot` is reproduced to the last ULP, and every colour channel is
      # rounded the way CPython's `round()` rounds.
      module Lowpoly
        # vertical gradient stops top -> bottom, then [accent, shadow]
        PALETTES = {
          "dusk" => ["#f5a35c", "#e2565b", "#7a3355", "#2b2240", "#ffd27a", "#161227"].freeze,
          "cyanic" => ["#bfe6e4", "#5bc0be", "#1c7293", "#0b1f3a", "#e8f1f2", "#06101f"].freeze,
          "moss" => ["#e9edc9", "#a3c9a8", "#3e6b48", "#16241b", "#f2e9c9", "#0c1610"].freeze,
          "ember" => ["#ffd166", "#f2542d", "#a11d33", "#2a0e1a", "#fff0c2", "#170610"].freeze,
        }.freeze

        DEFAULT_PALETTE = "dusk"

        W = 1200
        H = 800

        HALF = Rational(1, 2)
        private_constant :HALF

        class << self
          def value_noise(seed)
            hash = lambda do |ix, iy|
              n = (ix * 374_761_393) + (iy * 668_265_263) + (seed * 40_503)
              n = (n ^ (n >> 13)) * 1_274_126_177
              # `/ 0xFFFF` is true division in Python; fdiv keeps it a Float.
              ((n ^ (n >> 16)) & 0xFFFF).fdiv(0xFFFF)
            end
            smooth = ->(t) { t * t * (3 - (2 * t)) }
            lambda do |x, y|
              ix = x.floor
              iy = y.floor
              fx = smooth.call(x - ix)
              fy = smooth.call(y - iy)
              a = hash.call(ix, iy)
              b = hash.call(ix + 1, iy)
              c = hash.call(ix, iy + 1)
              d = hash.call(ix + 1, iy + 1)
              ((a * (1 - fx)) + (b * fx)) * (1 - fy) + (((c * (1 - fx)) + (d * fx)) * fy)
            end
          end

          # Returns the finished SVG document, newline-terminated.
          def build(seed, palette, cols = 16, rows = 11)
            rng = Support::PyRandom.new(seed)
            noise = value_noise(seed)
            stops = PALETTES.fetch(palette)
            grad = stops[0, 4].map { |c| hex(c) }
            accent = hex(stops[4])
            shadow = hex(stops[5])
            cw = W.fdiv(cols)
            ch = H.fdiv(rows)

            # Sun focus in the upper band, off-center by seed.
            sx = rng.uniform(0.15, 0.5) * W
            sy = rng.uniform(0.12, 0.32) * H
            sun_r = rng.uniform(0.30, 0.42) * H

            pts = {}
            (0..rows).each do |r|
              (0..cols).each do |c|
                x = c * cw
                y = r * ch
                if c.positive? && c < cols && r.positive? && r < rows
                  x += rng.uniform(-0.42, 0.42) * cw
                  y += rng.uniform(-0.42, 0.42) * ch
                end
                pts[[c, r]] = [x, y]
              end
            end

            parts = [
              %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 #{W} #{H}" role="img" ) +
                %(shape-rendering="geometricPrecision">),
              "<title>Low-poly field, seed #{seed}, palette #{palette}</title>",
            ]

            facet = lambda do |a, b, c|
              cx = (a[0] + b[0] + c[0]) / 3
              cy = (a[1] + b[1] + c[1]) / 3
              base = grad(grad, cy / H)
              # value noise -> plane shading; +/- ~14%
              shade = 0.86 + (0.28 * noise.call(cx / 190, cy / 190))
              col = base.map { |v| v * shade }
              # sun glow: blend toward accent within radius; lift shadow tint low
              dist = hypot(cx - sx, cy - sy)
              col = lerp(col, accent, ((1 - (dist / sun_r))**2) * 0.8) if dist < sun_r
              col = lerp(col, shadow, (cy / H - 0.82) / 0.18 * 0.5) if cy > H * 0.82
              p = "#{fmt(a[0], 1)},#{fmt(a[1], 1)} #{fmt(b[0], 1)},#{fmt(b[1], 1)} " \
                  "#{fmt(c[0], 1)},#{fmt(c[1], 1)}"
              rgb = rgb(col)
              %(<polygon points="#{p}" fill="#{rgb}" stroke="#{rgb}" stroke-width="1"/>)
            end

            rows.times do |r|
              cols.times do |c|
                p00 = pts[[c, r]]
                p10 = pts[[c + 1, r]]
                p01 = pts[[c, r + 1]]
                p11 = pts[[c + 1, r + 1]]
                # alternate the split diagonal so facets don't all lean one way
                if (c + r).even?
                  parts << facet.call(p00, p10, p11)
                  parts << facet.call(p00, p11, p01)
                else
                  parts << facet.call(p00, p10, p01)
                  parts << facet.call(p10, p11, p01)
                end
              end
            end

            parts << "</svg>"
            parts.join("\n") + "\n"
          end

          private

          def hex(c)
            [1, 3, 5].map { |i| c[i, 2].to_i(16) }
          end

          def rgb(t)
            "#" + t.map { |v| format("%02x", [0, [255, round_int(v)].min].max) }.join
          end

          def lerp(a, b, t)
            Array.new(3) { |i| a[i] + ((b[i] - a[i]) * t) }
          end

          def grad(stops, t)
            t = [0.0, [1.0, t].min].max
            n = stops.length - 1
            seg = [(t * n).to_i, n - 1].min
            lerp(stops[seg], stops[seg + 1], (t * n) - seg)
          end

          # Python's `round(v)` (no ndigits) -> nearest int, round-half-to-even.
          def round_int(value)
            neg = value.negative?
            scaled = value.abs.to_r
            whole = scaled.floor
            remainder = scaled - whole
            whole += 1 if remainder > HALF || (remainder == HALF && whole.odd?)
            neg ? -whole : whole
          end

          # A bit-exact port of CPython 3.8+ `math.hypot` (Hettinger's scaled
          # 2Sum accumulation). Ruby's `Math.hypot` differs in the last ULP,
          # which can flip a rounded colour channel and break byte-identity.
          TWO_POW_27 = 134_217_729.0 # 2**27 + 1, the Veltkamp split constant
          private_constant :TWO_POW_27

          def two_prod(a, b)
            prod = a * b
            ah = (a * TWO_POW_27) - ((a * TWO_POW_27) - a)
            al = a - ah
            bh = (b * TWO_POW_27) - ((b * TWO_POW_27) - b)
            bl = b - bh
            err = (((ah * bh) - prod) + (ah * bl) + (al * bh)) + (al * bl)
            [prod, err]
          end

          def hypot(dx, dy)
            coords = [dx.abs, dy.abs]
            max = coords.max
            return max if max.zero? # avoids 0/0 when both are zero

            _, max_e = Math.frexp(max)
            scale = Math.ldexp(1.0, -max_e)
            csum = 1.0
            frac1 = 0.0
            frac2 = 0.0
            coords.each do |c|
              x = c * scale
              pr, err = two_prod(x, x)
              s = csum + pr
              frac2 += (csum - s) + pr
              csum = s
              frac1 += err
            end
            h = Math.sqrt((csum - 1.0) + (frac1 + frac2))
            # one Newton step on the residual, matching CPython's correction
            pr, err = two_prod(-h, h)
            s = csum + pr
            frac2 += (csum - s) + pr
            csum = s
            frac1 += err
            x = (csum - 1.0) + (frac1 + frac2)
            h += x / (2.0 * h)
            h / scale
          end

          # Exact correctly-rounded fixed-point, matching Python's `f"{x:.Nf}"`.
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

if __FILE__ == $PROGRAM_NAME
  require "fileutils"

  mod = Zer0ImageGenerator::Svg::Generators::Lowpoly
  opts = { seed: 1, palette: mod::DEFAULT_PALETTE, cols: 16, rows: 11,
           out: ".sweep/lowpoly.svg" }
  argv = ARGV.dup
  until argv.empty?
    flag = argv.shift
    val = argv.shift
    case flag
    when "--seed" then opts[:seed] = Integer(val)
    when "--palette" then opts[:palette] = val
    when "--cols" then opts[:cols] = Integer(val)
    when "--rows" then opts[:rows] = Integer(val)
    when "--out" then opts[:out] = val
    else raise ArgumentError, "unknown flag #{flag.inspect}"
    end
  end

  dir = File.dirname(opts[:out])
  FileUtils.mkdir_p(dir.empty? ? "." : dir)
  svg = mod.build(opts[:seed], opts[:palette], opts[:cols], opts[:rows])
  File.write(opts[:out], svg)
  puts opts[:out]
end
