# frozen_string_literal: true

require "kramdown"
require "kramdown-parser-gfm"

module ApplicationHelper
  include Pagy::Frontend
  include ActionView::Helpers::SanitizeHelper
  def disk_file_url(path)
    return if path.blank?

    pathname = Pathname.new(path.to_s)
    return unless pathname.exist?

    file_path(path: pathname.realpath.to_s.sub(%r{\A/}, ""))
  end

  def preview_url(site, entry)
    preview = entry.preview.to_s
    return if preview.empty?
    return preview if preview.start_with?("http://", "https://")

    clean = preview.sub(%r{\A/+}, "")
    candidates = [
      site.root.join(clean),
      site.root.join("assets", clean),
      site.source_root.join(clean),
      site.source_root.join("assets", clean)
    ]
    hit = candidates.find(&:file?)
    disk_file_url(hit)
  end

  def site_tab_class(active)
    active ? "active" : ""
  end

  def markdown_html(text)
    html = Kramdown::Document.new(text.to_s, input: "GFM", hard_wrap: false).to_html
    sanitize(html, tags: %w[p br h1 h2 h3 h4 h5 h6 ul ol li pre code blockquote a img em strong hr table thead tbody tr th td],
                   attributes: %w[href src alt title class])
  end
end
