# frozen_string_literal: true

require "minitest/autorun"
require "yaml"
require_relative "../../lib/zer0_cms/cms/front_matter"

class TestFrontMatterParse < Minitest::Test
  FM = Zer0Cms::Cms::FrontMatter

  def test_parse_extracts_keys_body_and_raw_values
    doc = FM.parse("---\ntitle: Hello\ndate: '2025-11-29T16:46:02.000Z'\nn: 3\ndraft: false\ntags: [a]\n---\nBody line\n")
    assert_equal({ "title" => "Hello", "date" => "2025-11-29T16:46:02.000Z", "n" => 3, "draft" => false, "tags" => ["a"] }, doc.data)
    assert_equal "Body line\n", doc.body
    assert_equal "title: Hello\ndate: '2025-11-29T16:46:02.000Z'\nn: 3\ndraft: false\ntags: [a]\n", doc.raw
    assert_equal({ "title" => "Hello", "date" => "2025-11-29T16:46:02.000Z", "n" => "3", "draft" => "false" }, doc.raw_values)
    assert_equal "---", doc.fence_style
    assert_equal "\n", doc.newline
    refute doc.bom
    assert_empty doc.errors
    assert doc.front_matter?
  end

  def test_unquoted_dates_are_typed_but_raw_values_keep_the_text
    doc = FM.parse("---\ndate: 2025-09-03T12:00:00.000Z\nday: 2026-01-01\n---\n")
    assert_kind_of Time, doc.data["date"]
    assert_kind_of Date, doc.data["day"]
    assert_equal "2025-09-03T12:00:00.000Z", doc.raw_values["date"]
    assert_equal "2026-01-01", doc.raw_values["day"]
  end

  def test_bom_crlf_and_dot_fence
    doc = FM.parse("﻿---\r\ntitle: A\r\n...\r\nBody\r\n")
    assert doc.bom
    assert_equal "\r\n", doc.newline
    assert_equal "...", doc.fence_style
    assert_equal({ "title" => "A" }, doc.data)
    assert_equal "Body\r\n", doc.body
  end

  def test_no_block_and_unclosed_block_are_not_front_matter
    [ "Body\n", "---\ntitle: x\nno closing fence\n", "" ].each do |text|
      doc = FM.parse(text, strict: true)
      refute doc.front_matter?, text.inspect
      assert_equal({}, doc.data)
      assert_equal text, doc.body
    end
  end

  def test_empty_block_is_an_empty_mapping
    doc = FM.parse("---\n---\nBody\n", strict: true)
    assert doc.front_matter?
    assert_equal({}, doc.data)
  end

  def test_symbol_looking_scalars_stay_strings
    assert_equal({ "title" => ":wave", "tags" => [":ok"] }, FM.parse("---\ntitle: :wave\ntags:\n- :ok\n---\n").data)
  end

  def test_lenient_parse_reports_errors_instead_of_raising
    { "---\ntitle: [x\n---\n" => /SyntaxError/,
      "---\nx: !ruby/object:Object {}\n---\n" => /DisallowedClass/,
      "---\n- a\n- b\n---\n" => /NotAMapping/ }.each do |text, pattern|
      doc = FM.parse(text)
      assert_equal({}, doc.data)
      assert_match pattern, doc.errors.join, text.inspect
    end
  end

  def test_strict_parse_raises_psych_exceptions
    assert_raises(Psych::SyntaxError) { FM.parse("---\ntitle: [x\n---\n", strict: true) }
    assert_raises(Psych::DisallowedClass) { FM.parse("---\nx: !ruby/object:Object {}\n---\n", strict: true) }
    error = assert_raises(FM::NotAMapping) { FM.parse("---\njust a string\n---\n", strict: true) }
    assert_kind_of Psych::Exception, error
  end
end

class TestFrontMatterSurgery < Minitest::Test
  FM = Zer0Cms::Cms::FrontMatter

  # [what, input, changes, expected output]
  CASES = [
    ["rewrites one scalar, keeps comments and the closing fence",
     "---\ntitle: Hello\n# keep me\nauthor: rhea\n---\nBody\n", { "title" => "World" },
     "---\ntitle: World\n# keep me\nauthor: rhea\n---\nBody\n"],
    ["inserts a missing key before the closing fence",
     "---\ntitle: Hello\n---\nBody\n", { "status" => "draft" },
     "---\ntitle: Hello\nstatus: draft\n---\nBody\n"],
    ["inserts after the last content line, before trailing blanks",
     "---\ntitle: Hello\n# tail comment\n\n---\nBody\n", { "status" => "draft" },
     "---\ntitle: Hello\n# tail comment\nstatus: draft\n\n---\nBody\n"],
    ["fills an empty block", "---\n---\nBody\n", { "title" => "T" }, "---\ntitle: T\n---\nBody\n"],
    ["adds a block to a file without one", "Body\n", { "title" => "T" }, "---\ntitle: T\n---\nBody\n"],
    ["replaces a whole indented block sequence",
     "---\ntags:\n  - a\n  - b\n# c\nnext: 1\n---\n", { "tags" => ["x"] },
     "---\ntags:\n  - x\n# c\nnext: 1\n---\n"],
    ["keeps an aligned block sequence and its item quotes",
     "---\ntags:\n- '1100'\n- git\nn: 1\n---\n", { "tags" => %w[1010 git] },
     "---\ntags:\n- '1010'\n- git\nn: 1\n---\n"],
    ["keeps a flow sequence flow, quoting items by YAML rules",
     "---\ntags: [a, b]\n---\n", { "tags" => ["c", "d, e", "yes", "007"] },
     "---\ntags: [c, \"d, e\", \"yes\", \"007\"]\n---\n"],
    ["replaces a folded block scalar and leaves the blank line after it",
     "---\nd: >-\n  text\n  more\n\nnext: 1\n---\n", { "d" => "new" },
     "---\nd: new\n\nnext: 1\n---\n"],
    ["replaces a wrapped plain scalar",
     "---\ndescription: one\n  two\ndate: '2026-07-15'\n---\n", { "description" => "short" },
     "---\ndescription: short\ndate: '2026-07-15'\n---\n"],
    ["replaces a wrapped quoted scalar, keeping its quote style",
     "---\nexcerpt: 'one\n  two'\nn: 1\n---\n", { "excerpt" => "three" },
     "---\nexcerpt: 'three'\nn: 1\n---\n"],
    ["replaces a nested mapping with all its lines",
     "---\nseo:\n  title: a\n  tags:\n  - b\nx: 1\n---\n", { "seo" => { "title" => "c" } },
     "---\nseo:\n  title: c\nx: 1\n---\n"],
    ["writes a multi-line string as a literal block",
     "---\nx: 1\n---\n", { "note" => "line1\nline2\n" },
     "---\nx: 1\nnote: |\n  line1\n  line2\n---\n"],
    ["deletes a key and every duplicate of it",
     "---\ndraft: true\nx: 1\ndraft: false\n---\n", { "draft" => nil }, "---\nx: 1\n---\n"],
    ["deletes a key together with its block",
     "---\ntags:\n- a\n- b\nx: 1\n---\n", { "tags" => nil }, "---\nx: 1\n---\n"],
    ["deleting a key that is not there changes nothing",
     "---\nx: 1\n---\n", { "y" => nil }, "---\nx: 1\n---\n"],
    ["setting a duplicated key rewrites the one the parser reads",
     "---\nt: a\nt: b\n---\n", { "t" => "c" }, "---\nt: a\nt: c\n---\n"],
    ["NULL writes an explicit null", "---\nx: 1\n---\n", { "x" => Zer0Cms::Cms::FrontMatter::NULL }, "---\nx:\n---\n"],
    ["an empty string is written quoted, not as null", "---\nx: 1\n---\n", { "x" => "" }, "---\nx: \"\"\n---\n"],
    ["keeps CRLF line endings on new and rewritten lines",
     "---\r\ntitle: A\r\n---\r\nBody\r\n", { "title" => "B", "tags" => ["a"] },
     "---\r\ntitle: B\r\ntags:\r\n  - a\r\n---\r\nBody\r\n"],
    ["keeps a BOM and edits the block after it",
     "﻿---\ntitle: A\n---\n", { "title" => "B" }, "﻿---\ntitle: B\n---\n"],
    ["keeps a `...` closing fence", "---\ntitle: A\n...\nBody\n", { "title" => "B" }, "---\ntitle: B\n...\nBody\n"],
    ["a raw date equal to the file is not a change",
     "---\ndate: 2025-09-03T12:00:00.000Z\n---\n", { "date" => "2025-09-03T12:00:00.000Z" },
     "---\ndate: 2025-09-03T12:00:00.000Z\n---\n"],
    ["a single-quoted date stays single-quoted",
     "---\ndate: '2025-11-29T16:46:02.000Z'\n---\n", { "date" => "2025-12-01T00:00:00.000Z" },
     "---\ndate: '2025-12-01T00:00:00.000Z'\n---\n"],
    ["a plain date given back as text stays a plain date",
     "---\ndate: 2025-09-03\n---\n", { "date" => "2025-10-03" }, "---\ndate: 2025-10-03\n---\n"],
    ["a boolean given back as text stays a boolean",
     "---\ndraft: false\n---\n", { "draft" => "true" }, "---\ndraft: true\n---\n"],
    ["Date, Time and numbers are written as YAML reads them",
     "---\nx: 1\n---\n", { "at" => Time.utc(2026, 1, 2, 3, 4, 5), "day" => Date.new(2026, 1, 2), "f" => 1.5 },
     "---\nx: 1\nat: 2026-01-02T03:04:05Z\nday: 2026-01-02\nf: 1.5\n---\n"]
  ].freeze

  def test_surgery_table
    CASES.each do |what, input, changes, expected|
      output = FM.update_keys(input, changes)
      assert_equal expected, output, what
      FM.parse(output, strict: true)
    end
  end

  def test_an_empty_or_equal_change_set_returns_the_text_itself
    text = "---\ntitle: Hello\n---\nBody\n"
    assert_same text, FM.update_keys(text, {})
    assert_same text, FM.update_keys(text, "title" => "Hello")
  end

  # value => the scalar it must be written as
  QUOTING = {
    "plain words" => "plain words",
    "a:b" => "a:b",
    "Yes" => '"Yes"', "no" => '"no"', "on" => '"on"', "off" => '"off"', "null" => '"null"', "~" => '"~"',
    "true" => '"true"', "2026" => '"2026"', "007" => '"007"', "1.5" => '"1.5"', "1:30" => '"1:30"',
    "2026-01-01" => '"2026-01-01"', "[Draft] Terminal" => '"[Draft] Terminal"', "*wildcard*" => '"*wildcard*"',
    "&anchor" => '"&anchor"', "!tag" => '"!tag"', "@handle" => '"@handle"', "`tick`" => '"`tick`"',
    "% pct" => '"% pct"', "\#{x}" => '"#{x}"', "a: b" => '"a: b"', "a #b" => '"a #b"', " lead" => '" lead"',
    "trail " => '"trail "', "- item" => '"- item"', "? q" => '"? q"', ":wave:" => '":wave:"',
    "mid\\slash \"q\"" => 'mid\\slash "q"', "\"q\" back\\slash" => '"\\"q\\" back\\\\slash"', "tab\there" => '"tab\\there"', "bell\a" => '"bell\\u0007"'
  }.freeze

  def test_scalars_are_quoted_by_yaml_rules
    QUOTING.each do |value, written|
      output = FM.update_keys("---\nx: 1\n---\n", "k" => value)
      assert_equal "---\nx: 1\nk: #{written}\n---\n", output, value.inspect
      assert_equal value, YAML.safe_load(output.lines[1..-2].join)["k"], value.inspect
    end
  end

  def test_refuses_to_guess
    [
      ["---\ntitle: x\nno closing fence\n", { "title" => "y" }],
      ["---\ntitle: [x\n---\n", { "title" => "y" }],
      ["---\n{a: 1}\n---\n", { "b" => 2 }],
      ["---\n- a\n---\n", { "b" => 2 }]
    ].each do |text, changes|
      assert_raises(FM::EditError, text.inspect) { FM.update_keys(text, changes) }
    end
  end

  def test_dump_builds_a_block
    assert_equal "---\ntitle: \"Yes\"\ndate: 2026-01-02\n---\n", FM.dump("title" => "Yes", "date" => Date.new(2026, 1, 2))
  end
end

# Real front matter copied from the sister sites (test/fixtures/front_matter/).
class TestFrontMatterRealFiles < Minitest::Test
  FM = Zer0Cms::Cms::FrontMatter
  DIR = File.expand_path("../fixtures/front_matter", __dir__)
  SENTINEL = "zer0-sentinel"

  def fixture(name) = File.read(File.join(DIR, name))

  def as_changes(data) = data.transform_values { |v| v.nil? ? FM::NULL : v }

  def test_every_fixture_round_trips
    Dir[File.join(DIR, "*.md")].each do |path|
      text = File.read(path)
      doc = FM.parse(text, strict: true)
      refute_empty doc.data, path
      assert_equal text, FM.update_keys(text, as_changes(doc.data)), "#{path}: no-op must be byte-identical"
      doc.data.each do |key, value|
        moved = FM.update_keys(text, key => SENTINEL)
        back = FM.update_keys(moved, key => (value.nil? ? FM::NULL : value))
        assert FM.same_value?(doc.data, FM.parse(back, strict: true).data), "#{path}: #{key} did not re-emit"
        assert_equal FM.update_keys(text, key => nil), FM.update_keys(back, key => nil), "#{path}: #{key} moved other lines"
      end
    end
  end

  def test_lifehacker_flow_lists_and_sources
    text = fixture("lifehacker-wire-dispatch.md")
    out = FM.update_keys(text, "tags" => %w[news ai], "sources" => ["https://example.com/a", "https://example.com/b?x=1#frag"])
    assert_includes out, "\ntags: [news, ai]\n"
    assert_includes out, "\nsources:\n  - https://example.com/a\n  - https://example.com/b?x=1#frag\n---\n"
    assert_includes out, "\ncategories: [The Wire]\n"
    assert out.end_with?("---\nStub body copied for tests; the front matter above is real.\n")
    assert_equal ["https://example.com/a", "https://example.com/b?x=1#frag"], FM.parse(out).data["sources"]
  end

  def test_it_journey_wrapped_scalars_and_aligned_lists
    text = fixture("it-journey-quest-report.md")
    out = FM.update_keys(text, "description" => "One line now.", "tags" => %w[walkthrough 0101])
    assert_includes out, "\ndescription: One line now.\ndate: '2026-07-15T12:13:59.000Z'\n"
    assert_includes out, "\ntags:\n- walkthrough\n- '0101'\nrender_with_liquid: false\n"
    doc = FM.parse(out, strict: true)
    assert_equal "0101", doc.data["tags"].last
    assert_equal "2026-07-15T12:13:59.000Z", doc.data["date"]
  end

  def test_it_journey_nested_maps
    text = fixture("it-journey-quest.md")
    original = FM.parse(text).data
    deps = { "required_quests" => [], "unlocks_quests" => ["/quests/1010/elk-stack/"] }
    out = FM.update_keys(text, "quest_dependencies" => deps, "prerequisites" => nil)
    data = FM.parse(out, strict: true).data
    assert_equal deps, data["quest_dependencies"]
    refute data.key?("prerequisites")
    assert_equal original.except("quest_dependencies", "prerequisites"), data.except("quest_dependencies")
  end

  def test_zer0_mistakes_block_lists_and_typed_dates
    text = fixture("zer0-mistakes-post.md")
    doc = FM.parse(text)
    assert_same text, FM.update_keys(text, "date" => doc.raw_values["date"], "lastmod" => doc.raw_values["lastmod"])
    out = FM.update_keys(text, "tags" => %w[jekyll themes], "lastmod" => "2026-09-14T00:00:00.000Z")
    assert_includes out, "\ntags:\n  - jekyll\n  - themes\ndate: 2025-01-01T08:00:00.000Z\n"
    assert_includes out, "\nlastmod: 2026-09-14T00:00:00.000Z\n"
    assert_kind_of Time, FM.parse(out).data["lastmod"]
  end

  def test_it_journey_nulls
    text = fixture("it-journey-note-nulls.md")
    out = FM.update_keys(text, "excerpt" => nil)
    refute_includes out, "\nexcerpt:"
    assert_equal text.sub("excerpt: null\n", ""), out
  end
end
