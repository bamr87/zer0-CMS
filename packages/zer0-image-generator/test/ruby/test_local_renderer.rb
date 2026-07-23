# frozen_string_literal: true

# Differential byte-identity test for the deterministic local banner renderer.
#
#     ruby -Ilib test/ruby/test_local_renderer.rb
#
# The Python preview_generator.render_local_svg is the ORACLE: for a wide,
# varied set of slugs this shells out to python3 and asserts the Ruby output
# is BYTE-IDENTICAL. render_local_svg is a HARD determinism contract — same
# slug must produce the same banner in either language, or committed artwork
# drifts. The seed -> palette/composition scheme is checked the same way over
# a wide integer range. Skips cleanly (never fails) when python3 is absent;
# runs for real here (python3 3.14 + PyYAML installed).

require "minitest/autorun"
require "json"
require "tempfile"
require "zlib"

require_relative "../../lib/zer0_image_generator/svg/local_renderer"

class TestLocalRenderer < Minitest::Test
  LR = Zer0ImageGenerator::Svg::LocalRenderer

  REPO_ROOT = File.expand_path("../..", __dir__)
  ENGINE_DIR = File.join(REPO_ROOT, "lib", "zer0_image_generator")

  # Python driver: reads {"slugs":[...],"seeds":[...]} and emits the oracle's
  # render_local_svg / seed_for / palette_for / composition_for results.
  PY_DRIVER = <<~PYTHON
    import sys, json
    sys.path.insert(0, #{ENGINE_DIR.inspect})
    import preview_generator as pg
    req = json.load(open(sys.argv[1]))
    out = {
        "renders": [pg.render_local_svg(s, pg.seed_for(s)) for s in req["slugs"]],
        "seeds_for": [pg.seed_for(s) for s in req["slugs"]],
        "palettes": [pg.palette_for(n) for n in req["seeds"]],
        "compositions": [pg.composition_for(n) for n in req["seeds"]],
    }
    json.dump(out, open(sys.argv[2], "w"))
  PYTHON

  def python3?
    @python3 ||= system("python3", "--version",
                        out: File::NULL, err: File::NULL) ? :yes : :no
    @python3 == :yes
  end

  # Curated edge slugs + a broad generated spread. >= 200 varied slugs, hitting
  # empty-ish, unicode, very long, whitespace/escaped, and the sample slug.
  def slugs
    curated = [
      "hello-world",                 # the committed banner-hello-world.svg slug
      "getting-started",             # the docs fixture slug
      "", " ", "  ", "\t", "\n", "a", "z", "0", "-", "_", "..", "/", "//",
      "a b", "a/b/c", "a&b", "a<b>c", "&<>&<>",
      "café", "über-café", "naïve", "façade", "Москва", "日本語のタイトル",
      "emoji-🚀-banner", "🎮🕹️👾", "mixed 日本 & <x> café",
      "UPPER", "MiXeD-CaSe", "trailing-space ", " leading",
      "tab\tinside", "new\nline", "amp&only", "lt<only",
      "x" * 2000,                    # very long
      "y" * 511, "z" * 3,
      "constellation", "starmap-5", "ridgeline", "dawn-badge",
      "invaders-magma-5", "lowpoly-dusk-5", "mandala-ocean-11",
      "pixel-quest-dusk-7", "lsystem-tree-sakura-7", "flowfield-moss-5",
    ]
    generated = []
    (0...260).each do |i|
      # Vary shape so seeds scatter across palette (%10) and variant (>>8 %8).
      generated << "post-#{i}"
      generated << "2026-#{format('%02d', (i % 12) + 1)}-#{format('%02d', (i % 28) + 1)}-entry-#{i}"
    end
    curated + generated
  end

  def seeds
    wide = (0...3000).to_a
    edges = [
      0, 1, 255, 256, 257, 65_535, 65_536,
      2**31 - 1, 2**31, 2**32 - 1, 2**32 - 256,
      0xFFFF_FF00, 0x0000_0100, 0xDEAD_BEEF, 0xCAFE_BABE, 1_103_515_245,
    ]
    wide + edges
  end

  def run_oracle(slug_list, seed_list)
    req = Tempfile.new(["req", ".json"])
    res = Tempfile.new(["res", ".json"])
    drv = Tempfile.new(["driver", ".py"])
    begin
      req.write(JSON.generate(slugs: slug_list, seeds: seed_list))
      req.flush
      drv.write(PY_DRIVER)
      drv.flush
      ok = system("python3", drv.path, req.path, res.path,
                  out: File::NULL, err: File::NULL)
      assert ok, "python3 oracle driver failed"
      JSON.parse(File.read(res.path))
    ensure
      [req, res, drv].each { |f| f.close; f.unlink }
    end
  end

  def test_render_local_svg_byte_identical_across_slugs
    skip "python3 not available" unless python3?
    all = slugs
    assert_operator all.length, :>=, 200, "need >= 200 varied slugs"

    oracle = run_oracle(all, [])
    py_renders = oracle["renders"]
    py_seeds = oracle["seeds_for"]

    diverged = []
    variant_parities = []
    palette_indices = []
    all.each_with_index do |slug, i|
      ruby_seed = LR.seed_for(slug)
      assert_equal py_seeds[i], ruby_seed, "seed_for diverged for #{slug.inspect}"
      ruby_svg = LR.render_local_svg(slug, ruby_seed)
      diverged << slug unless ruby_svg == py_renders[i]
      variant_parities << ((ruby_seed >> 8) % 8).even?
      palette_indices << (ruby_seed % 10)
    end

    assert_empty diverged,
                 "render_local_svg diverged for #{diverged.length} slug(s): " \
                 "#{diverged.first(5).map(&:inspect).join(', ')}"

    # Prove both variant branches (grid floor vs starfield) and a spread of
    # palettes were actually exercised by the byte-identity comparison.
    assert_includes variant_parities, true, "no even-variant slug exercised"
    assert_includes variant_parities, false, "no odd-variant slug exercised"
    assert_operator palette_indices.uniq.length, :>=, 8,
                    "palette coverage too narrow to be meaningful"

    # Report the exact count proved identical (visible with -v / on failure).
    proved = all.length - diverged.length
    assert_equal all.length, proved
  end

  def test_seed_palette_composition_agree_over_wide_range
    skip "python3 not available" unless python3?
    seed_list = seeds
    oracle = run_oracle([], seed_list)
    py_palettes = oracle["palettes"]
    py_comps = oracle["compositions"]

    seed_list.each_with_index do |seed, i|
      assert_equal py_palettes[i], LR.palette_for(seed),
                   "palette_for diverged at seed=#{seed}"
      assert_equal py_comps[i], LR.composition_for(seed),
                   "composition_for diverged at seed=#{seed}"
    end
  end

  # seed_for is zlib.crc32 of the UTF-8 bytes — independent of python.
  def test_seed_for_matches_zlib_crc32
    assert_equal Zlib.crc32("hello-world"), LR.seed_for("hello-world")
    assert_equal 0, LR.seed_for(""), "crc32 of the empty string is 0 (unsigned)"
    assert_operator LR.seed_for("café"), :>=, 0, "crc32 must be a non-negative unsigned int"
  end

  # Zero seed (crc32 of the empty slug is not 0, but guard the documented
  # `seed or 1` path directly) must not freeze the LCG into an all-zero banner.
  def test_zero_seed_uses_one
    svg = LR.render_local_svg("anything", 0)
    refute_includes svg, 'cx="1216"', "zero seed should still advance the LCG"
    assert svg.start_with?("<svg ")
  end
end
