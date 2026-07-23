# frozen_string_literal: true

require_relative "../../support/py_random"

module Zer0ImageGenerator
  module Svg
    module Generators
      # Parametric flow-field — port of `tools/svg/examples/flowfield.py`.
      #
      # Seed a cloud of particles, then walk each one downstream through a
      # value-noise field, emitting the trail as a polyline. The canonical
      # "generator with knobs": lines/steps/scale/palette are the only dials,
      # every coordinate falls out of the seeded stream.
      #
      # The committed artwork under `docs/samples/flowfield-*.svg` and
      # `docs/showcase/variants/flowfield-*.svg` was produced by the Python
      # original, so this port is pinned to byte-identical output: every draw
      # comes off `Support::PyRandom` in the same order the Python drew it, and
      # every interpolated number is formatted to the same width the f-strings
      # used.
      module Flowfield
        PALETTES = {
          "ember" => ["#1a1423", "#f24236", "#f5a623", "#f7e8d3"].freeze,
          "cyanic" => ["#0b132b", "#1c7293", "#5bc0be", "#e8f1f2"].freeze,
          "moss" => ["#16211b", "#3e6b48", "#a3c9a8", "#e9edc9"].freeze,
        }.freeze

        DEFAULT_PALETTE = "cyanic"

        # Python's `math.tau` is the precomputed double 2*pi; `Math::PI * 2` is
        # the identical bit pattern, so `angle` matches to the last ULP.
        TAU = Math::PI * 2

        HALF = Rational(1, 2)
        private_constant :HALF

        class << self
          # Cheap hash-based value noise with bilinear interpolation. Returns a
          # callable sampler; the hash is pure integer arithmetic so it ports
          # directly — Ruby and CPython agree on `>>`, `&`, and `^` for the
          # negative lattice coordinates `math.floor` can produce.
          def value_noise(seed)
            hash = lambda do |ix, iy|
              n = (ix * 374_761_393) + (iy * 668_265_263) + (seed * 1_442_695_040_888_963_407)
              n = (n ^ (n >> 13)) * 1_274_126_177
              # `/ 0xFFFF` is true division in Python; fdiv keeps it a Float
              # instead of Ruby's integer division.
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
          def build(seed, w, h, lines, steps, scale, palette)
            rng = Support::PyRandom.new(seed)
            noise = value_noise(seed)
            colors = PALETTES.fetch(palette)
            out = []

            lines.times do
              x = rng.uniform(0, w)
              y = rng.uniform(0, h)
              pts = [[x, y]]
              steps.times do
                angle = noise.call(x / scale, y / scale) * TAU * 2
                x += Math.cos(angle) * 4
                y += Math.sin(angle) * 4
                break unless -20 < x && x < w + 20 && -20 < y && y < h + 20

                pts << [x, y]
              end
              # Too-short trails are dropped BEFORE their stroke/width/opacity
              # draws — mirroring Python's `continue`, so the RNG stays in sync.
              next if pts.length < 8

              d = "M" + pts.map { |px, py| "#{fmt(px, 0)},#{fmt(py, 0)}" }.join(" L")
              stroke = rng.choice(colors[1..])
              width = rng.uniform(0.4, 2.4)
              op = rng.uniform(0.25, 0.8)
              out << %(<path d="#{d}" fill="none" stroke="#{stroke}" ) +
                     %(stroke-width="#{fmt(width, 2)}" stroke-opacity="#{fmt(op, 2)}" ) +
                     %(stroke-linecap="round"/>)
            end

            %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 #{w} #{h}" ) +
              "role=\"img\">\n" \
              "  <title>Flow field, seed #{seed}, palette #{palette}</title>\n" +
              %(  <rect width="#{w}" height="#{h}" fill="#{colors[0]}"/>) + "\n  " +
              out.join("\n  ") + "\n</svg>\n"
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
        end
      end
    end
  end
end

if __FILE__ == $PROGRAM_NAME
  require "fileutils"

  opts = { seed: 1, out: "art/flowfield.svg", width: 800, height: 800,
           lines: 240, steps: 70, scale: 180.0,
           palette: Zer0ImageGenerator::Svg::Generators::Flowfield::DEFAULT_PALETTE }
  argv = ARGV.dup
  until argv.empty?
    flag = argv.shift
    val = argv.shift
    case flag
    when "--seed" then opts[:seed] = Integer(val)
    when "--out" then opts[:out] = val
    when "--width" then opts[:width] = Integer(val)
    when "--height" then opts[:height] = Integer(val)
    when "--lines" then opts[:lines] = Integer(val)
    when "--steps" then opts[:steps] = Integer(val)
    when "--scale" then opts[:scale] = Float(val)
    when "--palette" then opts[:palette] = val
    else raise ArgumentError, "unknown flag #{flag.inspect}"
    end
  end

  dir = File.dirname(opts[:out])
  FileUtils.mkdir_p(dir.empty? ? "." : dir)
  svg = Zer0ImageGenerator::Svg::Generators::Flowfield.build(
    opts[:seed], opts[:width], opts[:height], opts[:lines],
    opts[:steps], opts[:scale], opts[:palette]
  )
  File.write(opts[:out], svg)
  puts opts[:out]
end
