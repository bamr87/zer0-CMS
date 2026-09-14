# frozen_string_literal: true

require "minitest/autorun"
require "fileutils"
require "tmpdir"
require_relative "../../lib/zer0_cms/cms/catalog"

class TestCatalog < Minitest::Test
  def test_scan_lists_posts_with_front_matter
    Dir.mktmpdir do |dir|
      File.write(File.join(dir, "_config.yml"), "title: t\ncollections_dir: pages\n")
      FileUtils.mkdir_p(File.join(dir, "pages", "_posts"))
      File.write(
        File.join(dir, "pages", "_posts", "2026-01-01-hello.md"),
        "---\ntitle: Hello\nauthor: rhea\ncategories: [Hacks]\ntags: [ci]\ndraft: false\n---\nBody\n"
      )
      result = Zer0Cms::Cms::Catalog.scan(dir)
      assert_includes result.collections, "posts"
      assert_equal 1, result.total
      entry = result.entries.first
      assert_equal "Hello", entry.title
      assert_equal "rhea", entry.author
      assert_equal ["Hacks"], entry.categories
      assert_equal ["ci"], entry.tags
      refute entry.draft
    end
  end
end
