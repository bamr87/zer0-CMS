# frozen_string_literal: true

require "minitest/autorun"
require "fileutils"
require "tmpdir"
require_relative "../../lib/zer0_cms/cms/writer"

class TestWriter < Minitest::Test
  Writer = Zer0Cms::Cms::Writer
  FM = Zer0Cms::Cms::FrontMatter

  def site
    Dir.mktmpdir do |dir|
      File.write(File.join(dir, "_config.yml"), "title: t\ncollections_dir: pages\ncollections:\n  docs: {}\n")
      FileUtils.mkdir_p(File.join(dir, "pages/_posts/hacks"))
      FileUtils.mkdir_p(File.join(dir, "pages/_docs"))
      yield File.realpath(dir)
    end
  end

  def test_create_writes_a_dated_post
    site do |dir|
      path = Writer.create(dir, collection: "posts", title: "Hello World", body: "Hi\n", date: Date.new(2026, 9, 14))
      assert_equal File.join(dir, "pages/_posts/2026-09-14-hello-world.md"), path.to_s
      assert_equal "---\ntitle: Hello World\ndate: 2026-09-14\n---\nHi\n", File.read(path)
    end
  end

  def test_create_quotes_titles_by_yaml_rules_and_keeps_a_body_that_looks_like_front_matter
    site do |dir|
      path = Writer.create(dir, collection: "docs", title: "Yes", slug: "yes-page", body: "---\nnot: front matter\n---\n")
      doc = FM.parse(File.read(path), strict: true)
      assert_equal "Yes", doc.data["title"]
      assert_equal "---\nnot: front matter\n---\n", doc.body
    end
  end

  def test_create_into_an_existing_section
    site do |dir|
      path = Writer.create(dir, collection: "posts", section: "hacks", title: "A hack", date: Date.new(2026, 1, 2))
      assert_equal File.join(dir, "pages/_posts/hacks/2026-01-02-a-hack.md"), path.to_s
      assert_raises(ArgumentError) { Writer.create(dir, collection: "posts", section: "missing", title: "x") }
      assert_raises(ArgumentError) { Writer.create(dir, collection: "posts", section: "../_docs", title: "x") }
    end
  end

  def test_unknown_or_traversing_collections_are_refused
    site do |dir|
      ["docs/../../..", "../x", "data", "nope", "", "_docs"].each do |collection|
        assert_raises(ArgumentError, collection) { Writer.create(dir, collection: collection, title: "x") }
      end
    end
  end

  def test_slugs_are_validated_after_transliteration
    site do |dir|
      assert_equal "cafe-creme-brulee", File.basename(Writer.create(dir, collection: "docs", title: "Café Crème Brûlée!").to_s, ".md")
      assert_equal "strasse-aero", File.basename(Writer.create(dir, collection: "docs", title: "x", slug: "Straße-Ærø").to_s, ".md")
      ["../../x", "a/b", "a--b", "-a", "a_b", "..", "💥"].each do |slug|
        assert_raises(ArgumentError, slug) { Writer.create(dir, collection: "docs", title: "x", slug: slug) }
      end
      assert_raises(ArgumentError) { Writer.create(dir, collection: "docs", title: "!!!") }
    end
  end

  def test_slugify_truncates_at_a_word_boundary
    long = "an extraordinarily long title that keeps going well past the sixty character limit"
    slug = Writer.slugify(long)
    assert_operator slug.length, :<=, 60
    assert_equal "an-extraordinarily-long-title-that-keeps-going-well-past-the", slug
    assert_equal "a" * 60, Writer.slugify("a" * 80)
  end

  def test_create_never_overwrites_or_follows_a_symlink
    site do |dir|
      Dir.mktmpdir do |outside|
        target = File.join(outside, "victim.md")
        File.write(target, "original")
        File.symlink(target, File.join(dir, "pages/_docs/planted.md"))
        assert_raises(Zer0Cms::Cms::UnsafePath) { Writer.create(dir, collection: "docs", title: "x", slug: "planted") }
        File.symlink(File.join(outside, "dangling.md"), File.join(dir, "pages/_docs/dangling.md"))
        assert_raises(Zer0Cms::Cms::UnsafePath) { Writer.create(dir, collection: "docs", title: "x", slug: "dangling") }
        refute File.exist?(File.join(outside, "dangling.md"))
        assert_equal "original", File.read(target)
      end
      Writer.create(dir, collection: "docs", title: "Once", slug: "once")
      assert_raises(ArgumentError) { Writer.create(dir, collection: "docs", title: "Twice", slug: "once") }
    end
  end

  def test_create_refuses_a_collection_directory_symlinked_away
    Dir.mktmpdir do |outside|
      site do |dir|
        FileUtils.rm_rf(File.join(dir, "pages/_docs"))
        File.symlink(outside, File.join(dir, "pages/_docs"))
        assert_raises(ArgumentError) { Writer.create(dir, collection: "docs", title: "x") }
        assert_empty Dir.children(outside)
      end
    end
  end

  def test_duplicate_is_a_draft_copy_without_url_redirects_or_preview
    site do |dir|
      original = File.join(dir, "pages/_posts/2026-01-01-hello.md")
      text = "---\ntitle: Hello\npermalink: /hacks/hello/\nredirect_from:\n  - /old/\npreview: /img.png\ntags: [a]\n---\nBody\n"
      File.write(original, text)
      copy = Writer.duplicate(original, root: dir)
      assert_equal File.join(dir, "pages/_posts/2026-01-01-hello-copy.md"), copy.to_s
      assert_equal "---\ntitle: Hello (copy)\ntags: [a]\ndraft: true\n---\nBody\n", File.read(copy)
      assert_equal text, File.read(original)
      assert_equal File.join(dir, "pages/_posts/2026-01-01-hello-copy-2.md"), Writer.duplicate(original, root: dir).to_s
    end
  end

  def test_duplicate_refuses_symlinks_and_paths_outside_the_root
    site do |dir|
      Dir.mktmpdir do |outside|
        secret = File.join(outside, "secret.md")
        File.write(secret, "---\ntitle: Secret\n---\n")
        link = File.join(dir, "pages/_docs/link.md")
        File.symlink(secret, link)
        assert_raises(ArgumentError) { Writer.duplicate(link, root: dir) }
        assert_raises(Zer0Cms::Cms::UnsafePath) { Writer.duplicate(secret, root: dir) }
      end
    end
  end
end
