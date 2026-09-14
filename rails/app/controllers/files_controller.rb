# frozen_string_literal: true

# Serves an image that lives inside a registered site, by absolute path.
#
# Refusals never touch a path outside every site: the site is chosen by
# string prefix first, then SitePath walks the remaining components with
# lstat (any symlink is refused) and checks the realpath. Errors are bare
# status codes, in every environment — this controller never renders a trace.
class FilesController < ApplicationController
  IMAGE_TYPES = {
    ".png" => "image/png", ".jpg" => "image/jpeg", ".jpeg" => "image/jpeg",
    ".gif" => "image/gif", ".webp" => "image/webp", ".svg" => "image/svg+xml"
  }.freeze
  # An SVG opened directly must not run script in the app's origin.
  FILE_POLICY = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"

  def show
    requested = "/#{params[:path]}"
    type = IMAGE_TYPES[File.extname(requested).downcase]
    return head(:not_found) unless type

    site, relative = locate(requested)
    return head(:not_found) unless site

    file = SitePath.new(site.path).file!(relative)
    response.headers["Content-Security-Policy"] = FILE_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    send_file file.to_s, type: type, disposition: "inline"
  rescue SitePath::NotFound
    head :not_found
  rescue SitePath::Refused
    head :forbidden
  rescue StandardError => e
    Rails.logger.warn("files#show refused #{params[:path].inspect}: #{e.class}")
    head :not_found
  end

  private

  def locate(requested)
    Site.pluck(:id, :path).each do |id, path|
      prefix = "#{path.chomp("/")}/"
      return [Site.find(id), requested.delete_prefix(prefix)] if requested.start_with?(prefix)
    end
    nil
  end
end
