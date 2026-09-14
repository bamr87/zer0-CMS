# frozen_string_literal: true

require "administrate/field/base"

# A preview image path shown as a thumbnail through /files. For a Page the
# value is a site URL path (`/assets/images/previews/x.png`), looked up under
# the site source and root; with `root_relative: true` (an Asset) it is the
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

    @image_path = resolve
  end

  private

  def resolve
    site = resource.respond_to?(:site) ? resource.site : nil
    return nil if value.empty? || external? || site.nil?

    site_path = site.site_path
    candidates(site).each do |relative|
      next unless FilesController::IMAGE_TYPES.key?(File.extname(relative).downcase)

      begin
        file = site_path.file!(relative)
      rescue SitePath::Refused
        next
      end
      return Rails.application.routes.url_helpers.file_path(path: file.to_s.delete_prefix("/"))
    end
    nil
  rescue SitePath::Refused
    nil
  end

  def candidates(site)
    return [value] if options[:root_relative]

    clean = value.split(/[?#]/).first.to_s.sub(%r{\A/+}, "")
    source = site.source_subdir.to_s
    [source.empty? ? nil : File.join(source, clean), clean].compact.uniq
  end
end
