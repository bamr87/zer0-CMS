# frozen_string_literal: true

require "administrate/field/base"

# A preview image path shown as a thumbnail through /files. For a Page the
# value is a site URL path (`/images/previews/x.png` or
# `/assets/images/previews/x.png`), looked up the way the image engine looks
# it up (see .locate); with `root_relative: true` (an Asset) it is the
# root-relative file itself. Only files SitePath accepts get a thumbnail.
class PreviewImageField < Administrate::Field::Base
  def self.searchable?
    false
  end

  def self.sortable?
    false
  end

  def value
    data.to_s
  end

  def external?
    value.match?(%r{\Ahttps?://}i)
  end

  def image_path
    return @image_path if defined?(@image_path)

    site = resource.respond_to?(:site) ? resource.site : nil
    file = self.class.locate(site, value, root_relative: options[:root_relative])
    @image_path = file && Rails.application.routes.url_helpers.file_path(path: file.to_s.delete_prefix("/"))
  end

  # The image file inside `site` that a preview value names, or nil. The
  # candidates follow the image engine's own lookup: the path under the site
  # source, the same path under `assets/` (the engine writes
  # `/images/previews/x.png` for a file in `assets/images/previews/`, and the
  # theme adds the prefix), then the path from the site root. Only files
  # SitePath accepts count.
  def self.locate(site, value, root_relative: false)
    text = value.to_s
    return nil if site.nil? || text.empty? || text.match?(%r{\Ahttps?://}i)

    site_path = site.site_path
    candidates(site, text, root_relative).each do |relative|
      next unless FilesController::IMAGE_TYPES.key?(File.extname(relative).downcase)

      begin
        return site_path.file!(relative)
      rescue SitePath::Refused
        next
      end
    end
    nil
  rescue SitePath::Refused
    nil
  end

  def self.candidates(site, value, root_relative)
    return [value] if root_relative

    clean = value.split(/[?#]/).first.to_s.sub(%r{\A/+}, "")
    source = site.source_subdir.to_s
    in_source = ->(relative) { source.empty? ? relative : File.join(source, relative) }
    [in_source.call(clean), in_source.call(File.join("assets", clean)), clean].uniq
  end
end
