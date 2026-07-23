# frozen_string_literal: true

require_relative "../../support/py_random"
# The retro pixel toolkit is a sibling slice
# (lib/zer0_image_generator/svg/pixel_kit.rb). Load it unless a caller — a test
# harness pinning byte-identity — has already supplied the namespace; the
# `defined?` guard lets that stub stand in without a second load, and a genuine
# absence still surfaces as an explicit LoadError from require_relative.
require_relative "../pixel_kit" unless defined?(Zer0ImageGenerator::Svg::PixelKit)

module Zer0ImageGenerator
  module Svg
    module Generators
      # Procedural fixed-shooter scene — port of `tools/svg/examples/invaders.py`.
      #
      # Each wave's alien species are *generated*: random cells in a half-grid,
      # mirrored (hmirror) — bilateral symmetry is what makes random blobs read
      # as creatures. One alien is mid-explosion; the symmetry break is the
      # subject.
      #
      # Byte-identity contract: `docs/samples/invaders-*.svg` and
      # `docs/showcase/variants/invaders-dusk-3.svg` were produced here, so every
      # draw must come off `Support::PyRandom` in the Python order. `alien` does
      # rejection sampling, so the number of draws is data-dependent — the
      # density predicate has to match exactly or the whole stream desyncs.
      module Invaders
        SHIP = [
          ".....#.....",
          "....l#l....",
          ".l.l###l.l.",
          "###########",
          "l#l#l#l#l#l",
        ].freeze

        BUNKER = [
          ".########.",
          "##########",
          "##########",
          "###....###",
          "##......##",
        ].freeze

        MINI_SHIP = [
          "..#..",
          ".###.",
          "#####",
        ].freeze

        BOOM = [
          "#..#.#..#",
          ".#..#..#.",
          "..#####..",
          ".#..#..#.",
          "#..#.#..#",
        ].freeze

        DEFAULT_PALETTE = "cyanic"

        class << self
          # Random half-grid, mirrored. Reject sprites too sparse or too dense
          # to read as a creature. The bounds are `0.35..0.75` of the half-grid
          # cell count as floats, compared against the integer mass — mirror the
          # comparison exactly, since a stricter/looser predicate changes how
          # many times the loop redraws and shifts every later value.
          def alien(rng, half_w = 6, height = 8)
            loop do
              rows = Array.new(height) do
                Array.new(half_w) { rng.random < 0.55 ? "#" : "." }.join
              end
              mass = rows.sum { |row| row.count("#") }
              lo = 0.35 * half_w * height
              hi = 0.75 * half_w * height
              return Svg::PixelKit.hmirror(rows) if mass >= lo && mass <= hi
            end
          end

          def build(seed, palette = DEFAULT_PALETTE)
            rng = Support::PyRandom.new(seed)
            pal = Svg::PixelKit::PALETTES.fetch(palette)
            canvas = Svg::Canvas.new(64, 48, px: 12, bg: pal[0])

            # Starfield, sparse and uneven — heavier toward the top. The color
            # draw happens only when the placement test passes; keep it inside
            # the branch so the stream matches.
            70.times do
              col = rng.randrange(64)
              row = rng.randrange(44)
              if rng.random < ((1.0 - (row / 44.0)) * 0.8)
                canvas.set(col, row, rng.random < 0.6 ? pal[1] : pal[2])
              end
            end

            # Three ranks of aliens, one species per rank, 5 across
            species = Array.new(3) { alien(rng) }
            rank_color = [pal[5], pal[4], pal[3]]
            hit = [rng.randrange(3), rng.randrange(5)] # one alien mid-explosion
            3.times do |rank|
              5.times do |i|
                col = 1 + (i * 13)
                row = 5 + (rank * 10)
                if [rank, i] == hit
                  canvas.blit(BOOM, { "#" => pal[4] }, col + 1, row + 1)
                else
                  canvas.blit(species[rank], { "#" => rank_color[rank] }, col, row)
                end
              end
            end

            # A shot on its way up from the player
            shot_col = 1 + (rng.randrange(5) * 13) + 5
            canvas.fill(shot_col, 33, 1, 3, pal[5])

            # Bunkers, ship, ground, lives
            3.times { |i| canvas.blit(BUNKER, { "#" => pal[2] }, 5 + (i * 22), 36) }
            canvas.blit(SHIP, { "#" => pal[4], "l" => pal[3] }, 26, 41)
            canvas.fill(0, 46, 64, 1, pal[2])
            3.times { |i| canvas.blit(MINI_SHIP, { "#" => pal[2] }, 2 + (i * 7), 1) }

            canvas.to_svg("Invader wave, seed #{seed}, palette #{palette}", crt: true)
          end
        end
      end
    end
  end
end
