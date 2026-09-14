# frozen_string_literal: true

require "date"
require "pathname"
require "time"
require "yaml"
require_relative "front_matter"

module Zer0Cms
  module Cms
    # A path from a site's configuration or a request that resolves outside
    # the site root.
    class UnsafePath < StandardError; end

    # Walk a Jekyll (or zer0-mistakes) site and list what Jekyll itself would
    # read as content — the same files, under the same rules, in stdlib Ruby.
    #
    # The rules are transcribed from Jekyll 4.4's reader, not approximated:
    #
    # * `source:` moves the whole tree; every path below is relative to it.
    # * A directory entry is skipped when it is excluded (`exclude:` plus
    #   Jekyll's DEFAULT_EXCLUDES — matched by fnmatch, by *prefix*, or as a
    #   directory) and not `include:`d, or when it starts with `.`, `_`, `#`
    #   or `~` or ends with `~` (and is not `include:`d). That single rule is
    #   why `_data`, `_includes`, `_layouts`, `_site` and a `_templates`
    #   folder inside a collection are never content.
    # * A file outside a collection is a *page* when its first line is `---`;
    #   an `include:`d file the walk never reached is read as one too.
    # * `_posts` is read only inside `collections_dir` (or anywhere, when no
    #   `collections_dir` is set); a post needs a `YYYY-MM-DD-slug.ext` name
    #   and does not strictly need front matter. `_drafts` needs only an
    #   extension. A post or draft that is not valid UTF-8 is skipped.
    # * A declared collection (a map, or the legacy list form) lives at
    #   `<collections_dir>/_<name>`; `posts` and `data` are special and never
    #   read this way. A file in it is a *document* only with front matter.
    # * `published: false` and a future date are recorded, not hidden — a
    #   CMS shows what the build would skip; it does not pretend it is gone.
    #
    # Where this deliberately differs from Jekyll it is stricter, never looser:
    # only content extensions (markdown and HTML) become entries — the rest
    # are counted in `skipped` — every symlink is skipped (Jekyll's safe mode
    # skips only those leaving the source), and a `source:` or
    # `collections_dir:` that resolves outside the site root raises
    # UnsafePath instead of being followed.
    #
    # `bin/jekyll-parity` diffs this walk against Jekyll's own reader on any
    # site; test/fixtures/jekyll-site*.expected.json carry the lists that
    # script generated, so the stdlib test does not need the jekyll gem.
    module Catalog
      DEFAULT_EXCLUDES = %w[
        .sass-cache .jekyll-cache
        gemfiles Gemfile Gemfile.lock
        node_modules
        vendor/bundle/ vendor/cache/ vendor/gems/ vendor/ruby/
      ].freeze
      DEFAULT_INCLUDES = %w[.htaccess].freeze
      SPECIAL_LEADING = /\A[._#~]/
      SPECIAL_COLLECTIONS = %w[posts data].freeze
      DATE_FILENAME = %r{^(?>.+/)*?(\d{2,4}-\d{1,2}-\d{1,2})-([^/]*)(\.[^.]+)$}
      # Jekyll's DATELESS_FILENAME_MATCHER, %r{^(?:.+/)*(.*)(\.[^.]+)$}, only ever
      # asks "does the path end in a dot and at least one non-dot?". Its nested
      # quantifiers backtrack polynomially on a crafted name (CodeQL rb/redos),
      # so the same question is asked without them.
      DATELESS_FILENAME = /\.[^.\n]+\z/
      CONTENT_EXTENSIONS = %w[.md .markdown .mkd .mkdn .mdown .html .htm].freeze
      IMAGE_EXTENSIONS = %w[.png .jpg .jpeg .svg .webp .gif].freeze
      KINDS = %i[page post draft document].freeze

      Entry = Struct.new(
        :path, :relative, :source_relative, :kind, :collection,
        :title, :date, :date_raw, :lastmod, :status, :draft, :published, :future,
        :layout, :permalink, :preview, :description, :author, :tags, :categories,
        :data, :front_matter, :error,
        keyword_init: true
      ) do
        def live?
          !draft && published && !future && status.to_s != "draft"
        end
      end

      Result = Struct.new(:config, :root, :source, :collections_dir, :collections, :entries, :errors, :skipped, keyword_init: true) do
        def total = entries.size
        def drafts = entries.count { |e| e.draft || e.kind == :draft || e.status.to_s == "draft" }
        def unpublished = entries.count { |e| !e.published }
        def scheduled = entries.count(&:future)
        def published = entries.count(&:live?)
        def by_collection = entries.group_by(&:collection).transform_values(&:size)
      end

      # Everything the walk needs to know about a site, resolved once.
      # `collections_dir_raw` is the configured string, kept for Jekyll's
      # plain-prefix posts test; `collections_dir` is the cleaned relative path.
      Site = Struct.new(:root, :source, :config, :collections_dir, :collections_dir_raw, :excludes, :includes,
                        :destination, :collection_names, keyword_init: true) do
        def in_source(*parts)
          parts = parts.map { |p| p.to_s.sub(%r{\A/+}, "") }.reject(&:empty?)
          parts.empty? ? source : source.join(*parts)
        end
      end

      module_function

      def scan(root, now: Time.now)
        site = site_for(root)
        entries = []
        errors = []
        skipped = Hash.new(0)
        read_directories(site, "", entries, errors, skipped)
        read_included_files(site, entries, errors, skipped)
        read_collections(site, entries, errors, skipped)
        entries.each { |e| e.future = !!(e.date && e.date > now) }
        Result.new(
          config: site.config, root: site.root, source: site.source,
          collections_dir: site.collections_dir, collections: site.collection_names,
          entries: sort_entries(entries), errors: errors, skipped: skipped
        )
      end

      # Raises UnsafePath when `source:` or `collections_dir:` resolves
      # outside the root (lexically, or through a symlink).
      def site_for(root)
        root = Pathname.new(File.expand_path(root.to_s)).realpath
        config = read_config(root)
        source = confine(root, root, config["source"], "source")
        raw_collections_dir = config["collections_dir"].to_s
        collections_dir = confine(root, source, raw_collections_dir, "collections_dir")
        collections_rel = collections_dir == source ? "" : collections_dir.relative_path_from(source).to_s
        excludes = (config["exclude"].nil? ? [] : Array(config["exclude"])) + DEFAULT_EXCLUDES
        includes = config["include"].nil? ? DEFAULT_INCLUDES.dup : Array(config["include"])
        destination = config["destination"].to_s.strip
        destination = Pathname.new(File.expand_path(destination.empty? ? "_site" : destination, root.to_s))
        Site.new(
          root: root, source: source, config: config,
          collections_dir: collections_rel, collections_dir_raw: raw_collections_dir,
          excludes: excludes.uniq, includes: includes, destination: destination,
          collection_names: (["posts"] + declared_collections(config)).uniq
        )
      end

      def confine(root, base, value, key)
        text = value.to_s.strip
        return base if text.empty? || text == "."

        target = Pathname.new(File.expand_path(text, base.to_s))
        resolved = resolve(target)
        return resolved if inside?(root, target) && inside?(root, resolved)

        raise UnsafePath, "#{key}: #{text.inspect} resolves outside the site root"
      end

      # realpath of the deepest existing ancestor, plus the rest.
      def resolve(path)
        return path.realpath if path.exist?

        parent = path.dirname
        return path if parent == path

        resolve(parent).join(path.basename)
      end

      def inside?(root, path)
        path.to_s == root.to_s || path.to_s.start_with?("#{root.to_s.chomp("/")}/")
      end

      def read_config(root)
        file = Pathname.new(root).join("_config.yml")
        return {} unless file.file?

        data = YAML.safe_load(file.read, aliases: true, permitted_classes: [Date, Time, Symbol])
        data.is_a?(Hash) ? data : {}
      rescue Psych::Exception
        {}
      end

      # Declared collections in either form — a map, or the legacy plain list
      # — with Jekyll's label sanitising.
      def declared_collections(config)
        raw = config["collections"]
        names = case raw
                when Hash then raw.keys
                when Array then raw
                else []
                end
        names.map { |n| n.to_s.gsub(/[^a-z0-9_\-.]/i, "") }.reject { |n| n.empty? || n == "posts" }
      end

      # ---- pages, posts and drafts (Jekyll::Reader#read_directories) --------

      def read_directories(site, dir, out, errors, skipped)
        base = site.in_source(dir)
        return unless base.directory?

        names = filter_entries(site, Dir.entries(base.to_s), dir)
        dirs = []
        pages = []
        names.each do |name|
          path = base.join(name)
          if path.symlink?
            skipped[:symlinks] += 1
          elsif path.directory?
            dirs << name
          elsif yaml_header?(path)
            pages << name
          end
        end

        read_posts(site, dir, out, errors, skipped) unless outside_collections_dir?(site, dir)
        dirs.each do |name|
          next if site.destination.to_s == base.join(name).to_s

          read_directories(site, "#{dir}/#{name}", out, errors, skipped)
        end
        pages.each do |name|
          rel = "#{dir}/#{name}".sub(%r{\A/}, "")
          add_page(site, rel, out, errors, skipped)
        end
      end

      def add_page(site, rel, out, errors, skipped)
        unless content_extension?(rel)
          skipped[:non_content_pages] += 1
          return
        end
        out << build_entry(site, site.in_source(rel), rel, :page, "pages", errors)
      end

      # Jekyll::Reader#read_included_excludes: an `include:` entry naming a
      # file with front matter that the walk did not reach is still a page.
      def read_included_files(site, out, errors, skipped)
        site.includes.each do |entry|
          next unless entry.is_a?(String)

          path = Pathname.new(sanitized_path(site.source.to_s, entry))
          next if path.directory? || !path.file?

          if path.symlink?
            skipped[:symlinks] += 1
            next
          end
          next unless yaml_header?(path)

          rel = path.relative_path_from(site.source).to_s
          next if out.any? { |e| e.kind == :page && e.source_relative == rel }

          add_page(site, rel, out, errors, skipped)
        end
      end

      # Jekyll.sanitized_path: the questionable path is forced under base.
      def sanitized_path(base, questionable)
        clean = questionable.start_with?("~") ? "/#{questionable}" : questionable
        clean = File.expand_path(clean, "/")
        return clean if clean == base

        clean = clean.squeeze("/")
        return clean if clean.start_with?("#{base}/")

        File.join(base, clean.sub(%r{\A\w:/}, "/"))
      end

      # Jekyll reads `_posts`/`_drafts` from every directory when there is no
      # collections_dir, and only from within it when there is one. The
      # comparison is a plain prefix test on a `/`-led path with the value as
      # configured, exactly as Jekyll does it (so `/pagesx` counts as inside
      # `pages` — a quirk kept on purpose so the two readers agree).
      def outside_collections_dir?(site, dir)
        return false if site.collections_dir_raw.empty?

        !dir.start_with?("/#{site.collections_dir_raw}")
      end

      def read_posts(site, dir, out, errors, skipped)
        publishable_entries(site, dir, "_posts", skipped).each do |rel_in_posts|
          unless DATE_FILENAME.match?(rel_in_posts)
            skipped[:undated_posts] += 1
            next
          end
          add_post(site, "#{dir}/_posts/#{rel_in_posts}", :post, out, errors, skipped)
        end
        publishable_entries(site, dir, "_drafts", skipped).each do |rel_in_drafts|
          unless DATELESS_FILENAME.match?(rel_in_drafts)
            skipped[:extensionless_drafts] += 1
            next
          end
          add_post(site, "#{dir}/_drafts/#{rel_in_drafts}", :draft, out, errors, skipped)
        end
      end

      def add_post(site, rel, kind, out, errors, skipped)
        rel = rel.sub(%r{\A/}, "")
        full = site.in_source(rel)
        unless content_extension?(rel)
          skipped[:non_content_posts] += 1
          return
        end
        unless File.binread(full).force_encoding("UTF-8").valid_encoding?
          skipped[:invalid_utf8_posts] += 1
          return
        end
        out << build_entry(site, full, rel, kind, "posts", errors)
      end

      # Jekyll::Reader#get_entries — every file under <dir>/<magic_dir> (a
      # glob without FNM_DOTMATCH), filtered with the magic dir as the base.
      def publishable_entries(site, dir, magic_dir, skipped)
        base = site.in_source(dir, magic_dir)
        return [] unless base.exist?

        if base.symlink?
          skipped[:symlinks] += 1
          return []
        end
        relatives = Dir.glob("**/*", base: base.to_s)
        filter_entries(site, relatives, "#{dir}/#{magic_dir}").sort.reject do |entry|
          path = base.join(entry)
          (skipped[:symlinks] += 1) if path.symlink?
          path.symlink? || path.directory?
        end
      end

      # ---- declared collections (Jekyll::Collection#read) --------------------

      def read_collections(site, out, errors, skipped)
        site.collection_names.each do |label|
          next if SPECIAL_COLLECTIONS.include?(label)

          dir = collection_directory(site, label)
          next unless dir.directory?

          if dir.symlink?
            skipped[:symlinks] += 1
            next
          end
          relatives = Dir.glob("**/*", File::FNM_DOTMATCH, base: dir.to_s)
          # Jekyll filters these with base "_<label>" — relative to the
          # source, NOT to collections_dir. Mirrored, quirk included.
          filter_entries(site, relatives, "_#{label}").sort.each do |rel_in_collection|
            full = dir.join(rel_in_collection)
            if full.symlink?
              skipped[:symlinks] += 1
              next
            end
            next if full.directory?
            next unless yaml_header?(full)

            unless content_extension?(rel_in_collection)
              skipped[:non_content_documents] += 1
              next
            end
            rel = full.relative_path_from(site.source).to_s
            out << build_entry(site, full, rel, :document, label, errors)
          end
        end
      end

      def collection_directory(site, label)
        site.in_source(site.collections_dir, "_#{label}")
      end

      def content_extension?(path)
        CONTENT_EXTENSIONS.include?(File.extname(path).downcase)
      end

      # ---- the entry filter (Jekyll::EntryFilter) ----------------------------

      # `entries` are paths relative to `base_dir` (itself relative to the
      # source, `/`-led or empty). Returns the entries Jekyll would keep.
      def filter_entries(site, entries, base_dir)
        entries.reject do |entry|
          next true if entry.end_with?(".")

          included = included?(site, entry)
          next true if excluded?(site, entry, base_dir) && !included
          next false if included

          special?(entry) || entry.end_with?("~")
        end
      end

      def included?(site, entry)
        glob_include?(site, site.includes, entry) || glob_include?(site, site.includes, File.basename(entry))
      end

      def excluded?(site, entry, base_dir)
        relative = base_dir.to_s.empty? ? entry : File.join(base_dir.to_s.sub(%r{\A/}, ""), entry)
        glob_include?(site, site.excludes - site.includes, relative)
      end

      def special?(entry)
        SPECIAL_LEADING.match?(entry) || SPECIAL_LEADING.match?(File.basename(entry))
      end

      # Jekyll::EntryFilter#glob_include?: fnmatch (no flags, so `*` crosses
      # `/`), or a bare prefix match, or directory equality with a trailing
      # slash. All three are Jekyll's; the prefix one is the surprising one.
      def glob_include?(site, patterns, entry)
        entry_with_source = File.join(site.source.to_s, entry.to_s)
        entry_is_directory = File.directory?(entry_with_source)
        patterns.any? do |pattern|
          next false unless pattern.is_a?(String)

          pattern_with_source = File.join(site.source.to_s, pattern)
          File.fnmatch?(pattern_with_source, entry_with_source) ||
            entry_with_source.start_with?(pattern_with_source) ||
            (entry_is_directory && pattern_with_source == "#{entry_with_source}/")
        end
      end

      def yaml_header?(path)
        File.open(path, "rb") { |f| f.readline.match?(/\A---\s*\r?\n/) }
      rescue EOFError, SystemCallError
        false
      end

      # ---- one entry -----------------------------------------------------------

      def build_entry(site, full, source_relative, kind, collection, errors)
        raw = File.binread(full).force_encoding("UTF-8")
        error = nil
        unless raw.valid_encoding?
          raw = raw.scrub("\uFFFD")
          error = "not valid UTF-8"
        end
        data = {}
        begin
          data = FrontMatter.parse(raw, strict: true).data
        rescue Psych::Exception, ArgumentError => e
          error = "front matter: #{e.message.lines.first.to_s.strip}"
          data = {}
        end
        errors << { path: full.to_s, message: error } if error

        slug = File.basename(source_relative, File.extname(source_relative))
        filename_date = nil
        if kind == :post && (m = DATE_FILENAME.match(source_relative))
          filename_date = m[1]
          slug = m[2]
        end
        date, date_raw = resolve_date(data["date"], filename_date)
        lastmod, = resolve_date(data["lastmod"], nil)

        Entry.new(
          path: full.to_s,
          relative: full.relative_path_from(site.root).to_s,
          source_relative: source_relative,
          kind: kind,
          collection: collection,
          title: entry_title(data["title"], slug, kind),
          date: date, date_raw: date_raw, lastmod: lastmod,
          status: data["status"].to_s,
          draft: truthy?(data["draft"]) || kind == :draft,
          published: !(data.key?("published") && data["published"] == false),
          future: false,
          layout: data["layout"].to_s,
          permalink: data["permalink"].to_s,
          preview: (data["preview"].to_s.empty? ? data["image"].to_s : data["preview"].to_s),
          description: data["description"].to_s,
          author: data["author"].is_a?(Hash) ? data["author"]["name"].to_s : data["author"].to_s,
          tags: Array(data["tags"]).map(&:to_s),
          categories: Array(data["categories"] || data["category"]).flatten.map(&:to_s),
          data: data,
          front_matter: FrontMatter::BLOCK.match?(raw.delete_prefix(FrontMatter::BOM)),
          error: error
        )
      end

      def entry_title(title, slug, kind)
        return title.to_s unless title.nil? || title.to_s.empty?
        return slug.split(/[-_]/).map(&:capitalize).join(" ") if kind == :post || kind == :draft

        slug
      end

      # A YAML date (Date/Time) is used as is; a string goes through
      # Time.parse, as Jekyll's Utils.parse_date does; anything else (a
      # Liquid placeholder parsed as a mapping, a number) is unparseable and
      # sorts last. The filename date is the fallback for posts only.
      def resolve_date(value, filename_date)
        raw = value.nil? ? filename_date.to_s : value.to_s
        candidate = value.nil? ? filename_date : value
        return [nil, raw] if candidate.nil?

        parsed = case candidate
                 when Time then candidate
                 when DateTime then candidate.to_time
                 when Date then Time.new(candidate.year, candidate.month, candidate.day)
                 when String then (candidate.strip.empty? ? nil : Time.parse(candidate))
                 end
        [parsed, raw]
      rescue ArgumentError, TypeError
        [nil, raw]
      end

      def sort_entries(entries)
        dated, undated = entries.partition(&:date)
        dated.sort_by { |e| [-e.date.to_i, e.source_relative] } + undated.sort_by(&:source_relative)
      end

      def truthy?(value)
        value == true || value.to_s == "true" || value.to_s == "1"
      end

      # ---- helpers the rest of the app uses -------------------------------------

      def content_root_for(root)
        site = site_for(root)
        site.in_source(site.collections_dir)
      end

      def collection_dir(root, name)
        label = name.to_s.delete_prefix("_").gsub(/[^a-z0-9_\-.]/i, "")
        content_root_for(root).join("_#{label}")
      end

      # Images under the *source*'s assets/ and images/ trees, plus the
      # image generator's output_dir when the site names one and it stays
      # inside the root. Symlinks are skipped, like everywhere else.
      def media(root)
        site = site_for(root)
        dirs = %w[assets images]
        output_dir = site.config.dig("preview_images", "output_dir").to_s.strip
        dirs << output_dir unless output_dir.empty?
        pattern = "**/*{#{IMAGE_EXTENSIONS.join(",")}}"
        dirs.uniq.flat_map do |d|
          base = begin
            confine(site.root, site.source, d, "preview_images.output_dir")
          rescue UnsafePath
            next []
          end
          next [] unless base.directory? && !base.symlink?

          Dir.glob(pattern, File::FNM_CASEFOLD, base: base.to_s).map { |rel| base.join(rel) }
        end.select { |p| p.file? && !p.symlink? }
           .uniq
           .sort_by(&:mtime)
           .reverse
      end
    end
  end
end
