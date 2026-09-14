# frozen_string_literal: true

class Site < ApplicationRecord
  validates :name, presence: true
  validates :path, presence: true, uniqueness: true
  validate :path_is_a_jekyll_site

  scope :named, -> { order(:name) }

  def self.discover_roots(mount = Rails.application.config.x.sites_dir)
    dir = Pathname.new(mount)
    return [] unless dir.directory?

    configs = Pathname.glob(dir.join("*/_config.yml")) + Pathname.glob(dir.join("*/*/_config.yml"))
    registered = pluck(:path).to_set
    configs.map { |cfg| cfg.dirname.to_s }.uniq.reject { |path| registered.include?(path) }.sort
  end

  def root
    Pathname.new(path)
  end

  def source_root
    source_subdir.presence ? root.join(source_subdir) : root
  end

  def config_file
    root.join("_config.yml")
  end

  def catalog
    Zer0Cms::Cms::Catalog.scan(root)
  end

  def absorb_source_subdir
    config = Zer0Cms::Cms::Catalog.read_config(root)
    source = config["source"].to_s.strip
    update_column(:source_subdir, source) if source.present? && source != source_subdir
    collections_dir = config["collections_dir"].to_s.strip
    notes_bit = collections_dir.present? ? "collections_dir: #{collections_dir}" : nil
    update_column(:notes, notes_bit) if notes.blank? && notes_bit
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
