# Obsidian bridge -- wikilink converter (pure Ruby, no Jekyll required).
#
# Converts Obsidian wikilinks and embeds into HTML/markdown at build time:
#   [[target]]  [[target|Display]]  [[target#Anchor]]  [[target#Anchor|Display]]
#   ![[image.png]] -> ![](url-or-path)      ![[note]] -> regular link
# Resolution is delegated to a caller-supplied resolver lambda that maps a
# target string to a URL (or nil when unresolved). Ruby 2.6 compatible.

require_relative 'fence_mask'

module Obsidian
  module Wikilinks
    IMAGE_EXTS = %w[.png .jpg .jpeg .gif .svg .webp].freeze
    LINK_RE = /(!?)\[\[([^\[\]\n]+)\]\]/

    module_function

    # Converts every wikilink outside code fences / inline code spans.
    # +resolver+ responds to #call(target) -> url String or nil.
    def convert(md, resolver)
      FenceMask.apply_outside(md) { |chunk| convert_chunk(chunk, resolver) }
    end

    def convert_chunk(text, resolver)
      text.gsub(LINK_RE) do
        embed = Regexp.last_match(1) == '!'
        inner = Regexp.last_match(2)
        render_link(inner, embed, resolver) || Regexp.last_match(0)
      end
    end

    def render_link(inner, embed, resolver)
      target, display = inner.split('|', 2)
      target = target.to_s.strip
      display = display.strip if display
      path, anchor = target.split('#', 2)
      path = path.to_s.strip
      anchor = anchor.strip if anchor
      return nil if path.empty? && (anchor.nil? || anchor.empty?)

      if embed && image?(path)
        url = resolver.call(path)
        src = url || path
        src = "<#{src}>" if src.include?(' ')
        return "![](#{src})"
      end

      base = path.split('/').last.to_s
      label = display
      label = base if label.nil? || label.empty?
      label = anchor if label.nil? || label.empty?

      frag = anchor && !anchor.empty? ? "##{slugify(anchor)}" : ''

      if path.empty?
        return "<a href=\"#{escape_html(frag)}\" class=\"wikilink\">#{escape_html(label)}</a>"
      end

      url = resolver.call(path)
      if url
        "<a href=\"#{escape_html(url + frag)}\" class=\"wikilink\">#{escape_html(label)}</a>"
      else
        "<span class=\"wikilink-unresolved\">#{escape_html(label)}</span>"
      end
    end

    def image?(path)
      IMAGE_EXTS.include?(File.extname(path).downcase)
    end

    def slugify(text)
      text.to_s.downcase.gsub(/[^a-z0-9]+/, '-').gsub(/\A-+|-+\z/, '')
    end

    def escape_html(text)
      text.to_s.gsub('&', '&amp;').gsub('<', '&lt;').gsub('>', '&gt;').gsub('"', '&quot;')
    end
  end
end
