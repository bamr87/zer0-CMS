# frozen_string_literal: true

# A Jekyll site the app can generate previews for.
#
# Registration is by path: a site is read and written in place. Nothing about
# its configuration is stored here beyond what is needed to find it —
# `_config.yml` remains the source of truth, and the config editor round-trips
# that file rather than shadowing it in the database.
class Site < ApplicationRecord
  has_many :runs, dependent: :nullify

  validates :name, presence: true
  validates :path, presence: true, uniqueness: true
  validate :path_is_a_jekyll_site

  scope :recently_scanned, -> { order(last_scanned_at: :desc) }
  scope :named, -> { order(:name) }

  def self.discover_roots(mount = "/sites")
    dir = Pathname.new(mount)
    return [] unless dir.directory?

    configs = Pathname.glob(dir.join("*/_config.yml")) + Pathname.glob(dir.join("*/*/_config.yml"))
    registered = pluck(:path).to_set
    configs.map { |cfg| cfg.dirname.to_s }.uniq.reject { |path| registered.include?(path) }.sort
  end

  def root
    Pathname.new(path)
  end

  # Where content and assets actually live. Jekyll's top-level `source:` key
  # shifts every disk path without changing front-matter values, so it has to
  # be applied here rather than assumed to be the site root.
  def source_root
    source_subdir.presence ? root.join(source_subdir) : root
  end

  def config_file
    root.join("_config.yml")
  end

  def config_file_exists?
    config_file.file?
  end

  private

  def path_is_a_jekyll_site
    return if path.blank?

    pathname = Pathname.new(path)
    unless pathname.absolute?
      errors.add(:path, "must be an absolute path (in Docker, sites live under /sites)")
      return
    end
    unless pathname.directory?
      errors.add(:path, "is not a directory the app can see — check the volume mount")
      return
    end
    return if pathname.join("_config.yml").file?

    errors.add(:path, "has no _config.yml — is this a Jekyll site root?")
  end
end
