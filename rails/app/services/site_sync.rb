# frozen_string_literal: true

require "digest"

# Rebuilds a site's rows from disk. Zer0Cms::Cms::Catalog walks the site with
# Jekyll's reader rules and Catalog.media lists its images; this class turns
# that into upserts and deletes inside one transaction, so the index never
# shows half a sync.
class SiteSync
  class Failed < StandardError; end

  Result = Struct.new(:pages, :assets, :terms, :errors, keyword_init: true)

  attr_reader :site, :now

  def initialize(site, now: Time.current)
    @site = site
    @now = now
  end

  def call
    scan = catalog_scan
    media = Zer0Cms::Cms::Catalog.media(site.path)
    page_rows = scan.entries.map { |entry| page_row(entry) }
    asset_rows = media.filter_map { |file| asset_row(file) }

    Site.transaction do
      replace(site.pages, page_rows, :source_relative)
      replace(site.assets, asset_rows, :relative)
      rebuild_terms(scan.entries)
      finish!(scan)
    end
    Result.new(pages: page_rows.size, assets: asset_rows.size, terms: site.terms.count, errors: scan.errors.size)
  rescue Zer0Cms::Cms::UnsafePath, SystemCallError, SitePath::Refused => e
    fail_with(e)
  end

  # Re-index one root-relative path after a write: upsert its row when Jekyll
  # would read it, delete the row when it no longer exists or is no longer
  # content. The walk is the full catalog, so the classification (kind,
  # collection, draft) is exactly the one #call would give.
  def sync_path(relative)
    scan = catalog_scan
    entry = scan.entries.find { |e| e.relative == relative.to_s }
    Site.transaction do
      if entry
        site.pages.upsert_all([page_row(entry)], unique_by: %i[site_id source_relative])
      else
        site.pages.where(relative: relative.to_s).delete_all
      end
      rebuild_terms(scan.entries)
      finish!(scan)
    end
    entry
  rescue Zer0Cms::Cms::UnsafePath, SystemCallError, SitePath::Refused => e
    fail_with(e)
  end

  private

  def catalog_scan
    Zer0Cms::Cms::Catalog.scan(site.path, now: now)
  end

  def fail_with(error)
    site.update_columns(sync_error: error.message, last_synced_at: now) if site.persisted?
    raise Failed, error.message
  end

  def finish!(scan)
    site.update!(
      source_subdir: relative_to_root(scan.source),
      collections_dir: scan.collections_dir.to_s,
      last_synced_at: now,
      sync_error: nil,
      pages_count: site.pages.count,
      assets_count: site.assets.count
    )
  end

  def relative_to_root(source)
    source.to_s == site.path ? "" : source.relative_path_from(Pathname.new(site.path)).to_s
  end

  def replace(scope, rows, key)
    keys = rows.map { |row| row[key] }
    scope.where.not(key => keys).delete_all
    scope.upsert_all(rows, unique_by: [:site_id, key]) if rows.any?
  end

  def page_row(entry)
    stat = File.stat(entry.path)
    {
      site_id: site.id,
      source_relative: entry.source_relative,
      relative: entry.relative,
      kind: entry.kind.to_s,
      collection: entry.collection.to_s,
      title: entry.title.to_s,
      description: entry.description.to_s,
      author: entry.author.to_s,
      date: entry.date,
      lastmod: entry.lastmod,
      layout: entry.layout.to_s,
      permalink: entry.permalink.to_s,
      preview: entry.preview.to_s,
      status: entry.status.to_s,
      draft: entry.draft ? true : false,
      published: entry.published ? true : false,
      future: entry.future ? true : false,
      tags: entry.tags,
      categories: entry.categories,
      front_matter: json_safe(entry.data),
      error: entry.error,
      digest: Digest::SHA256.file(entry.path).hexdigest,
      bytes: stat.size,
      mtime: stat.mtime
    }
  end

  def asset_row(file)
    relative = site.site_path.relative_for(file)
    return nil unless relative

    stat = File.stat(file)
    { site_id: site.id, relative: relative, ext: file.extname.downcase.delete_prefix("."), bytes: stat.size, mtime: stat.mtime }
  end

  def rebuild_terms(entries)
    counts = Hash.new(0)
    entries.each do |entry|
      entry.tags.uniq.each { |name| counts[["tag", name]] += 1 unless name.empty? }
      entry.categories.uniq.each { |name| counts[["category", name]] += 1 unless name.empty? }
      counts[["author", entry.author]] += 1 unless entry.author.to_s.empty?
    end
    site.terms.delete_all
    rows = counts.map { |(kind, name), n| { site_id: site.id, kind: kind, name: name, pages_count: n } }
    site.terms.insert_all(rows) if rows.any?
  end

  # Front matter as JSON can hold: dates as ISO 8601, non-finite floats as
  # text.
  def json_safe(value)
    case value
    when Hash then value.to_h { |k, v| [k.to_s, json_safe(v)] }
    when Array then value.map { |item| json_safe(item) }
    when Date, Time then value.iso8601
    when Float then value.finite? ? value : value.to_s
    else value
    end
  end
end
