# frozen_string_literal: true

require "test_helper"

class SiteTest < ActiveSupport::TestCase
  test "discover_roots finds unregistered jekyll sites" do
    mount = Dir.mktmpdir
    nested = File.join(mount, "year-of-ai", "year-of-ai.github.io")
    FileUtils.mkdir_p(File.join(mount, "blog"))
    FileUtils.mkdir_p(nested)
    File.write(File.join(mount, "blog", "_config.yml"), "title: blog\n")
    File.write(File.join(nested, "_config.yml"), "title: year\n")
    File.write(File.join(mount, "blog", "_config.yml.tmp"), "nope\n")

    found = Site.discover_roots(mount)
    assert_includes found, File.join(mount, "blog")
    assert_includes found, nested

    Site.create!(name: "blog", path: File.join(mount, "blog"))
    found = Site.discover_roots(mount)
    refute_includes found, File.join(mount, "blog")
    assert_includes found, nested
  ensure
    FileUtils.remove_entry(mount) if mount
  end

  test "discover_roots is empty when the mount is missing" do
    assert_equal [], Site.discover_roots("/definitely-not-a-sites-mount")
  end
end
