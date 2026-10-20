# frozen_string_literal: true

# Reads a site's collections and reports, per content file, whether it already
# has a valid preview — the web equivalent of `--list-missing`, but as
# structured data rather than printed lines.
#
# It resolves settings the same way a run would, so "missing" here means
# exactly what "missing" means to a real generation: the front-matter key is
# absent, or points at a file that is not on disk.
class SiteScanner
  class Error < StandardError; end

  Entry = Struct.new(:path, :relative, :title, :collection, :preview, :exists, :disk_path, keyword_init: true) do
    def missing? = !exists

    def remote?
      preview.to_s.start_with?("http://", "https://")
    end
  end
  Result = Struct.new(:settings, :collections, :entries, keyword_init: true) do
    def total = entries.size
    def missing = entries.count(&:missing?)
    def present = entries.count(&:exists)
    def by_collection = entries.group_by(&:collection)
  end

  def initialize(site, args = {})
    @site = site
    @args = args
  end

  def call
    config = EngineBridge.read_config(@site.root)
    settings = EngineBridge.resolve_settings(@args, config)
    entries = collections(settings).flat_map { |name| scan_collection(settings, name) }
    Result.new(settings: settings, collections: collections(settings), entries: entries)
  rescue EngineBridge::Error => e
    raise Error, e.message
  end

  private

  def collections(settings)
    @collections ||= Array(settings.collections).map(&:to_s)
  end

  def scan_collection(settings, name)
    dir = collection_dir(settings, name)
    return [] unless dir.directory?

    content = Zer0ImageGenerator::Content
    dir.glob("**/*.md").sort.filter_map do |path|
      cf = content.parse_front_matter(path.to_s, settings.front_matter_key)
      next unless cf

      exists = cf.preview && content.check_preview_exists(cf.preview, settings, @site.root)
      disk = exists ? content.find_preview_image(cf.preview, settings, @site.root) : nil
      Entry.new(
        path: path.to_s,
        relative: path.relative_path_from(@site.root).to_s,
        title: cf.title.to_s.empty? ? File.basename(path) : cf.title,
        collection: name,
        preview: cf.preview,
        exists: !!exists,
        disk_path: disk&.to_s
      )
    end
  end

  # `<source_root>/<collections_dir>/_<name>` — mirrors Runner#collection_path,
  # but rooted at the site's source_root so `source:` sites resolve correctly.
  def collection_dir(settings, name)
    base = @site.source_root
    settings.collections_dir.to_s.split("/").each { |part| base = base.join(part) unless part.empty? }
    base.join("_#{name}")
  end
end
