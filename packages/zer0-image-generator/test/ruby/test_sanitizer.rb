# frozen_string_literal: true

# Security-property tests for the SVG sanitizer.
#
#     ruby -Ilib test/ruby/test_sanitizer.rb
#
# The sanitized STRING is intentionally not byte-identical to Python's
# ElementTree output (REXML orders attributes and quotes differently), so this
# proves the SECURITY CONTRACT instead: everything the Python strips, this
# strips; everything it keeps, this keeps; and it forces the banner geometry.
# A differential check confirms the warnings list matches the oracle exactly,
# and that both engines agree on what to accept vs reject.

require "minitest/autorun"
require "rexml/document"

require_relative "../../lib/zer0_image_generator/svg/sanitizer"
require_relative "../../lib/zer0_image_generator/svg/local_renderer"

class TestSanitizer < Minitest::Test
  S = Zer0ImageGenerator::Svg::Sanitizer
  LR = Zer0ImageGenerator::Svg::LocalRenderer
  Err = Zer0ImageGenerator::Svg::SvgError

  REPO_ROOT = File.expand_path("../..", __dir__)
  ENGINE_DIR = File.join(REPO_ROOT, "lib", "zer0_image_generator")
  COMMITTED_BANNER = File.join(REPO_ROOT, "docs", "showcase", "variants", "banner-hello-world.svg")

  def python3?
    @python3 ||= system("python3", "--version",
                        out: File::NULL, err: File::NULL) ? :yes : :no
    @python3 == :yes
  end

  # sanitize_svg via the oracle; returns [clean_or_nil, warnings_or_nil, error]
  def oracle_sanitize(svg)
    require "json"
    require "tempfile"
    driver = <<~PYTHON
      import sys, json
      sys.path.insert(0, #{ENGINE_DIR.inspect})
      import preview_generator as pg
      svg = open(sys.argv[1], encoding="utf-8").read()
      try:
          clean, warns = pg.sanitize_svg(svg)
          json.dump({"clean": clean, "warns": warns, "error": None}, open(sys.argv[2], "w"))
      except pg.SvgError as e:
          json.dump({"clean": None, "warns": None, "error": str(e)}, open(sys.argv[2], "w"))
    PYTHON
    inp = Tempfile.new(["in", ".svg"])
    out = Tempfile.new(["out", ".json"])
    drv = Tempfile.new(["drv", ".py"])
    begin
      inp.write(svg); inp.flush
      drv.write(driver); drv.flush
      system("python3", drv.path, inp.path, out.path, out: File::NULL, err: File::NULL)
      data = JSON.parse(File.read(out.path))
      [data["clean"], data["warns"], data["error"]]
    ensure
      [inp, out, drv].each { |f| f.close; f.unlink }
    end
  end

  MALICIOUS = <<~SVG.freeze
    <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">
      <script>alert(1)</script>
      <foreignObject><div>x</div></foreignObject>
      <iframe src="http://x"/><audio/><video/>
      <image href="data:image/png;base64,AAAA"/>
      <rect onload="steal()" onmouseover="x()" fill="url(http://evil/#g)" stroke="url(#ok)"/>
      <a xlink:href="http://external">link</a>
      <a href="#local-anchor">ok</a>
      <g style="fill:url(http://bad); background:url(#fine)">t</g>
      <style>@import url(http://cdn); .a{fill:url(http://bad2)} .b{fill:url(#good)}</style>
    </svg>
  SVG

  def test_strips_all_dangerous_content
    clean, warns = S.sanitize_svg(MALICIOUS)

    refute_match(/<script/i, clean, "script survived")
    refute_match(/foreignObject/i, clean, "foreignObject survived")
    refute_match(/<iframe/i, clean, "iframe survived")
    refute_match(/<audio/i, clean, "audio survived")
    refute_match(/<video/i, clean, "video survived")
    refute_match(/<image/i, clean, "image survived")
    refute_match(/onload/i, clean, "onload handler survived")
    refute_match(/onmouseover/i, clean, "onmouseover handler survived")
    refute_includes clean, "http://external", "external href survived"
    refute_includes clean, "http://evil", "external url() in presentation attr survived"
    refute_includes clean, "http://bad", "external url() in style attr survived"
    refute_includes clean, "http://cdn", "@import in <style> survived"
    refute_includes clean, "http://bad2", "external url() in <style> survived"

    # Local references must be preserved untouched.
    assert_includes clean, "url(#ok)", "local url() was wrongly scrubbed"
    assert_includes clean, "#local-anchor", "local anchor href was wrongly removed"
    assert_includes clean, "url(#fine)", "local url() in style attr scrubbed"
    assert_includes clean, "url(#good)", "local url() in <style> scrubbed"

    assert_kind_of Array, warns
    assert_includes warns, "removed <script>"
    assert_includes warns, "removed onload handler"
    assert_includes warns, "removed external href"
  end

  def test_forces_banner_geometry
    clean, = S.sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5 5" width="5" height="5"></svg>')
    doc = REXML::Document.new(clean)
    assert_equal "0 0 1536 1024", doc.root.attributes["viewBox"]
    assert_equal "1536", doc.root.attributes["width"]
    assert_equal "1024", doc.root.attributes["height"]
  end

  def test_rejects_doctype_and_entity
    err = assert_raises(Err) { S.sanitize_svg("<!DOCTYPE svg><svg xmlns='http://www.w3.org/2000/svg'/>") }
    assert_match(/DOCTYPE\/ENTITY/, err.message)
    # billion-laughs shape must be rejected before the parser ever sees it.
    bomb = %(<!DOCTYPE lolz [<!ENTITY lol "lol">]><svg>&lol;</svg>)
    assert_raises(Err) { S.sanitize_svg(bomb) }
  end

  def test_rejects_non_svg_root
    err = assert_raises(Err) { S.sanitize_svg("<html xmlns='http://www.w3.org/1999/xhtml'/>") }
    assert_match(/not <svg>/, err.message)
  end

  def test_rejects_unparseable
    assert_raises(Err) { S.sanitize_svg("<svg><unclosed></svg>") }
    assert_raises(Err) { S.sanitize_svg("not xml at all") }
  end

  def test_nested_banned_elements_are_removed
    # A <script> buried inside a <g> must still be stripped (depth-first scrub).
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><g><g><script>x</script><rect/></g></g></svg>'
    clean, warns = S.sanitize_svg(svg)
    refute_match(/<script/i, clean)
    assert_includes warns, "removed <script>"
    assert_includes clean, "<rect", "sibling of a removed element must survive"
  end

  # The local renderer's own output is the house style — it must survive the
  # sanitizer completely untouched (zero warnings). This is the svg.md contract.
  def test_clean_local_render_survives_untouched
    raw = LR.render_local_svg("hello-world", LR.seed_for("hello-world"))
    _clean, warns = S.sanitize_svg(raw)
    assert_empty warns, "a clean local banner must sanitize with no warnings"
  end

  # Provenance: Ruby's render -> sanitize output is SEMANTICALLY identical to
  # the committed banner (produced by the Python pipeline). The serialized
  # bytes differ by XML engine, but the drawing does not: same geometry, same
  # title, same element census.
  def test_matches_committed_banner_semantically
    skip "committed banner missing" unless File.file?(COMMITTED_BANNER)
    raw = LR.render_local_svg("hello-world", LR.seed_for("hello-world"))
    clean, = S.sanitize_svg(raw)
    assert_equal summarize(REXML::Document.new(File.read(COMMITTED_BANNER))),
                 summarize(REXML::Document.new(clean)),
                 "render+sanitize diverged from the committed banner"
  end

  def summarize(doc)
    root = doc.root
    tags = Hash.new(0)
    root.each_recursive { |e| tags[e.name] += 1 }
    {
      viewBox: root.attributes["viewBox"],
      width: root.attributes["width"],
      height: root.attributes["height"],
      title: REXML::XPath.first(root, "//title")&.text,
      tags: tags.sort.to_h,
    }
  end

  # Differential: warnings list and accept/reject verdict must match the oracle
  # exactly, even though the serialized strings differ by engine.
  def test_warnings_and_verdict_match_oracle
    skip "python3 not available" unless python3?
    samples = [
      MALICIOUS,
      '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#111"/></svg>',
      '<svg xmlns="http://www.w3.org/2000/svg"><g onclick="x"/></svg>',
      "<!DOCTYPE svg><svg/>",
      "<html/>",
      "<svg><bad></svg>",
    ]
    samples.each do |svg|
      py_clean, py_warns, py_err = oracle_sanitize(svg)
      begin
        rb_clean, rb_warns = S.sanitize_svg(svg)
        assert_nil py_err, "oracle rejected but ruby accepted: #{svg[0, 40].inspect}"
        # Warnings are appended in the same traversal order in both engines.
        assert_equal py_warns, rb_warns, "warnings diverged for #{svg[0, 40].inspect}"
        # Semantic equivalence: both must parse and carry the forced geometry.
        assert_equal "0 0 1536 1024", REXML::Document.new(rb_clean).root.attributes["viewBox"]
        refute_nil py_clean
      rescue Err
        refute_nil py_err, "ruby rejected but oracle accepted: #{svg[0, 40].inspect}"
      end
    end
  end
end
