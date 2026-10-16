# frozen_string_literal: true

# Tests for the SVG -> PNG rasterizer chain.
#
#     ruby -Ilib test/ruby/test_rasterizer.rb
#
# The tool-SELECTION logic (rsvg > inkscape > magick[magick|convert] >
# playwright, with PNG-signature verification and fall-through) is exercised
# with fakes so it does not depend on which binaries are installed. One test
# runs a REAL SVG -> PNG through inkscape (installed here) and asserts a valid
# PNG signature came out.

require "minitest/autorun"
require "tmpdir"
require "stringio"

require_relative "../../lib/zer0_image_generator/svg/rasterizer"
require_relative "../../lib/zer0_image_generator/svg/local_renderer"
require_relative "../../lib/zer0_image_generator/svg/sanitizer"

class TestRasterizer < Minitest::Test
  R = Zer0ImageGenerator::Svg::Rasterizer
  PNG_SIG = Zer0ImageGenerator::Svg::Rasterizer::PNG_SIGNATURE

  def which_stub(*available)
    ->(tool) { available.include?(tool) ? "/fake/bin/#{tool}" : nil }
  end

  # run_quiet fake: records the binary invoked and writes an output PNG whose
  # validity is controlled per-binary via `outcomes` ("valid"/"invalid"/false).
  def run_quiet_stub(png_path, outcomes, calls)
    lambda do |cmd, **_kw|
      calls << cmd[0]
      outcome = outcomes.fetch(cmd[0], "valid")
      return false if outcome == false

      bytes = outcome == "valid" ? (PNG_SIG + "data") : "NOTPNG!!"
      File.binwrite(png_path, bytes)
      true
    end
  end

  def with_tmp
    Dir.mktmpdir do |dir|
      yield File.join(dir, "in.svg"), File.join(dir, "out.png"), dir
    end
  end

  # Minitest 6 dropped Object#stub; swap the module's singleton methods
  # directly (dynamic dispatch means rasterize_svg picks up the fakes) and
  # restore the originals afterward.
  def with_fakes(overrides)
    originals = overrides.keys.to_h { |name| [name, R.method(name)] }
    overrides.each { |name, impl| R.define_singleton_method(name, &impl) }
    yield
  ensure
    originals.each { |name, meth| R.define_singleton_method(name, meth) }
  end

  def test_prefers_rsvg_when_available
    with_tmp do |svg, png, root|
      calls = []
      with_fakes(which: which_stub("rsvg-convert", "inkscape"),
                 run_quiet: run_quiet_stub(png, {}, calls)) do
        assert_equal "rsvg", R.rasterize_svg(svg, png, root)
      end
      assert_equal ["rsvg-convert"], calls, "rsvg-convert must be tried first and win"
    end
  end

  def test_falls_through_to_inkscape_when_rsvg_absent
    with_tmp do |svg, png, root|
      calls = []
      with_fakes(which: which_stub("inkscape"),
                 run_quiet: run_quiet_stub(png, {}, calls)) do
        assert_equal "inkscape", R.rasterize_svg(svg, png, root)
      end
      assert_equal ["inkscape"], calls
    end
  end

  def test_invalid_png_signature_falls_through_to_next_tool
    with_tmp do |svg, png, root|
      calls = []
      # rsvg "succeeds" but emits a non-PNG; the chain must discard it and
      # continue to inkscape, which produces a valid PNG.
      with_fakes(which: which_stub("rsvg-convert", "inkscape"),
                 run_quiet: run_quiet_stub(png, { "rsvg-convert" => "invalid" }, calls)) do
        assert_equal "inkscape", R.rasterize_svg(svg, png, root)
      end
      assert_equal %w[rsvg-convert inkscape], calls
      assert_equal PNG_SIG, File.binread(png)[0, 8], "surviving output must be a real PNG"
    end
  end

  def test_magick_entry_uses_magick_then_convert
    with_tmp do |svg, png, root|
      calls = []
      # Only `convert` present: the magick entry must fall back to it and the
      # returned tool name is still "magick".
      with_fakes(which: which_stub("convert"),
                 run_quiet: run_quiet_stub(png, {}, calls)) do
        assert_equal "magick", R.rasterize_svg(svg, png, root)
      end
      assert_equal ["convert"], calls
    end
  end

  def test_playwright_last_resort
    with_tmp do |svg, png, root|
      calls = []
      # helper resolves to the real vendored rasterize-svg.js; node "present".
      with_fakes(which: which_stub("node"),
                 run_quiet: run_quiet_stub(png, {}, calls)) do
        assert_equal "playwright", R.rasterize_svg(svg, png, root)
      end
      assert_equal ["node"], calls
    end
  end

  def test_returns_nil_when_nothing_available
    with_tmp do |svg, png, root|
      calls = []
      with_fakes(which: which_stub, # nothing installed
                 run_quiet: run_quiet_stub(png, {}, calls)) do
        assert_nil R.rasterize_svg(svg, png, root)
      end
      assert_empty calls, "no run_quiet should fire when no tool resolves"
    end
  end

  def test_preference_none_short_circuits
    with_tmp do |svg, png, root|
      calls = []
      with_fakes(which: which_stub("rsvg-convert"),
                 run_quiet: run_quiet_stub(png, {}, calls)) do
        assert_nil R.rasterize_svg(svg, png, root, preference: "none")
      end
      assert_empty calls, "'none' must not probe any tool"
    end
  end

  def test_preference_pins_a_single_tool
    with_tmp do |svg, png, root|
      calls = []
      # rsvg is available and would normally win, but preference pins inkscape.
      with_fakes(which: which_stub("rsvg-convert", "inkscape"),
                 run_quiet: run_quiet_stub(png, {}, calls)) do
        assert_equal "inkscape", R.rasterize_svg(svg, png, root, preference: "inkscape")
      end
      assert_equal ["inkscape"], calls
    end
  end

  def test_unknown_preference_returns_nil_and_warns
    with_tmp do |svg, png, root|
      out = capture_stderr do
        with_fakes(which: which_stub("rsvg-convert")) do
          assert_nil R.rasterize_svg(svg, png, root, preference: "bogus")
        end
      end
      assert_match(/Unknown rasterizer 'bogus'/, out)
    end
  end

  def test_playwright_helper_resolves_vendored_js
    helper = R.playwright_helper(Dir.pwd)
    refute_nil helper, "the vendored rasterize-svg.js must be found beside the engine"
    assert_equal "rasterize-svg.js", File.basename(helper)
    assert File.file?(helper)
  end

  # Real end-to-end: render -> sanitize -> inkscape -> assert PNG signature.
  def test_real_inkscape_end_to_end
    skip "inkscape not installed" unless R.which("inkscape")
    with_tmp do |svg, png, root|
      raw = Zer0ImageGenerator::Svg::LocalRenderer.render_local_svg(
        "hello-world", Zer0ImageGenerator::Svg::LocalRenderer.seed_for("hello-world")
      )
      clean, = Zer0ImageGenerator::Svg::Sanitizer.sanitize_svg(raw)
      File.write(svg, clean)
      name = R.rasterize_svg(svg, png, root, preference: "inkscape")
      assert_equal "inkscape", name, "inkscape should have produced the PNG"
      assert File.file?(png), "PNG file must exist"
      assert_equal PNG_SIG, File.binread(png)[0, 8], "output must start with the PNG signature"
    end
  end

  def capture_stderr
    original = $stderr
    $stderr = StringIO.new
    yield
    $stderr.string
  ensure
    $stderr = original
  end
end
