# Obsidian bridge -- Jekyll glue.
#
# Wires the pure-Ruby converters in _plugins/obsidian/ into the Jekyll build:
#   1. site :pre_render     -> build the wikilink resolution index and the
#                              document pool used by Dataview queries.
#   2. docs/pages :pre_render  -> replace ```dataview fences, then convert
#                              wikilinks and callouts (code fences untouched).
#   3. docs/pages :post_render -> prefix site.baseurl onto root-relative
#                              href/src values and clean literal {{ site.* }}
#                              leftovers, skipping <pre>/<code> content.
#
# The helper methods are pure so the unit tests can exercise them with plain
# hashes and no Jekyll installed. Ruby 2.6 compatible.

require_relative 'obsidian/fence_mask'
require_relative 'obsidian/wikilinks'
require_relative 'obsidian/callouts'
require_relative 'obsidian/dataview'

module ObsidianBridge
  MD_EXTS = %w[.md .markdown].freeze

  class << self
    attr_accessor :index, :pool, :resolver
  end

  module_function

  # --------------------------------------------------------- pure helpers

  # Builds the wikilink resolution index from entry hashes
  # {path: 'vault/relative/path.md', url: '/its/url/', aliases: [...]}.
  # Keys: path without extension, unique basenames, aliases -- plus
  # downcased variants of each (Obsidian resolves case-insensitively).
  def build_index(entries)
    index = {}
    counts = Hash.new(0)
    entries.each do |e|
      key = strip_ext(e[:path].to_s)
      next if key.empty?
      url = e[:url]
      index[key] = url
      index[key.downcase] = url unless index.key?(key.downcase)
      each_alias(e[:aliases]) do |a|
        index[a] = url unless index.key?(a)
        index[a.downcase] = url unless index.key?(a.downcase)
      end
      counts[File.basename(key).downcase] += 1
    end
    entries.each do |e|
      key = strip_ext(e[:path].to_s)
      next if key.empty?
      base = File.basename(key)
      next unless counts[base.downcase] == 1
      index[base] = e[:url] unless index.key?(base)
      index[base.downcase] = e[:url] unless index.key?(base.downcase)
    end
    index
  end

  def each_alias(aliases)
    list = aliases.is_a?(Array) ? aliases : [aliases]
    list.each do |a|
      a = a.to_s
      yield a unless a.empty?
    end
  end

  def strip_ext(path)
    path.sub(%r{\A/+}, '').sub(/\.(md|markdown)\z/i, '')
  end

  # Returns a lambda mapping a wikilink target to a URL or nil.
  def resolver_for(index)
    lambda do |target|
      t = target.to_s.strip
      next nil if t.empty?
      candidates = []
      bare = t.sub(%r{\A/+}, '').sub(/\.(md|markdown)\z/i, '')
      candidates << t
      candidates << bare
      candidates << '/' + bare
      candidates << t + '/' unless t.end_with?('/')
      hit = nil
      candidates.each do |c|
        if index.key?(c)
          hit = index[c]
          break
        end
        if index.key?(c.downcase)
          hit = index[c.downcase]
          break
        end
      end
      hit
    end
  end

  # Filters the doc pool down to the FROM selection
  # ({include: [...], exclude: [...]}; '' includes everything).
  def docs_for(pool, from)
    inc = from[:include] || []
    exc = from[:exclude] || []
    selected = pool.select { |d| inc.any? { |f| path_in_folder?(d[:path], f) } }
    selected.reject { |d| exc.any? { |f| !f.empty? && path_in_folder?(d[:path], f) } }
  end

  def path_in_folder?(path, folder)
    return true if folder == ''
    path = path.to_s
    path == folder || path.start_with?(folder + '/')
  end

  # Full markdown transform: dataview fences, then wikilinks, then callouts.
  def transform(content, resolver, pool)
    out = Obsidian::FenceMask.replace_fences(content) do |info, body|
      info.downcase == 'dataview' ? render_dataview(body, pool) : nil
    end
    out = Obsidian::Wikilinks.convert(out, resolver)
    Obsidian::Callouts.convert(out)
  end

  def render_dataview(body, pool)
    parsed = Obsidian::Dataview.parse(body)
    if parsed
      docs = docs_for(pool, parsed.from)
      html = Obsidian::Dataview.render(parsed, docs)
      return "\n" + html if html
    end
    from = Obsidian::Dataview.extract_from(body) || { include: [], exclude: [] }
    docs = docs_for(pool, from)
    items = docs.map do |d|
      title = Obsidian::Dataview.escape_html((d[:title] || d[:path]).to_s)
      "<li><a href=\"#{Obsidian::Dataview.escape_html(d[:url].to_s)}\">#{title}</a></li>"
    end
    "\n<!-- obsidian-bridge: unsupported dataview query, plain listing fallback -->\n" \
      "<ul class=\"obsidian-dataview dataview-fallback\">\n#{items.join("\n")}\n</ul>\n"
  end

  # Post-render HTML pass: baseurl-prefix root-relative href/src values and
  # replace literal {{ site.url }} / {{ site.baseurl }} leftovers, skipping
  # anything inside <pre>...</pre> or <code>...</code>.
  def postprocess_html(html, baseurl, site_url = '')
    return html if baseurl.nil? || baseurl.empty?
    segments = html.split(%r{(<pre\b.*?</pre>|<code\b.*?</code>)}im)
    segments.map { |seg|
      if seg =~ /\A<(pre|code)\b/i
        seg
      else
        s = seg.gsub(/\{\{\s*site\.url\s*\}\}/, site_url.to_s + baseurl)
        s = s.gsub(/\{\{\s*site\.baseurl\s*\}\}/, baseurl)
        s.gsub(/\b(href|src)=(["'])(\/[^"']*)\2/) do
          attr = Regexp.last_match(1)
          quote = Regexp.last_match(2)
          value = Regexp.last_match(3)
          if value.start_with?('//') || value == baseurl || value.start_with?(baseurl + '/')
            "#{attr}=#{quote}#{value}#{quote}"
          else
            "#{attr}=#{quote}#{baseurl}#{value}#{quote}"
          end
        end
      end
    }.join
  end

  # ------------------------------------------------------ jekyll adapters

  def md_item?(item)
    ext = if item.respond_to?(:extname) && item.extname
            item.extname
          elsif item.respond_to?(:ext) && item.ext
            item.ext
          else
            File.extname(item.respond_to?(:path) ? item.path.to_s : '')
          end
    MD_EXTS.include?(ext.to_s.downcase)
  end

  def rel_path(item)
    p = if item.respond_to?(:relative_path) && item.relative_path
          item.relative_path
        elsif item.respond_to?(:path)
          item.path
        else
          ''
        end
    p.to_s.sub(%r{\A/+}, '')
  end
end

if defined?(Jekyll)
  Jekyll::Hooks.register :site, :pre_render do |site|
    items = []
    site.collections.each_value do |collection|
      collection.docs.each { |doc| items << doc }
    end
    site.pages.each { |page| items << page if ObsidianBridge.md_item?(page) }

    entries = items.map do |item|
      {
        path: ObsidianBridge.rel_path(item),
        url: item.url,
        aliases: item.data['aliases']
      }
    end
    static_entries = site.static_files.map do |sf|
      { path: sf.relative_path.to_s.sub(%r{\A/+}, ''), url: sf.url, aliases: [] }
    end

    ObsidianBridge.index = ObsidianBridge.build_index(entries + static_entries)
    ObsidianBridge.resolver = ObsidianBridge.resolver_for(ObsidianBridge.index)
    ObsidianBridge.pool = items.map do |item|
      path = ObsidianBridge.rel_path(item)
      {
        title: item.data['title'] || File.basename(path, '.*'),
        url: item.url,
        path: path,
        fm: item.data
      }
    end
  end

  Jekyll::Hooks.register [:documents, :pages], :pre_render do |item|
    next unless ObsidianBridge.pool && ObsidianBridge.resolver
    next unless ObsidianBridge.md_item?(item)
    content = item.content
    next if content.nil? || content.empty?
    item.content = ObsidianBridge.transform(content, ObsidianBridge.resolver, ObsidianBridge.pool)
    # Excerpts are sliced from the raw content at read time, BEFORE this hook
    # runs — layouts rendering post.excerpt would show raw [[wikilinks]].
    # Re-extract from the transformed content so excerpts match the body.
    if item.is_a?(Jekyll::Document) && item.data['excerpt'].is_a?(Jekyll::Excerpt)
      item.data['excerpt'] = Jekyll::Excerpt.new(item)
    end
  end

  Jekyll::Hooks.register [:documents, :pages], :post_render do |item|
    site = item.site
    baseurl = site.config['baseurl'].to_s
    next if baseurl.empty?
    next unless ObsidianBridge.md_item?(item)
    next if item.output.nil? || item.output.empty?
    item.output = ObsidianBridge.postprocess_html(
      item.output, baseurl, site.config['url'].to_s
    )
  end
end
