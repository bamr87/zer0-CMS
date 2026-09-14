# frozen_string_literal: true

require "minitest/autorun"
require_relative "../../lib/zer0_cms/cms/front_matter"

class TestFrontMatter < Minitest::Test
  include Zer0Cms::Cms

  def test_parse_extracts_keys_and_body
    raw = "---\ntitle: Hello\ndraft: false\n---\nBody line\n"
    doc = FrontMatter.parse(raw)
    assert_equal "Hello", doc.data["title"]
    assert_equal false, doc.data["draft"]
    assert_equal "Body line\n", doc.body
  end

  def test_update_keys_rewrites_only_changed_lines
    raw = "---\ntitle: Hello\n# keep me\nauthor: rhea\n---\nBody\n"
    out = FrontMatter.update_keys(raw, "title" => "World")
    assert_includes out, "title: World\n"
    assert_includes out, "# keep me\n"
    assert_includes out, "author: rhea\n"
    assert_includes out, "Body\n"
    refute_includes out, "title: Hello"
  end

  def test_update_keys_appends_missing_key
    raw = "---\ntitle: Hello\n---\nBody\n"
    out = FrontMatter.update_keys(raw, "status" => "draft")
    assert_includes out, "status: draft\n"
    assert_includes out, "title: Hello\n"
  end
end
