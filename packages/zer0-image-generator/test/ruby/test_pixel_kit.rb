# frozen_string_literal: true

# Tests for the retro pixel-art toolkit port (lib/zer0_image_generator/svg/pixel_kit.rb).
#
#     ruby -Ilib test/ruby/test_pixel_kit.rb
#
# Three layers:
#   1. A differential test that drives BOTH the Python oracle
#      (tools/svg/pixelkit.py) and this port through the identical scripted API
#      sequence — every palette, hmirror in both modes, an ASCII blit, the
#      run-length merge (adjacent same-color cells collapsing, a different
#      color splitting the run), disc, off-grid set, title escaping, and the
#      CRT veil on and off — and asserts byte-identical SVG. Skips if python3
#      is unavailable.
#   2. A golden test that reproduces the committed invaders/pixelquest artwork
#      (which was emitted through pixelkit) with this Canvas + PyRandom and
#      asserts byte-identity, proving the library against real output with no
#      python at all.
#   3. Focused unit assertions on hmirror and the run-merge edge cases.

require "minitest/autorun"
require "open3"
require "tempfile"
require_relative "../../lib/zer0_image_generator/svg/pixel_kit"
require_relative "../../lib/zer0_image_generator/support/py_random"

module Zer0ImageGenerator
  module Svg
    class PixelKitDifferentialTest < Minitest::Test
      REPO = File.expand_path("../..", __dir__)

      # The authoritative driver. The Ruby scenes below mirror it op for op; the
      # byte comparison is what keeps them honest.
      HARNESS = <<~PY
        import os, sys
        sys.path.insert(0, os.path.join(os.environ["REPO"], "tools", "svg"))
        from pixelkit import Canvas, PALETTES, hmirror

        SEP = "\\n===SCENE===\\n"
        HALF = ["#.", "##", "#.", ".#"]

        def scenes():
            out = []
            for idx, name in enumerate(PALETTES):
                pal = PALETTES[name]
                c = Canvas(12, 9, px=7, bg=pal[0])
                body = hmirror(HALF)
                wings = hmirror(HALF, shared_center=False)
                c.blit(body, {"#": pal[5]}, 1, 1)
                c.blit(wings, {"#": pal[3]}, 6, 4)
                c.fill(0, 8, 5, 1, pal[2])
                c.fill(5, 8, 4, 1, pal[2])
                c.set(9, 8, pal[4])
                c.set(10, 8, pal[2])
                c.set(-1, 0, pal[1])
                c.set(11, 0, pal[1])
                c.disc(3, 5, 2.4, pal[4])
                out.append(c.to_svg(f'Kit {name} & <friends> "q"', crt=(idx % 2 == 0)))
            return out

        sys.stdout.write(SEP.join(scenes()))
      PY

      SEP = "\n===SCENE===\n"
      HALF = ["#.", "##", "#.", ".#"].freeze

      def python3?
        @python3 ||= system("python3", "--version", out: File::NULL, err: File::NULL)
      end

      def ruby_scenes
        PixelKit::PALETTES.each_with_index.map do |(name, pal), idx|
          c = Canvas.new(12, 9, px: 7, bg: pal[0])
          body = PixelKit.hmirror(HALF)
          wings = PixelKit.hmirror(HALF, shared_center: false)
          c.blit(body, { "#" => pal[5] }, 1, 1)
          c.blit(wings, { "#" => pal[3] }, 6, 4)
          c.fill(0, 8, 5, 1, pal[2])
          c.fill(5, 8, 4, 1, pal[2])
          c.set(9, 8, pal[4])
          c.set(10, 8, pal[2])
          c.set(-1, 0, pal[1])
          c.set(11, 0, pal[1])
          c.disc(3, 5, 2.4, pal[4])
          c.to_svg(%(Kit #{name} & <friends> "q"), crt: idx.even?)
        end.join(SEP)
      end

      def test_api_output_is_byte_identical_to_the_oracle
        skip "python3 not available" unless python3?

        harness = Tempfile.new(["pk_harness", ".py"])
        harness.write(HARNESS)
        harness.close

        py_out, py_err, status = Open3.capture3(
          { "REPO" => REPO }, "python3", harness.path, chdir: REPO
        )
        assert status.success?, "python harness failed: #{py_err}"

        assert_equal py_out, ruby_scenes
      ensure
        harness&.unlink
      end
    end

    # Proves Canvas + PALETTES + hmirror against the committed pixel artwork by
    # reproducing the invaders/pixelquest generators here (they are not part of
    # this slice, so their logic lives in the test) through PyRandom.
    class PixelKitGoldenTest < Minitest::Test
      REPO = File.expand_path("../..", __dir__)
      PyRandom = Zer0ImageGenerator::Support::PyRandom

      SHIP = [".....#.....", "....l#l....", ".l.l###l.l.", "###########", "l#l#l#l#l#l"].freeze
      BUNKER = [".########.", "##########", "##########", "###....###", "##......##"].freeze
      MINI_SHIP = ["..#..", ".###.", "#####"].freeze
      BOOM = ["#..#.#..#", ".#..#..#.", "..#####..", ".#..#..#.", "#..#.#..#"].freeze

      HERO = ["...cc...", "..cccc..", ".hhhhhh.", ".hfefeh.", ".hffffh.",
              "..aaaa..", ".gaaaag.", ".gaaaag.", "..a..a..", "..b..b..", "..b..b.."].freeze
      SLIME = ["..ssss..", ".ssssss.", "ssssssss", "ss.ss.ss", "ssssssss"].freeze
      COIN = [".##.", "#oo#", "#oo#", ".##."].freeze
      CRATE = ["######", "#o##o#", "######", "######", "#o##o#", "######"].freeze
      FLAG = ["pff.", "pfff", "pff.", "p...", "p...", "p...", "p...", "p...", "p...", "p..."].freeze

      def alien(rng, half_w = 6, height = 8)
        loop do
          rows = Array.new(height) do
            (0...half_w).map { rng.random < 0.55 ? "#" : "." }.join
          end
          mass = rows.sum { |r| r.count("#") }
          return PixelKit.hmirror(rows) if 0.35 * half_w * height <= mass && mass <= 0.75 * half_w * height
        end
      end

      def build_invaders(seed, palette)
        rng = PyRandom.new(seed)
        pal = PixelKit::PALETTES[palette]
        c = Canvas.new(64, 48, px: 12, bg: pal[0])
        70.times do
          col = rng.randrange(64)
          row = rng.randrange(44)
          c.set(col, row, rng.random < 0.6 ? pal[1] : pal[2]) if rng.random < (1.0 - row / 44.0) * 0.8
        end
        species = Array.new(3) { alien(rng) }
        rank_color = [pal[5], pal[4], pal[3]]
        hit = [rng.randrange(3), rng.randrange(5)]
        3.times do |rank|
          5.times do |i|
            col = 1 + (i * 13)
            row = 5 + (rank * 10)
            if [rank, i] == hit
              c.blit(BOOM, { "#" => pal[4] }, col + 1, row + 1)
            else
              c.blit(species[rank], { "#" => rank_color[rank] }, col, row)
            end
          end
        end
        shot_col = 1 + (rng.randrange(5) * 13) + 5
        c.fill(shot_col, 33, 1, 3, pal[5])
        3.times { |i| c.blit(BUNKER, { "#" => pal[2] }, 5 + (i * 22), 36) }
        c.blit(SHIP, { "#" => pal[4], "l" => pal[3] }, 26, 41)
        c.fill(0, 46, 64, 1, pal[2])
        3.times { |i| c.blit(MINI_SHIP, { "#" => pal[2] }, 2 + (i * 7), 1) }
        c.to_svg("Invader wave, seed #{seed}, palette #{palette}", crt: true)
      end

      def build_pixelquest(seed, palette)
        rng = PyRandom.new(seed)
        pal = PixelKit::PALETTES[palette]
        c = Canvas.new(64, 40, px: 16, bg: pal[0])
        ground_top = 34
        60.times do
          col = rng.randrange(64)
          row = rng.randrange(24)
          c.set(col, row, rng.random < 0.7 ? pal[1] : pal[2]) if rng.random < (1.0 - row / 24.0)
        end
        sun_x = 40 + rng.randrange(12)
        c.disc(sun_x, 9, 5.2, pal[4])
        c.disc(sun_x, 9, 3.4, pal[5])
        [[26, pal[1]], [30, pal[2]]].each do |base, color|
          col = 0
          level = base - rng.randrange(3)
          while col < 64
            width = 3 + rng.randrange(5)
            c.fill(col, level, width, ground_top - level, color)
            col += width
            level = [base - 6, [base, level + rng.choice([-2, -1, 1, 2])].min].max
          end
        end
        c.fill(0, ground_top, 64, 6, pal[2])
        (ground_top...40).each do |row|
          (0...64).each do |col|
            c.set(col, row, pal[1]) if row.odd? && (col + (3 * (row / 2))) % 6 == 0
          end
        end
        c.fill(0, ground_top, 64, 1, pal[4])
        hero_col = 10 + rng.randrange(6)
        c.blit(HERO, { "c" => pal[3], "h" => pal[5], "f" => pal[4], "e" => pal[0],
                       "a" => pal[5], "g" => pal[5], "b" => pal[3] }, hero_col, ground_top - 11)
        c.blit(SLIME, { "s" => pal[3] }, 38 + rng.randrange(6), ground_top - 5)
        crate_col = 27
        c.blit(CRATE, { "#" => pal[4], "o" => pal[1] }, crate_col, ground_top - 6)
        c.blit(FLAG, { "p" => pal[5], "f" => pal[3] }, 58, ground_top - 10)
        [[-6, 10], [0, 12], [6, 10]].each do |dx, dy|
          c.blit(COIN, { "#" => pal[4], "o" => pal[5] }, crate_col + 1 + dx, ground_top - dy - 4)
        end
        c.to_svg("Pixel quest, seed #{seed}, palette #{palette}", crt: true)
      end

      # Every committed .svg whose <title> marks it as a pixelkit scene, keyed
      # to the builder that made it. Reproducing from the title means new
      # samples are covered automatically. Only docs/ (the tracked determinism
      # contract) is scanned; .sweep/ is gitignored scratch that can predate a
      # generator change, so it is not a valid oracle.
      def pixel_samples
        Dir[File.join(REPO, "docs/**/*.svg")].sort.filter_map do |path|
          title = File.foreach(path).find { |l| l.include?("<title>") }
          case title
          when /<title>Invader wave, seed (\d+), palette (\w+)</
            [path, :invaders, Regexp.last_match(1).to_i, Regexp.last_match(2)]
          when /<title>Pixel quest, seed (\d+), palette (\w+)</
            [path, :pixelquest, Regexp.last_match(1).to_i, Regexp.last_match(2)]
          end
        end
      end

      def test_committed_pixel_artwork_reproduces_byte_for_byte
        samples = pixel_samples
        refute_empty samples, "expected committed invaders/pixelquest SVGs"

        samples.each do |path, kind, seed, palette|
          got = kind == :invaders ? build_invaders(seed, palette) : build_pixelquest(seed, palette)
          assert_equal File.binread(path), got, "byte mismatch reproducing #{path}"
        end
      end
    end

    class PixelKitUnitTest < Minitest::Test
      def test_hmirror_shared_center_folds_on_last_column
        assert_equal ["#.#", "###"], PixelKit.hmirror(["#.", "##"])
      end

      def test_hmirror_full_doubles_every_column
        assert_equal ["#..#", "####"], PixelKit.hmirror(["#.", "##"], shared_center: false)
      end

      def test_hmirror_handles_single_and_empty_rows
        assert_equal ["#", ""], PixelKit.hmirror(["#", ""])
      end

      def test_run_merge_collapses_and_splits
        c = Canvas.new(6, 1, px: 1, bg: "#000")
        c.fill(0, 0, 3, 1, "#f00")
        c.fill(3, 0, 2, 1, "#f00") # abuts -> one run
        c.set(5, 0, "#0f0")        # different color -> its own run
        rects = c.to_svg("t").scan(/<rect [^>]*fill="#(?!000")[^"]*"\/>/)
        assert_equal 2, rects.length
        assert_includes rects[0], %(width="5")
        assert_includes rects[1], %(width="1")
      end

      def test_blit_missing_color_raises
        c = Canvas.new(4, 1, px: 1)
        assert_raises(KeyError) { c.blit(["x"], { "#" => "#fff" }, 0, 0) }
      end

      def test_off_grid_writes_ignored
        c = Canvas.new(2, 2, px: 1, bg: "#000")
        c.set(-1, 0, "#fff")
        c.set(5, 5, "#fff")
        refute_includes c.to_svg("t"), "#fff"
      end
    end
  end
end
