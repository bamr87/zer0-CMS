# frozen_string_literal: true

# Differential + contract test for the banner-seed adapter (Ruby port of
# tools/svg/banner-seed.py) and its svg-sweep.sh contact-sheet logic.
#
#     ruby -Ilib test/ruby/test_banner_seed.rb
#
# banner-seed.py is the ORACLE. The adapter's job is to reproduce the engine's
# REAL `local` banner — render_local_svg(title, seed) run through the real
# sanitize_svg — so a sweep judges true output, not a lookalike.
#
# WHAT IS PROVEN BYTE-IDENTICAL, and how:
#   * The PRE-sanitize render is byte-identical to the Python adapter's, for
#     80 seeds and ~20 slugs, in both --seed and --slug modes.
#   * The FINAL sanitized string is the SAME DOM but not byte-identical, because
#     the ported Sanitizer serializes via REXML where Python uses ElementTree
#     (a deviation owned by the sanitizer slice). Proven here by canonicalizing
#     BOTH outputs through REXML and asserting equality — including against the
#     REAL banner-seed.py script end-to-end (file bytes, stdout path, stderr
#     notes) for the two documented invocations.
#   * seed_for agrees across languages, so --slug and --seed pick the same seed.
#
# Skips cleanly where python3 is absent; runs for real here (python3 3.14).

require "minitest/autorun"
require "json"
require "open3"
require "tempfile"
require "fileutils"
require "stringio"
require "rexml/document"
require "zlib"

require_relative "../../lib/zer0_image_generator/svg/banner_seed"

class TestBannerSeed < Minitest::Test
  BS = Zer0ImageGenerator::Svg::BannerSeed
  LR = Zer0ImageGenerator::Svg::LocalRenderer

  REPO_ROOT = File.expand_path("../..", __dir__)
  ENGINE_DIR = File.join(REPO_ROOT, "lib", "zer0_image_generator")
  ADAPTER = File.join(REPO_ROOT, "tools", "svg", "banner-seed.py")

  # Replays banner-seed.py's exact core over a batch, in ONE process: for each
  # seed it does `title, seed = f"banner-seed-{n}", n`; for each slug it does
  # `title, seed = slug, seed_for(slug)`; then `sanitize_svg(render_local_svg(
  # title, seed))`. Emits the raw render, the sanitized svg, notes and seed so
  # the Ruby port can be checked at both stages. (banner-seed.py exposes no
  # importable function, so its 4-line body is transcribed, not re-invented.)
  PY_BATCH = <<~PYTHON
    import sys, json
    sys.path.insert(0, #{ENGINE_DIR.inspect})
    import preview_generator as pg
    req = json.load(open(sys.argv[1]))
    def one(title, seed):
        raw = pg.render_local_svg(title, seed)
        svg, notes = pg.sanitize_svg(raw)
        return {"title": title, "seed": seed, "raw": raw, "svg": svg, "notes": notes}
    out = {
        "seed_mode": [one(f"banner-seed-{n}", n) for n in req["seeds"]],
        "slug_mode": [one(s, pg.seed_for(s)) for s in req["slugs"]],
        "seeds_for": [pg.seed_for(s) for s in req["slugs"]],
    }
    json.dump(out, open(sys.argv[2], "w"))
  PYTHON

  def python3?
    @python3 ||= system("python3", "--version",
                        out: File::NULL, err: File::NULL) ? :yes : :no
    @python3 == :yes
  end

  # Parse then reserialize through REXML's Default formatter, normalizing quote
  # style / attribute order / self-closing spacing so ElementTree output and
  # REXML output become comparable. One more fold is needed: REXML echoes parsed
  # text verbatim (a title's literal '>' stays '>'), while ElementTree escapes
  # '>' to '&gt;' in text — the same character either way. Folding '&gt;' to '>'
  # leaves only the true DOM. (No attribute here ever contains '>', so the fold
  # is lossless.)
  def canon(svg)
    out = +""
    REXML::Formatters::Default.new.write(REXML::Document.new(svg).root, out)
    out.gsub("&gt;", ">")
  end

  # >= 50 seeds, chosen to exercise BOTH render branches: seed>>8 is 0 for all
  # of 1..255 (even variant, grid floor), so 256..511 are added to reach the
  # odd variant (starfield). Palette index (seed % 10) is spread by 1..60.
  SEEDS = ((1..60).to_a +
           [256, 257, 300, 400, 511, 700, 900, 1000, 1300,
            65_535, 70_000, 200_000]).freeze
  SLUGS = [
    "my-post",                # the documented --slug example
    "hello-world", "getting-started",
    "café", "über-café", "naïve", "日本語のタイトル", "emoji-🚀-banner",
    "a&b", "a<b>c", "&<>", "UPPER", "MiXeD-CaSe",
    "trailing-space ", " leading", "tab\tinside",
    "post-42", "2026-07-23-entry", "z", "x" * 300,
  ].freeze

  def run_batch(seeds, slugs)
    req = Tempfile.new(["req", ".json"])
    res = Tempfile.new(["res", ".json"])
    drv = Tempfile.new(["drv", ".py"])
    begin
      req.write(JSON.generate(seeds: seeds, slugs: slugs))
      req.flush
      drv.write(PY_BATCH)
      drv.flush
      ok = system("python3", drv.path, req.path, res.path,
                  out: File::NULL, err: File::NULL)
      assert ok, "python3 batch oracle failed"
      JSON.parse(File.read(res.path))
    ensure
      [req, res, drv].each { |f| f.close; f.unlink }
    end
  end

  # ---- byte-identity against banner-seed.py -----------------------------

  def test_seed_mode_matches_oracle
    skip "python3 not available" unless python3?
    assert_operator SEEDS.length, :>=, 50, "need >= 50 seeds"

    oracle = run_batch(SEEDS, [])["seed_mode"]
    raw_ok = dom_ok = 0
    parities = []
    oracle.each_with_index do |row, i|
      seed = SEEDS[i]
      title, resolved = BS.resolve(seed: seed)
      assert_equal "banner-seed-#{seed}", title
      assert_equal seed, resolved, "seed must pass through untouched in --seed mode"

      rb_raw = LR.render_local_svg(title, resolved)
      assert_equal row["raw"], rb_raw, "pre-sanitize render diverged at seed=#{seed}"
      raw_ok += 1

      rb_svg, rb_notes = BS.generate(seed: seed)
      assert_equal row["notes"], rb_notes, "sanitizer notes diverged at seed=#{seed}"
      assert_empty rb_notes, "the local template renders clean; no notes expected"
      assert_equal canon(row["svg"]), canon(rb_svg),
                   "sanitized DOM diverged at seed=#{seed}"
      dom_ok += 1
      parities << ((resolved >> 8) % 8).even?
    end

    assert_equal SEEDS.length, raw_ok
    assert_equal SEEDS.length, dom_ok
    # Both variant branches (grid floor vs starfield) must be in the population.
    assert_includes parities, true, "no even-variant seed exercised"
    assert_includes parities, false, "no odd-variant seed exercised"
  end

  def test_slug_mode_matches_oracle_and_seed_for_agrees
    skip "python3 not available" unless python3?

    batch = run_batch([], SLUGS)
    oracle = batch["slug_mode"]
    py_seeds = batch["seeds_for"]

    raw_ok = dom_ok = 0
    SLUGS.each_with_index do |slug, i|
      # --slug and --seed agree THROUGH seed_for: the adapter derives the seed
      # exactly as the engine (zlib.crc32), so both languages pick the same one.
      rb_seed = BS.seed_for(slug)
      assert_equal py_seeds[i], rb_seed, "seed_for diverged for #{slug.inspect}"
      assert_equal Zlib.crc32(slug), rb_seed
      title, resolved = BS.resolve(slug: slug)
      assert_equal slug, title, "--slug uses the slug itself as the title"
      assert_equal rb_seed, resolved

      rb_raw = LR.render_local_svg(title, resolved)
      assert_equal oracle[i]["raw"], rb_raw, "render diverged for slug #{slug.inspect}"
      raw_ok += 1

      rb_svg, = BS.generate(slug: slug)
      assert_equal canon(oracle[i]["svg"]), canon(rb_svg),
                   "sanitized DOM diverged for slug #{slug.inspect}"
      dom_ok += 1
    end

    assert_equal SLUGS.length, raw_ok
    assert_equal SLUGS.length, dom_ok
  end

  # The real banner-seed.py script, end to end: file bytes (DOM), the stdout
  # path it echoes, and its stderr notes — for the two documented invocations.
  def test_real_script_end_to_end
    skip "python3 not available" unless python3?

    dir = Dir.mktmpdir("banner-seed")
    begin
      [["--seed", "7"], ["--slug", "my-post"]].each do |mode, value|
        py_out = File.join(dir, "py.svg")
        py_stdout, py_stderr, py_status =
          Open3.capture3("python3", ADAPTER, mode, value, "--out", py_out)
        assert py_status.success?, "banner-seed.py failed: #{py_stderr}"
        assert_equal py_out, py_stdout.chomp, "adapter must echo the out path"

        rb_out = File.join(dir, "rb.svg")
        rb_stdout = StringIO.new
        rb_stderr = StringIO.new
        opts = mode == "--seed" ? { seed: Integer(value) } : { slug: value }
        code = BS.main([mode, value, "--out", rb_out], out: rb_stdout, err: rb_stderr)
        assert_equal 0, code

        assert_equal rb_out, rb_stdout.string.chomp
        # Local renders are clean -> no "sanitizer:" notes on either side.
        assert_equal py_stderr, rb_stderr.string
        assert_equal "", rb_stderr.string, "no sanitizer notes expected for local"
        assert_equal canon(File.read(py_out)), canon(File.read(rb_out)),
                     "on-disk banner DOM diverged for #{mode} #{value}"

        # The library API must produce the same file the CLI just wrote.
        assert_equal File.read(rb_out), BS.svg(**opts)
      end
    ensure
      FileUtils.remove_entry(dir)
    end
  end

  # ---- studio API (no shelling out) -------------------------------------

  def test_sweep_and_render_many_shape
    results = BS.sweep(5)
    assert_equal [1, 2, 3, 4, 5], results.map { |r| r[:seed] }
    results.each do |r|
      assert_equal "banner-seed-#{r[:seed]}", r[:title]
      assert r[:svg].start_with?("<svg "), "each entry carries an SVG string"
      assert_equal [], r[:notes]
      assert_equal BS.svg(seed: r[:seed]), r[:svg], "sweep svg == single-seed svg"
    end

    # first: offsets the range like svg-sweep.sh's 1..N does from a base.
    assert_equal [10, 11, 12], BS.sweep(3, first: 10).map { |r| r[:seed] }
    # Arbitrary (non-range) seed sets are what a web form actually submits.
    picked = BS.render_many([3, 99, 7])
    assert_equal [3, 99, 7], picked.map { |r| r[:seed] }
    assert_equal BS.svg(seed: 99), picked[1][:svg]

    assert_equal [], BS.sweep(0)
    assert_raises(ArgumentError) { BS.sweep(-1) }
  end

  def test_write_makes_nested_dirs_and_matches_generate
    dir = Dir.mktmpdir("banner-seed-write")
    begin
      out = File.join(dir, "deep", "nested", "banner.svg")
      err = StringIO.new
      returned = BS.write(out, seed: 3, err: err)
      assert_equal out, returned
      assert File.file?(out), "write must create intermediate directories"
      assert_equal BS.generate(seed: 3).first, File.read(out)
      assert_equal "", err.string, "local render is clean; no notes to stderr"
    ensure
      FileUtils.remove_entry(dir)
    end
  end

  def test_bad_cli_argument_exits_two
    err = StringIO.new
    code = BS.main(["--seed", "not-an-int"], out: StringIO.new, err: err)
    assert_equal 2, code, "argparse exits 2 on a bad argument"
    refute_empty err.string, "the parse error must be reported, not swallowed"
  end

  # ---- svg-sweep.sh contact-sheet logic ---------------------------------

  # ceil(sqrt(N)) — the bash's COLS. Cross-check against the same math.
  def test_tile_columns_is_ceil_sqrt
    (1..50).each do |n|
      assert_equal Math.sqrt(n).ceil, BS.tile_columns(n)
    end
    assert_equal 4, BS.tile_columns(12) # the README's `svg-sweep.sh ... 12`
    assert_equal 3, BS.tile_columns(9)  # perfect square: no float overshoot
  end

  # The montage argv must carry svg-sweep.sh's exact knobs.
  def test_montage_argv_matches_svg_sweep_flags
    pngs = %w[.preview/seed-1.png .preview/seed-2.png .preview/seed-3.png .preview/seed-4.png]
    argv = BS.montage_argv(pngs, out: ".sweep/contact-sheet.png")
    assert_equal(
      ["montage", "-label", "%f", "-background", "#111", "-fill", "#eee",
       "-tile", "2x", "-geometry", "400x400+8+8",
       ".preview/seed-1.png", ".preview/seed-2.png",
       ".preview/seed-3.png", ".preview/seed-4.png",
       ".sweep/contact-sheet.png"],
      argv
    )
    # Columns follow ceil(sqrt(N)); an explicit override wins. The "<cols>x"
    # token sits right after "-tile" (argv index 8).
    assert_equal "-tile", BS.montage_argv(pngs, out: "o.png")[7]
    assert_equal "3x", BS.montage_argv(pngs * 2, out: "o.png")[8] # 8 pngs -> ceil(sqrt 8)=3
    assert_equal "5x", BS.montage_argv(pngs, out: "o.png", columns: 5)[8]
  end

  # The REQUIRED absent-ImageMagick path: this machine has no `montage`.
  def test_contact_sheet_without_montage_fails_actionably
    refute BS.montage_available?, "test host is expected to lack ImageMagick"
    err = assert_raises(BS::MontageMissing) do
      BS.contact_sheet([".preview/seed-1.png"], out: ".sweep/contact-sheet.png")
    end
    assert_match(/montage/i, err.message)
    assert_match(/ImageMagick/i, err.message, "message must name the missing dependency")
  end

  def test_contact_sheet_rejects_empty_when_montage_present
    skip "montage present — empty-input guard is only reachable with ImageMagick" unless BS.montage_available?
    assert_raises(ArgumentError) { BS.contact_sheet([], out: "o.png") }
  end
end
