# frozen_string_literal: true

# Markdown to sanitized HTML for previews: kramdown GFM, then an allow-list
# sanitizer (no on* attributes, no javascript: URLs, no raw HTML beyond the
# listed tags).
module MarkdownRenderer
  TAGS = %w[p br h1 h2 h3 h4 h5 h6 ul ol li pre code blockquote a img em strong del hr table thead tbody tr th td].freeze
  ATTRIBUTES = %w[href src alt title class].freeze
  LIMIT = 1_000_000

  module_function

  def render(text)
    source = text.to_s
    source = source[0, LIMIT] if source.length > LIMIT
    html = Kramdown::Document.new(source, input: "GFM", hard_wrap: false).to_html
    Rails::HTML5::SafeListSanitizer.new.sanitize(html, tags: TAGS, attributes: ATTRIBUTES).to_s.html_safe
  rescue StandardError => e
    Rails.logger.warn("markdown preview failed: #{e.class}: #{e.message}")
    ERB::Util.html_escape(source)
  end
end
