# frozen_string_literal: true

# Differential test: svg/text_to_paths.rb vs the Python oracle
# (preview_generator.py's "SVG text → paths" section).
#
#   ruby -Ilib test/ruby/test_text_to_paths.rb
#
# Geometry is pinned BYTE-FOR-BYTE (path data, advances via Python repr()).
# Documents are pinned on what the walk produces — d strings, aria labels and
# counts in document order — not on serialized bytes (REXML ≠ ElementTree).

require "minitest/autorun"
require "json"
require "open3"
require_relative "../../lib/zer0_image_generator/svg/text_to_paths"

class TestTextToPaths < Minitest::Test
  T = Zer0ImageGenerator::Svg::TextToPaths
  ORACLE = File.expand_path("text_to_paths_oracle.py", __dir__)
  NS = 'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1536 1024"'

  FMT = [0.0, -0.001, 1.006, 2.5, -3.0, -2.344, -2.346, 12.999, 0.07, 1234.5678, -0.004, 99.995].freeze

  RUNS = [
    ["inter-bold", "Hi", 10.0, 100.0, 48.0, 0.0, ""],
    ["inter", "Chandrayaan-1 — India’s “First”", 0.0, 900.0, 72.0, 1.5, "middle"],
    ["inter", "Ünïcödé àccents ÉÀü", 33.3, 512.25, 37.0, 0.0, "central"],
    ["press-start-2p", "BEAR STEARNS", 768.0, 160.0, 56.0, 4.0, "hanging"],
    ["press-start-2p", "a\u4e2db c", -12.5, 0.0, 20.0, 0.0, "text-bottom"],
    ["inter-bold", "Bear Stearns Collapses Into JPMorgan's Arms", 46.08, 1000.0, 96.0, -2.0, ""],
  ].freeze

  FITS = [
    ["press-start-2p", "Chandrayaan-1 India's First Lunar Probe", 600.0, 3, 64.0, 24.0, 0.0],
    ["inter-bold", "Chandrayaan-1: India's First Lunar Probe Reaches the Moon", 1320.96, 3, 96.0, 40.0, 307.2],
    ["inter-bold", "A B C D E F G H", 200.0, 3, 120.0, 20.0, 200.0],
    ["inter-bold", "Supercalifragilisticexpialidocious antidisestablishmentarianism", 300.0, 2, 80.0, 40.0, 0.0],
    ["inter", "", 500.0, 3, 64.0, 24.0, 0.0],
  ].freeze

  DOCS = [
    [%(<svg #{NS}><text x="768" y="900" font-family="Inter" font-weight="700" font-size="72" text-anchor="middle" fill="#e8f1f2">Chandrayaan-1 Reaches the Moon</text></svg>), "paths", "inter"],
    [%(<svg #{NS}><style>.h{font-family:'Press Start 2P';font-size:40px} text{fill:#ff0}</style><text class="h" x="10" y="100">HI</text></svg>), "paths", "inter"],
    [%(<svg #{NS}><text x="100" y="100" font-size="40" fill="#111">A <tspan fill="#f00" font-weight="bold">B</tspan><tspan x="100" dy="1.5em">C  D</tspan>\n  <tspan dx="12" dy="-3">E</tspan></text></svg>), "paths", "inter"],
    [%(<svg #{NS}><text x="768" y="500" font-size="200" text-anchor="middle">An absurdly long headline that cannot fit</text></svg>), "paths", "inter"],
    [%(<svg #{NS}><g transform="translate(10 20)" font-family="Press Start 2P"><text font-size="3em" letter-spacing="2" dominant-baseline="middle" y="80">Pixel</text></g></svg>), "paths", "inter"],
    [%(<svg #{NS}><text x="10" y="100" font-size="40">Edge</text><text x="1500" y="200" font-size="60" text-anchor="start">Off the right</text></svg>), "paths", "press-start-2p"],
    [%(<svg #{NS}><text x="0" y="50" style="font-size:24pt;fill:#abc;opacity:.5" font-family="Helvetica, Inter">Inline <tspan style="font-weight:800">bold</tspan></text></svg>), "paths", "inter"],
    [%(<svg #{NS}><text x="0" y="50">gone</text><rect width="1" height="1"/></svg>), "forbid", "inter"],
  ].freeze

  def oracle
    @oracle ||= begin
      query = {
        fmt: FMT,
        runs: RUNS.map { |f, t, x, y, s, ls, b| { family: f, text: t, x: x, y: y, size: s, ls: ls, baseline: b } },
        fits: FITS.map { |f, t, w, l, mx, mn, h| { family: f, text: t, width: w, lines: l, max: mx, min: mn, height: h } },
        docs: DOCS.map { |svg, mode, fam| { svg: svg, mode: mode, family: fam } },
      }
      out, status = Open3.capture2("python3", ORACLE, stdin_data: JSON.generate(query))
      skip "python3 oracle unavailable" unless status.success?
      JSON.parse(out)
    end
  end

  # Python repr() of a float — what the oracle prints for advances.
  def py_repr(value)
    s = value.to_s
    s = s.sub(/e\+?/, "e+").sub("e+-", "e-") if s.include?("e")
    s
  end

  def test_fmt2_matches
    assert_equal oracle["fmt"], FMT.map { |v| T.fmt2(v) }
  end

  def test_font_metrics_match
    T::BUNDLED_FONTS.each_key do |family|
      f = T.load_font(family)
      assert_equal oracle["metrics"][family],
                   [f.units_per_em, f.ascender, f.descender, f.x_height, f.cmap.length, f.num_glyphs], family
    end
  end

  def test_glyph_runs_are_byte_identical
    RUNS.each_with_index do |(family, text, x, y, size, ls, baseline), i|
      font = T.load_font(family)
      d, advance, missing = T.glyph_run_path(font, text, x, y, size, ls)
      expected = oracle["runs"][i]
      assert_equal expected["d"], d, "path data, run #{i} (#{text})"
      assert_equal expected["advance"], py_repr(advance), "advance, run #{i}"
      assert_equal expected["missing"], missing, "missing, run #{i}"
      assert_equal expected["width"], py_repr(T.text_advance(font, text, size, ls)), "width, run #{i}"
      assert_equal expected["shift"], py_repr(T.baseline_shift(font, baseline, size)), "shift, run #{i}"
    end
  end

  def test_fit_headline_matches
    FITS.each_with_index do |(family, text, width, lines, max, min, height), i|
      got_lines, size = T.fit_headline(T.load_font(family), text, width, lines, max, min, max_height: height)
      assert_equal oracle["fits"][i]["lines"], got_lines, "fit #{i}"
      assert_equal oracle["fits"][i]["size"], py_repr(size), "fit size #{i}"
    end
  end

  def test_documents_convert_identically
    DOCS.each_with_index do |(svg, mode, family), i|
      r = T.svg_text_to_paths(svg, mode, family)
      got = {
        "d" => r.svg.scan(/\sd=['"]([^'"]*)['"]/).flatten,
        "labels" => r.svg.scan(/aria-label=['"]([^'"]*)['"]/).flatten,
        "converted" => r.converted, "stripped" => r.stripped, "fitted" => r.fitted,
        "missing" => r.missing_glyphs, "notes" => r.notes,
      }
      assert_equal oracle["docs"][i], got, "document #{i}"
      refute_match(/<text\b/, r.svg, "document #{i} still carries <text>") unless mode == "keep"
    end
  end

  def test_keep_is_a_no_op
    svg = %(<svg #{NS}><text>kept</text></svg>)
    assert_equal svg, T.svg_text_to_paths(svg, "keep").svg
  end
end
