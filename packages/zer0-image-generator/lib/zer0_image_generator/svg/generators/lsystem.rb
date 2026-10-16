# frozen_string_literal: true

require_relative "../../support/py_random"

module Zer0ImageGenerator
  module Svg
    module Generators
      # L-system botanical generator — port of `tools/svg/examples/lsystem.py`.
      #
      # Expand an L-system string, turtle-interpret it into branch segments and
      # growth tips, shade by branch depth (thick dark trunk -> thin bright
      # twigs), and drop foliage at the tips. A seeded per-turn angle jitter
      # keeps the plant organic; four rulesets give four species, four palettes
      # re-skin without touching geometry.
      #
      # The committed artwork under `docs/samples/lsystem-*.svg` was produced by
      # the Python original, so this port is pinned to byte-identical output:
      # every draw comes off `Support::PyRandom` in the same order, the
      # depth-sort is stable exactly as CPython's `sorted` is, and every
      # interpolated number reproduces the Python f-string / `round()` text.
      module Lsystem
        # [bg, trunk, branch, leaf, bloom, sky-glow]
        PALETTES = {
          "verdant" => ["#0e1a12", "#4a3327", "#3e6b48", "#8bbf6f", "#f2e9c9", "#1b3326"].freeze,
          "autumn" => ["#1a1410", "#4a2f20", "#8a4b2f", "#d98324", "#f2c14e", "#2a1d14"].freeze,
          "sakura" => ["#171320", "#3d2b3d", "#5a4466", "#c98bb9", "#f7d6e6", "#241b2e"].freeze,
          "frost" => ["#0b1420", "#2a3b4a", "#3e6b7a", "#8bbfd6", "#e8f1f2", "#152532"].freeze,
        }.freeze

        DEFAULT_PALETTE = "verdant"

        # axiom, rules, base angle (deg), iterations, step length
        RULESETS = {
          "bush" => ["X", { "X" => "F+[[X]-X]-F[-FX]+X", "F" => "FF" }.freeze, 22.5, 4, 13.0].freeze,
          "fern" => ["X", { "X" => "F-[[X]+X]+F[+FX]-X", "F" => "FF" }.freeze, 20.0, 4, 13.0].freeze,
          "tree" => ["F", { "F" => "FF+[+F-F-F]-[-F+F+F]" }.freeze, 25.0, 4, 9.0].freeze,
          "weed" => ["F", { "F" => "F[+F]F[-F][F]" }.freeze, 22.0, 4, 8.0].freeze,
        }.freeze

        DEFAULT_SPECIES = "bush"

        W = 900
        H = 1100
        M = 90

        HALF = Rational(1, 2)
        private_constant :HALF

        # `math.radians(x)` is `x * (pi/180.0)` with the constant folded first;
        # replicate that association so the angle matches to the last ULP.
        DEG2RAD = Math::PI / 180.0
        private_constant :DEG2RAD

        class << self
          def expand(axiom, rules, iters)
            s = axiom
            iters.times { s = s.each_char.map { |c| rules.fetch(c, c) }.join }
            s
          end

          def interpret(s, angle, step, jitter, rng)
            x = 0.0
            y = 0.0
            a = -90.0
            stack = []
            segs = []
            tips = []
            s.each_char do |c|
              case c
              when "F"
                na = a + rng.uniform(-jitter, jitter)
                nx = x + (step * Math.cos(na * DEG2RAD))
                ny = y + (step * Math.sin(na * DEG2RAD))
                segs << [x, y, nx, ny, stack.length]
                x = nx
                y = ny
                a = na
              when "+"
                a += angle + rng.uniform(-jitter, jitter)
              when "-"
                a -= angle + rng.uniform(-jitter, jitter)
              when "["
                stack << [x, y, a]
              when "]"
                tips << [x, y, stack.length]
                x, y, a = stack.pop
              when "X"
                tips << [x, y, stack.length]
              end
            end
            [segs, tips]
          end

          # Returns the finished SVG document, newline-terminated.
          def build(seed, species, palette, iters_override = nil)
            rng = Support::PyRandom.new(seed)
            axiom, rules, angle, iters, step = RULESETS.fetch(species)
            # Python `if iters_override:` is falsy for both nil AND 0, so a
            # `--iters 0` keeps the ruleset default just as the original does.
            iters = iters_override if iters_override && !iters_override.zero?
            pal = PALETTES.fetch(palette)
            jitter = 3.0 + (rng.random * 5.0)
            segs, tips = interpret(expand(axiom, rules, iters), angle, step, jitter, rng)
            segs = [[0, 0, 0, -10, 0]] if segs.empty?

            xs = segs.flat_map { |s| [s[0], s[2]] }
            ys = segs.flat_map { |s| [s[1], s[3]] }
            minx = xs.min
            maxx = xs.max
            miny = ys.min
            maxy = ys.max
            span_x = [maxx - minx, 1e-6].max
            span_y = [maxy - miny, 1e-6].max
            # Python `/` is true division throughout; fdiv guards the fallback
            # path where a span can still be an Integer.
            scale = [(W - (2 * M)).fdiv(span_x), (H - (2 * M)).fdiv(span_y)].min
            ox = ((W - (span_x * scale)) / 2) - (minx * scale)
            oy = H - M - (maxy * scale) # base sits near the bottom margin

            tx = ->(x) { round_repr(ox + (x * scale), 1) }
            ty = ->(y) { round_repr(oy + (y * scale), 1) }

            maxd = segs.map { |s| s[4] }.max || 1
            parts = [
              %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 #{W} #{H}" role="img" ) +
                %(stroke-linecap="round">),
              "<title>L-system #{species}, seed #{seed}, palette #{palette}</title>",
              %(<rect width="#{W}" height="#{H}" fill="#{pal[0]}"/>),
              %(<ellipse cx="#{W / 2}" cy="#{(H * 0.34).to_i}" rx="#{W / 2}" ry="#{(H * 0.34).to_i}" ) +
                %(fill="#{pal[5]}" opacity="0.6"/>),
              %(<ellipse cx="#{W / 2}" cy="#{H - 40}" rx="#{(W * 0.42).to_i}" ry="34" ) +
                %(fill="#{pal[1]}" opacity="0.5"/>),
            ]

            # Trunk-first (shallow depth first) so deep twigs don't occlude it.
            # CPython's `sorted` is stable; pairing each seg with its index and
            # sorting by [depth, index] reproduces that order (Ruby's sort_by
            # is not stable on its own).
            stable_by_depth(segs).each do |x1, y1, x2, y2, d|
              t = d.fdiv(maxd)
              color = t < 0.28 ? pal[1] : (t < 0.62 ? pal[2] : pal[3])
              w = round_repr([0.6, 11 * ((1 - t)**1.7)].max, 2)
              parts << %(<line x1="#{tx.call(x1)}" y1="#{ty.call(y1)}" ) +
                       %(x2="#{tx.call(x2)}" y2="#{ty.call(y2)}" ) +
                       %(stroke="#{color}" stroke-width="#{w}"/>)
            end

            # Foliage at tips: most leaves, a seeded fraction blooms.
            tips.each do |x, y, d|
              next if d < 2

              r = round_val(rng.uniform(3.5, 7.0) * [scale, 1.0].min * 3, 1)
              if rng.random < 0.16
                parts << %(<circle cx="#{tx.call(x)}" cy="#{ty.call(y)}" r="#{fmt(r * 1.1, 1)}" ) +
                         %(fill="#{pal[4]}" opacity="0.95"/>)
              else
                parts << %(<circle cx="#{tx.call(x)}" cy="#{ty.call(y)}" r="#{fmt(r, 1)}" ) +
                         %(fill="#{pal[3]}" opacity="0.75"/>)
              end
            end

            parts << "</svg>"
            parts.join("\n") + "\n"
          end

          private

          def stable_by_depth(segs)
            segs.each_with_index.sort_by { |s, i| [s[4], i] }.map(&:first)
          end

          # Python's `round(x, n)` as a Float (round-half-to-even on the exact
          # binary value); equal to `float(f"{x:.Nf}")`.
          def round_val(value, places)
            Float(fmt(value, places))
          end

          # Bare `{round(x, n)}` interpolation prints the rounded double's
          # shortest round-tripping repr. Ruby's Float#to_s matches CPython's
          # repr for this magnitude range (coordinates < 1e4, stroke widths).
          def round_repr(value, places)
            round_val(value, places).to_s
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

  mod = Zer0ImageGenerator::Svg::Generators::Lsystem
  opts = { seed: 1, species: mod::DEFAULT_SPECIES, palette: mod::DEFAULT_PALETTE,
           iters: nil, out: ".sweep/lsystem.svg" }
  argv = ARGV.dup
  until argv.empty?
    flag = argv.shift
    val = argv.shift
    case flag
    when "--seed" then opts[:seed] = Integer(val)
    when "--species" then opts[:species] = val
    when "--palette" then opts[:palette] = val
    when "--iters" then opts[:iters] = Integer(val)
    when "--out" then opts[:out] = val
    else raise ArgumentError, "unknown flag #{flag.inspect}"
    end
  end

  dir = File.dirname(opts[:out])
  FileUtils.mkdir_p(dir.empty? ? "." : dir)
  svg = mod.build(opts[:seed], opts[:species], opts[:palette], opts[:iters])
  File.write(opts[:out], svg)
  puts opts[:out]
end
