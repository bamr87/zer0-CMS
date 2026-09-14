# frozen_string_literal: true

# A registered Jekyll site. `path` is stored as the directory's realpath, so
# two spellings of one root cannot register twice and every containment check
# compares canonical paths.
class Site < ApplicationRecord
  CONFIG_READ_LIMIT = 256 * 1024

  has_many :pages, dependent: :delete_all
  has_many :assets, dependent: :delete_all
  has_many :terms, dependent: :delete_all

  before_validation :canonicalize_path

  validates :name, presence: true
  validates :path, presence: true, uniqueness: true
  validate :path_is_a_confined_jekyll_site

  scope :named, -> { order(:name) }

  # The mount that registered sites must live in, or nil (any absolute path).
  def self.sites_dir
    Rails.application.config.x.sites_dir.presence
  end

  # Jekyll roots one or two levels under SITES_DIR that are not registered.
  def self.discover_roots(mount = sites_dir)
    return [] if mount.blank?

    dir = Pathname.new(mount)
    return [] unless dir.directory?

    registered = pluck(:path).to_set
    configs = Pathname.glob(dir.join("*/_config.yml")) + Pathname.glob(dir.join("*/*/_config.yml"))
    configs.filter_map { |config| realpath_or_nil(config.dirname) }
           .uniq
           .select { |root| inside_sites_dir?(root, mount) }
           .reject { |root| registered.include?(root) }
           .sort
  end

  # True when `real` (a realpath string) is strictly inside SITES_DIR, or when
  # no SITES_DIR is configured.
  def self.inside_sites_dir?(real, mount = sites_dir)
    return true if mount.blank?

    base = realpath_or_nil(mount)
    !base.nil? && real.to_s.start_with?("#{base.chomp("/")}/")
  end

  def self.realpath_or_nil(path)
    File.realpath(path.to_s)
  rescue SystemCallError
    nil
  end

  def root
    Pathname.new(path)
  end

  def to_s
    name
  end

  def sync!
    SiteSync.new(self).call
  end

  def sync_path!(relative)
    SiteSync.new(self).sync_path(relative)
  end

  def site_path
    SitePath.new(path)
  end

  # The raw _config.yml text for the read-only view, or nil.
  def config_yaml
    file = site_path.file!("_config.yml")
    File.open(file, "rb") { |io| io.read(CONFIG_READ_LIMIT) }.to_s.force_encoding("UTF-8").scrub
  rescue SitePath::Refused
    nil
  end

  def collection_counts
    pages.group(:collection).order(:collection).count
  end

  # { "posts" => ["hacks", "wire"], "docs" => [] } — the collections a new
  # page can go into (declared, with a real directory) and their existing
  # section subdirectories, for the new-page form.
  def writable_collections
    catalog_site = Zer0Cms::Cms::Catalog.site_for(path)
    catalog_site.collection_names.reject { |name| name == "data" }.each_with_object({}) do |name, out|
      dir = Zer0Cms::Cms::Catalog.collection_directory(catalog_site, name)
      next unless dir.directory? && !dir.symlink?

      out[name] = sections_under(dir)
    end
  rescue Zer0Cms::Cms::UnsafePath, SystemCallError
    {}
  end

  private

  def sections_under(dir, prefix = nil, depth = 0)
    return [] if depth > 1

    dir.children.select { |child| child.directory? && !child.symlink? }
       .map { |child| child.basename.to_s }
       .select { |name| Zer0Cms::Cms::Writer::SECTION_SEGMENT.match?(name) }
       .sort
       .flat_map do |name|
         section = prefix ? "#{prefix}/#{name}" : name
         [section, *sections_under(dir.join(name), section, depth + 1)]
       end
  rescue SystemCallError
    []
  end

  def canonicalize_path
    text = path.to_s.strip
    self.path = text
    return if text.empty? || !Pathname.new(text).absolute?

    real = self.class.realpath_or_nil(text)
    self.path = real if real
  end

  def path_is_a_confined_jekyll_site
    return if path.blank?

    pathname = Pathname.new(path)
    unless pathname.absolute?
      errors.add(:path, "must be an absolute path (in Docker, sites live under #{self.class.sites_dir || "/sites"})")
      return
    end
    unless pathname.directory?
      errors.add(:path, "is not a directory the app can see — check the volume mount")
      return
    end
    unless self.class.inside_sites_dir?(path)
      errors.add(:path, "must be inside SITES_DIR (#{self.class.sites_dir})")
      return
    end
    return if pathname.join("_config.yml").file?

    errors.add(:path, "has no _config.yml — is this a Jekyll site root?")
  end
end
