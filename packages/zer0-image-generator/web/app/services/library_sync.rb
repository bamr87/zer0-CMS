# frozen_string_literal: true

# Projects tools/svg/library/MANIFEST.json into LibraryEntry rows so the
# library is browsable and searchable in the UI.
#
# The manifest on disk is the source of truth (it ships with the repo and is
# what a human reviews in a diff); this sync is one-directional, manifest → DB,
# and idempotent. Entries removed from the manifest are removed from the table
# so the two never drift.
class LibrarySync
  class Error < StandardError; end

  MANIFEST = "tools/svg/library/MANIFEST.json"

  def self.manifest_path
    Rails.application.config.repo_root.join(MANIFEST)
  end

  def self.call
    path = manifest_path
    raise Error, "manifest not found at #{path}" unless path.file?

    data = JSON.parse(path.read)
    entries = data["entries"] || []
    seen = []

    entries.each do |entry|
      file = entry["file"]
      next if file.blank?

      record = LibraryEntry.find_or_initialize_by(file: file)
      record.assign_attributes(
        title: entry["title"], source_url: entry["source_url"],
        license: entry["license"], license_url: entry["license_url"],
        tags: Array(entry["tags"]), lint: entry["lint"], size_kb: entry["size_kb"]
      )
      # A manifest entry that fails our own model validation (e.g. an external
      # SVG with no license) is surfaced, not silently imported.
      record.save
      seen << file
    end

    LibraryEntry.where.not(file: seen).delete_all
    seen.size
  rescue JSON::ParserError => e
    raise Error, "manifest is not valid JSON: #{e.message}"
  end
end
