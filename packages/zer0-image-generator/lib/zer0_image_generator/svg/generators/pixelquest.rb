# frozen_string_literal: true

require_relative "../../support/py_random"
# See invaders.rb for why the PixelKit load is guarded.
require_relative "../pixel_kit" unless defined?(Zer0ImageGenerator::Svg::PixelKit)

module Zer0ImageGenerator
  module Svg
    module Generators
      # Side-scroller vignette — port of `tools/svg/examples/pixelquest.py`.
      #
      # A knight, a slime, coins, a crate, and a goal flag under a blocky sunset.
      # Hand-designed sprites, seeded layout: the seed drives terrain, star and
      # coin placement, and where the cast stands.
      #
      # Byte-identity contract: `docs/samples/pixel-quest-dusk-7.svg` and the
      # `docs/showcase/variants/pixel-quest-*.svg` were produced here. The
      # terrain random-walk and starfield draw values in a precise order — a
      # color pick only fires when a star is actually placed — so the stream
      # must be reproduced draw-for-draw.
      module PixelQuest
        HERO = [
          "...cc...",
          "..cccc..",
          ".hhhhhh.",
          ".hfefeh.",
          ".hffffh.",
          "..aaaa..",
          ".gaaaag.",
          ".gaaaag.",
          "..a..a..",
          "..b..b..",
          "..b..b..",
        ].freeze

        SLIME = [
          "..ssss..",
          ".ssssss.",
          "ssssssss",
          "ss.ss.ss",
          "ssssssss",
        ].freeze

        COIN = [
          ".##.",
          "#oo#",
          "#oo#",
          ".##.",
        ].freeze

        CRATE = [
          "######",
          "#o##o#",
          "######",
          "######",
          "#o##o#",
          "######",
        ].freeze

        FLAG = [
          "pff.",
          "pfff",
          "pff.",
          "p...",
          "p...",
          "p...",
          "p...",
          "p...",
          "p...",
          "p...",
        ].freeze

        DEFAULT_PALETTE = "dusk"

        # Coin arc over the crate, not confetti: (dx, dy) offsets.
        COIN_ARC = [[-6, 10], [0, 12], [6, 10]].freeze

        class << self
          def build(seed, palette = DEFAULT_PALETTE)
            rng = Support::PyRandom.new(seed)
            pal = Svg::PixelKit::PALETTES.fetch(palette)
            canvas = Svg::Canvas.new(64, 40, px: 16, bg: pal[0])
            ground_top = 34

            # Stars, thinning toward the horizon. The color draw is inside the
            # branch — only placed stars consume it.
            60.times do
              col = rng.randrange(64)
              row = rng.randrange(24)
              if rng.random < (1.0 - (row / 24.0))
                canvas.set(col, row, rng.random < 0.7 ? pal[1] : pal[2])
              end
            end

            # Blocky setting sun
            sun_x = 40 + rng.randrange(12)
            canvas.disc(sun_x, 9, 5.2, pal[4])
            canvas.disc(sun_x, 9, 3.4, pal[5])

            # Stepped far hills, then near hills (random walk, engine-style)
            [[26, pal[1]], [30, pal[2]]].each do |base, color|
              col = 0
              level = base - rng.randrange(3)
              while col < 64
                width = 3 + rng.randrange(5)
                canvas.fill(col, level, width, ground_top - level, color)
                col += width
                level = [base - 6, [base, level + rng.choice([-2, -1, 1, 2])].min].max
              end
            end

            # Brick ground with staggered mortar and a lit cap row
            canvas.fill(0, ground_top, 64, 6, pal[2])
            (ground_top...40).each do |row|
              64.times do |col|
                if row.odd? && ((col + (3 * (row / 2))) % 6).zero?
                  canvas.set(col, row, pal[1])
                end
              end
            end
            canvas.fill(0, ground_top, 64, 1, pal[4])

            # The cast
            hero_col = 10 + rng.randrange(6)
            canvas.blit(HERO, { "c" => pal[3], "h" => pal[5], "f" => pal[4], "e" => pal[0],
                                "a" => pal[5], "g" => pal[5], "b" => pal[3] },
                        hero_col, ground_top - 11)
            canvas.blit(SLIME, { "s" => pal[3] }, 38 + rng.randrange(6), ground_top - 5)
            crate_col = 27
            canvas.blit(CRATE, { "#" => pal[4], "o" => pal[1] }, crate_col, ground_top - 6)
            canvas.blit(FLAG, { "p" => pal[5], "f" => pal[3] }, 58, ground_top - 10)
            # Coin arc over the crate, not confetti
            COIN_ARC.each do |dx, dy|
              canvas.blit(COIN, { "#" => pal[4], "o" => pal[5] },
                          crate_col + 1 + dx, ground_top - dy - 4)
            end

            canvas.to_svg("Pixel quest, seed #{seed}, palette #{palette}", crt: true)
          end
        end
      end
    end
  end
end
