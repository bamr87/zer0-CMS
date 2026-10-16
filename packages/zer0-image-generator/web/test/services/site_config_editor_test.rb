# frozen_string_literal: true

require "test_helper"

class SiteConfigEditorTest < ActiveSupport::TestCase
  # The editor rewrites a file the user hand-maintains, so these tests defend
  # the single property that matters most: everything outside the
  # preview_images: block survives untouched.

  def with_config(body)
    Dir.mktmpdir do |dir|
      File.write(File.join(dir, "_config.yml"), body)
      site = Site.create!(name: "S", path: dir)
      yield site, File.join(dir, "_config.yml")
    end
  end

  test "replaces the block while preserving comments and sibling keys" do
    body = <<~YAML
      # top comment
      title: My Site
      collections:
        docs:
          output: true

      preview_images:
        provider: local
        collections: auto
    YAML
    with_config(body) do |site, path|
      SiteConfigEditor.new(site).update("provider" => "openai", "front_matter_key" => "image")
      result = File.read(path)
      assert_includes result, "# top comment"
      assert_includes result, "title: My Site"
      assert_includes result, "output: true"
      parsed = YAML.safe_load(result)
      assert_equal "openai", parsed["preview_images"]["provider"]
      assert_equal "image", parsed["preview_images"]["front_matter_key"]
      assert_equal "My Site", parsed["title"]
    end
  end

  test "appends a block when the file has none" do
    with_config("title: Bare\n") do |site, path|
      SiteConfigEditor.new(site).update("provider" => "xai")
      parsed = YAML.safe_load(File.read(path))
      assert_equal "Bare", parsed["title"]
      assert_equal "xai", parsed["preview_images"]["provider"]
    end
  end

  test "does not disturb a top-level key that follows the block" do
    body = <<~YAML
      preview_images:
        provider: local
      plugins:
        - jekyll-seo-tag
    YAML
    with_config(body) do |site, path|
      SiteConfigEditor.new(site).update("provider" => "gemini")
      parsed = YAML.safe_load(File.read(path))
      assert_equal ["jekyll-seo-tag"], parsed["plugins"]
      assert_equal "gemini", parsed["preview_images"]["provider"]
    end
  end

  test "collections accepts a list or the literal auto" do
    with_config("preview_images:\n  provider: local\n") do |site, path|
      SiteConfigEditor.new(site).update("collections" => "posts, docs, notes")
      assert_equal %w[posts docs notes], YAML.safe_load(File.read(path))["preview_images"]["collections"]
      SiteConfigEditor.new(site).update("collections" => "auto")
      assert_equal "auto", YAML.safe_load(File.read(path))["preview_images"]["collections"]
    end
  end
end
