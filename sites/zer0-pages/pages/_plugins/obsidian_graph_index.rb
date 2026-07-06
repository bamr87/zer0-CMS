# Obsidian graph index -- Jekyll glue.
#
# Emits /assets/data/wiki-index.json (nodes + outgoing wikilink edges) for
# the theme's Obsidian graph UI, client-side wikilink resolver, and
# backlinks tooling. The payload itself is built by the pure-Ruby core in
# _plugins/obsidian/graph_index.rb, which reuses the bridge's fence-masked
# wikilink parser -- one parser, one resolution story.
#
# Why not the theme's template? jekyll-theme-zer0 ships a Liquid template
# page at the same permalink that re-extracts [[wikilinks]] from
# doc.content DURING rendering. Our bridge (obsidian_bridge.rb) rewrites
# doc.content at :pre_render, so what that template would see depends on
# render order -- nondeterministic. This hook therefore REMOVES the theme's
# page from site.pages before anything renders and appends its own
# PageWithoutAFile at the same destination, so exactly one deterministic
# JSON is ever rendered and written.
#
# Ordering: registered at :site :pre_render with priority :low, so it runs
# AFTER the bridge's :site :pre_render hook (normal priority) and BEFORE any
# document/page renders -- item.content is still raw markdown here, exactly
# what the wikilink parser expects.
#
# URLs are emitted with site.baseurl prefixed (the graph JS navigates to
# entry.url verbatim and this site deploys under /zer0-pages).
#
# Ruby 2.6 compatible.

require 'json'
require_relative 'obsidian/graph_index'
require_relative 'obsidian_bridge'

module ObsidianGraphIndex
  INDEX_PATH = '/assets/data/wiki-index.json'.freeze
  INDEX_RELATIVE = 'assets/data/wiki-index.json'.freeze

  module_function

  # Maps a Jekyll document/page (or any duck-typed stand-in) to the plain
  # hash Obsidian::GraphIndex.build_entry consumes.
  def doc_hash(item, baseurl = '')
    {
      title: item.data['title'],
      path: ObsidianBridge.rel_path(item),
      url: baseurl.to_s + item.url.to_s,
      collection: collection_label(item),
      tags: item.data['tags'],
      categories: item.data['categories'],
      aliases: item.data['aliases'],
      content: item.content
    }
  end

  # "posts" for posts, the collection label for other collections, nil for
  # standalone pages (the graph JS colors nil as "page").
  def collection_label(item)
    collection = item.respond_to?(:collection) ? item.collection : nil
    return nil if collection.nil?
    collection.respond_to?(:label) ? collection.label : collection.to_s
  end
end

if defined?(Jekyll)
  Jekyll::Hooks.register :site, :pre_render, priority: :low do |site|
    # Same doc pool the bridge indexes: every collection doc + markdown page.
    items = []
    site.collections.each_value do |collection|
      collection.docs.each { |doc| items << doc }
    end
    site.pages.each { |page| items << page if ObsidianBridge.md_item?(page) }

    baseurl = site.config['baseurl'].to_s
    docs = items.map { |item| ObsidianGraphIndex.doc_hash(item, baseurl) }
    json = Obsidian::GraphIndex.to_json(docs, site.time)

    # Drop the theme gem's Liquid-template page at the same destination so
    # only this deterministic, bridge-parsed JSON renders and gets written.
    site.pages.reject! do |page|
      page.url == ObsidianGraphIndex::INDEX_PATH ||
        page.relative_path.to_s.sub(%r{\A/+}, '') == ObsidianGraphIndex::INDEX_RELATIVE
    end

    page = Jekyll::PageWithoutAFile.new(site, site.source, 'assets/data', 'wiki-index.json')
    page.content = json
    page.data['layout'] = nil
    page.data['sitemap'] = false
    page.data['permalink'] = ObsidianGraphIndex::INDEX_PATH
    # The content IS the final JSON -- never run Liquid over it (excerpts may
    # quote Liquid syntax from docs that teach it).
    page.data['render_with_liquid'] = false
    site.pages << page
  end
end
