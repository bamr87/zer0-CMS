# frozen_string_literal: true

# Serves generated artifacts for preview in the UI.
#
# Previews live inside registered sites and the studio scratch dir — outside
# public/ — so they cannot be served as static assets. This controller streams
# them, but ONLY after confirming the resolved real path sits inside an
# allowed root. Without that check, `files/../../etc/passwd` would be a file
# disclosure hole; the allow-list of roots is the whole security boundary.
class FilesController < ApplicationController
  skip_before_action :load_nav

  IMAGE_TYPES = {
    ".png" => "image/png", ".svg" => "image/svg+xml",
    ".jpg" => "image/jpeg", ".jpeg" => "image/jpeg", ".webp" => "image/webp"
  }.freeze

  def show
    requested = Pathname.new("/#{params[:path]}").cleanpath
    real = resolve(requested)
    return head(:not_found) unless real&.file?
    return head(:forbidden) unless allowed?(real)

    ext = real.extname.downcase
    return head(:unsupported_media_type) unless IMAGE_TYPES.key?(ext)

    send_file real.to_s, type: IMAGE_TYPES[ext], disposition: "inline"
  end

  private

  # The request path is an absolute on-disk path (artifacts are stored that
  # way). cleanpath collapses any `..` before the allow-list check, so a
  # traversal attempt resolves to a real path that simply is not under a root.
  def resolve(requested)
    requested.exist? ? requested.realpath : nil
  rescue SystemCallError
    nil
  end

  def allowed?(real)
    allowed_roots.any? { |root| real.to_s == root.to_s || real.to_s.start_with?("#{root}/") }
  end

  # Registered site roots, the studio scratch dirs, and the repo's own
  # first-party asset dirs (the example library and sample/showcase artwork the
  # Library and Studio display). Recomputed per request so a newly registered
  # site is immediately serveable. Everything here is read-only display
  # content; the extension allow-list in #show still gates what can be served.
  FIRST_PARTY_ASSET_DIRS = [".sweep", ".preview", ".forge", "docs", "tools/svg/library"].freeze

  def allowed_roots
    roots = Site.pluck(:path).map { |p| real_or_nil(p) }
    FIRST_PARTY_ASSET_DIRS.each do |rel|
      roots << real_or_nil(Rails.application.config.repo_root.join(rel))
    end
    roots.compact
  end

  def real_or_nil(path)
    Pathname.new(path.to_s).realpath
  rescue SystemCallError
    nil
  end
end
