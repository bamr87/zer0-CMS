# Obsidian bridge -- graph index builder (pure Ruby, no Jekyll required).
#
# Builds the payload for /assets/data/wiki-index.json, consumed by the
# theme's Obsidian graph UI (assets/js/obsidian-graph.js), the client-side
# wikilink resolver, and the backlinks panel. Entry shape mirrors the theme's
# Liquid template contract:
#   {title, basename, url, collection, tags, categories, aliases[],
#    outgoing[], excerpt}
#
# Wikilink extraction reuses Obsidian::Wikilinks::LINK_RE with
# Obsidian::FenceMask so code fences and inline code never become graph
# edges -- the exact same parsing the bridge applies to page content.
#
# Client-side resolution contract (theme's obsidian-graph.js buildLookup):
# outgoing targets are matched against NORMALIZED title / basename /
# aliases only. This vault writes path-qualified wikilinks
# ([[_docs/obsidian/graph]]), so build_entry adds each doc's
# extension-less vault path to aliases[] -- that is what makes
# path-qualified targets resolve in the browser. Targets that resolve
# nowhere stay in outgoing[] untouched and render as red "broken" nodes,
# which is intended behaviour.
#
# Ruby 2.6 compatible.

require 'json'
require 'time'
require_relative 'fence_mask'
require_relative 'wikilinks'

module Obsidian
  module GraphIndex
    EXCERPT_LIMIT = 240

    module_function

    # docs: array of hashes
    #   {title:, path:, url:, collection:, tags:, categories:, aliases:, content:}
    # Returns the full JSON-ready payload hash.
    def build_payload(docs, generated_at = nil)
      time = generated_at || Time.now
      stamp = time.respond_to?(:iso8601) ? time.iso8601 : time.to_s
      entries = docs.map { |doc| build_entry(doc) }
      {
        'generated_at' => stamp,
        'count' => entries.length,
        'entries' => entries
      }
    end

    def to_json(docs, generated_at = nil)
      JSON.pretty_generate(build_payload(docs, generated_at))
    end

    def build_entry(doc)
      vault_key = strip_ext(doc[:path].to_s)
      base = File.basename(vault_key)
      content = doc[:content].to_s
      {
        'title' => (doc[:title] || base).to_s,
        'basename' => base,
        'url' => doc[:url].to_s,
        'collection' => doc[:collection],
        'tags' => string_list(doc[:tags]),
        'categories' => string_list(doc[:categories]),
        'aliases' => alias_list(doc[:aliases], vault_key),
        'outgoing' => outgoing_targets(content),
        'excerpt' => excerpt(content)
      }
    end

    # Frontmatter aliases plus the doc's extension-less vault path (see the
    # resolution contract in the header comment).
    def alias_list(aliases, vault_key)
      list = aliases.is_a?(Array) ? aliases : [aliases]
      out = list.map { |a| a.to_s }.reject(&:empty?)
      out << vault_key unless vault_key.empty? || out.include?(vault_key)
      out
    end

    def string_list(value)
      return [] if value.nil?
      list = value.is_a?(Array) ? value : [value]
      list.map { |v| v.to_s }.reject { |v| v.empty? }
    end

    def strip_ext(path)
      path.sub(%r{\A/+}, '').sub(/\.(md|markdown)\z/i, '')
    end

    # Ordered, unique outgoing wikilink targets. Code fences and inline code
    # are skipped via FenceMask; image embeds (![[pic.png]]) are attachments,
    # not edges; note embeds (![[note]]) are transclusions and count.
    def outgoing_targets(md)
      targets = []
      FenceMask.apply_outside(md.to_s) do |chunk|
        chunk.scan(Wikilinks::LINK_RE) do |bang, inner|
          target = wikilink_target(inner, bang == '!')
          targets << target if target
        end
        chunk
      end
      targets.uniq
    end

    # Path part of a wikilink body: strips |alias, #anchor, and ^block-ref.
    def wikilink_target(inner, embed)
      target = inner.to_s.split('|', 2).first.to_s
      path = target.split('#', 2).first.to_s.split('^', 2).first.to_s.strip
      return nil if path.empty?
      return nil if embed && Wikilinks.image?(path)
      path
    end

    # Plain-text excerpt: fenced blocks and inline code dropped, wikilinks
    # reduced to their labels, markdown/HTML markup stripped, whitespace
    # collapsed, truncated to EXCERPT_LIMIT characters.
    def excerpt(md, limit = EXCERPT_LIMIT)
      prose = FenceMask.segments(md.to_s).map { |kind, chunk|
        next ' ' if kind == :code
        FenceMask.split_inline(chunk).map { |k, c| k == :code ? ' ' : c }.join
      }.join(' ')
      truncate(plain_text(prose), limit)
    end

    def plain_text(text)
      out = text.dup
      out.gsub!(/\{%.*?%\}/m, ' ')                # liquid tags
      out.gsub!(/\{\{.*?\}\}/m, ' ')              # liquid output
      out.gsub!(Wikilinks::LINK_RE) do            # wikilinks -> label
        wikilink_label(Regexp.last_match(2))
      end
      out.gsub!(/!\[([^\]]*)\]\([^)]*\)/, '\1')   # md images -> alt text
      out.gsub!(/\[([^\]]+)\]\([^)]*\)/, '\1')    # md links -> link text
      out.gsub!(/<[^>]+>/, ' ')                   # html tags
      out.gsub!(/^ {0,3}\#{1,6}[ \t]+/, '')       # heading markers
      out.gsub!(/^ {0,3}>[ \t]?/, '')             # blockquote markers
      out.gsub!(/\[!\w+\][+-]?/, '')              # callout type markers
      out.gsub!(/\*+/, '')                        # emphasis asterisks
      out.gsub!(/\s+/, ' ')
      out.strip
    end

    def wikilink_label(inner)
      target, display = inner.to_s.split('|', 2)
      label = display.to_s.strip
      return label unless label.empty?
      path, anchor = target.to_s.split('#', 2)
      path = path.to_s.strip
      return File.basename(path) unless path.empty?
      anchor.to_s.strip
    end

    def truncate(text, limit)
      return text if text.length <= limit
      text[0, limit - 1].rstrip + '…'
    end
  end
end
