# frozen_string_literal: true

require "test_helper"

class SiteSyncTest < ActiveSupport::TestCase
  test "the index holds exactly what Catalog.scan and Catalog.media report" do
    site = build_site
    write_file(site, "assets/images/pixel.png", PNG)
    site.sync!
    scan = Zer0Cms::Cms::Catalog.scan(site.path)

    assert_equal scan.entries.map(&:source_relative).sort, site.pages.pluck(:source_relative).sort
    assert_equal scan.entries.size, site.reload.pages_count
    assert_equal scan.by_collection, site.pages.group(:collection).count
    assert_equal scan.entries.count(&:draft), site.pages.where(draft: true).count
    assert_equal Zer0Cms::Cms::Catalog.media(site.path).size, site.assets.count
    assert_equal site.assets.count, site.assets_count
    assert_equal scan.entries.flat_map { |e| e.tags.uniq }.tally, site.terms.where(kind: "tag").pluck(:name, :pages_count).to_h
    assert_equal "pages", site.collections_dir
    assert_nil site.sync_error
  end

  test "a second sync removes vanished files and indexes new ones" do
    site = build_site
    File.delete(File.join(site.path, "pages/_docs/intro.md"))
    write_file(site, "pages/_docs/added.md", "---\ntitle: Added\n---\nNew.\n")
    site.sync!

    assert_nil site.pages.find_by(source_relative: "pages/_docs/intro.md")
    assert_equal "Added", site.pages.find_by!(source_relative: "pages/_docs/added.md").title
    assert_equal Zer0Cms::Cms::Catalog.scan(site.path).entries.size, site.pages.count
  end

  test "rows keep their ids across syncs" do
    site = build_site
    ids = site.pages.pluck(:source_relative, :id).to_h
    site.sync!
    assert_equal ids, site.pages.pluck(:source_relative, :id).to_h
  end

  test "a collections_dir outside the root fails the sync and records why" do
    site = build_site
    File.write(File.join(site.path, "_config.yml"), "collections_dir: ../elsewhere\n")
    error = assert_raises(SiteSync::Failed) { site.sync! }
    assert_match(/outside the site root/, error.message)
    assert_match(/outside the site root/, site.reload.sync_error)
  end

  test "sync_path indexes one new file and drops one deleted file" do
    site = build_site
    write_file(site, "pages/_docs/one.md", "---\ntitle: One\n---\n")
    entry = site.sync_path!("pages/_docs/one.md")
    assert_equal "docs", entry.collection
    assert site.pages.exists?(relative: "pages/_docs/one.md")

    File.delete(File.join(site.path, "pages/_docs/one.md"))
    assert_nil site.sync_path!("pages/_docs/one.md")
    refute site.pages.exists?(relative: "pages/_docs/one.md")
  end

  test "a registered path is canonical and must sit inside SITES_DIR when one is set" do
    site = build_site
    parent = File.dirname(site.path)
    duplicate = Site.new(name: "again", path: File.join(parent, ".", "site"))
    refute duplicate.valid?
    assert_includes duplicate.errors[:path], "has already been taken"

    Rails.application.config.x.sites_dir = scratch_dir
    outside = Site.new(name: "outside", path: site.path)
    outside.valid?
    assert(outside.errors[:path].any? { |message| message.include?("inside SITES_DIR") })
  end

  test "discovery lists unregistered roots under SITES_DIR only" do
    site = build_site
    mount = File.dirname(site.path)
    FileUtils.cp_r(FixtureSite::SOURCE.to_s, File.join(mount, "second"))
    Rails.application.config.x.sites_dir = mount

    assert_equal [File.join(mount, "second")], Site.discover_roots
  end
end
