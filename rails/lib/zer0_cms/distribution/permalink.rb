# frozen_string_literal: true

module Zer0Cms
  module Distribution
    # The URL Jekyll 4.4 gives a page, post or collection document — the
    # canonical URL an article share links to and the ledger is keyed by.
    #
    # Transcribed from Jekyll's `URL`, `Drops::UrlDrop`, `Document#url` and
    # `Page#template`, for the parts a zer0 site uses:
    #
    # * a `permalink:` in the file's front matter wins, then one set by a
    #   matching `defaults:` scope, then the collection's `permalink`, then
    #   (posts only) the site's `permalink` style, then Jekyll's defaults;
    # * placeholders — `:collection :path :name :title :slug :categories :year
    #   :month :day :i_month :i_day :short_year :y_day :output_ext :basename` —
    #   are filled the way UrlDrop fills them, including Jekyll's slugify;
    # * the result is sanitized as `URL#sanitize_url` does it.
    #
    # One deliberate simplification: `:year`, `:month` and `:day` come from the
    # calendar date as written (`2026-07-08…` → 2026/07/08), not from a time
    # converted to the build machine's zone. On a site that follows its own
    # lint rule — the filename date equals the `date` field — the two agree.
    module Permalink
      STYLES = {
        "date" => "/:categories/:year/:month/:day/:title:output_ext",
        "pretty" => "/:categories/:year/:month/:day/:title/",
        "ordinal" => "/:categories/:year/:y_day/:title:output_ext",
        "weekdate" => "/:categories/:year/W:week/:short_day/:title:output_ext",
        "none" => "/:categories/:title:output_ext"
      }.freeze
      COLLECTION_DEFAULT = "/:collection/:path:output_ext"
      TOKEN = /:(output_ext|short_year|i_month|i_day|y_day|collection|categories|basename|path|name|title|slug|year|month|day)/
      SLUG_DEFAULT = /[^\p{M}\p{L}\p{Nd}]+/
      SLUG_PRETTY = /[^\p{M}\p{L}\p{Nd}._~!$&'()+,;=@]+/
      SAFE_PATH = %r{[^a-zA-Z0-9_.\-~!$&'()*+,;=:@/]}

      module_function

      # The site-relative URL path, or nil for a draft (it has none).
      def path_for(site_config, entry)
        return nil if entry.kind == :draft

        template = entry.permalink.to_s.strip
        template = default_permalink(site_config, entry).to_s if template.empty?
        template = implicit_template(site_config, entry) if template.empty?
        sanitize(fill(template, placeholders(entry)))
      end

      def implicit_template(site_config, entry)
        case entry.kind
        when :post
          collection_permalink(site_config, "posts") || style(site_config["permalink"])
        when :document
          collection_permalink(site_config, entry.collection) || COLLECTION_DEFAULT
        else
          page_template(site_config, entry)
        end
      end

      def collection_permalink(site_config, label)
        collections = site_config["collections"]
        return nil unless collections.is_a?(Hash) && collections[label].is_a?(Hash)

        value = collections[label]["permalink"].to_s.strip
        value.empty? ? nil : style(value)
      end

      def style(value)
        text = value.to_s.strip
        text = "date" if text.empty?
        STYLES.fetch(text, text)
      end

      # Jekyll's front-matter defaults: every scope whose path prefixes the
      # file and whose type matches it; the longest path wins, a later entry
      # breaks a tie.
      def default_permalink(site_config, entry)
        best = nil
        Array(site_config["defaults"]).each_with_index do |default, index|
          next unless default.is_a?(Hash) && default["values"].is_a?(Hash) && default["values"].key?("permalink")

          scope = default["scope"].is_a?(Hash) ? default["scope"] : {}
          scope_path = scope["path"].to_s.delete_prefix("/").chomp("/")
          next unless scope_path.empty? || entry.source_relative.to_s == scope_path ||
                      entry.source_relative.to_s.start_with?("#{scope_path}/")

          type = scope["type"].to_s
          next unless type.empty? || type == type_of(entry)

          rank = [scope_path.length, type.empty? ? 0 : 1, index]
          best = [rank, default["values"]["permalink"]] if best.nil? || (rank <=> best[0]) >= 0
        end
        best&.last
      end

      def type_of(entry)
        case entry.kind
        when :post then "posts"
        when :document then entry.collection.to_s
        else "pages"
        end
      end

      def page_template(site_config, entry)
        return "/:path/" if File.basename(entry.source_relative.to_s, ".*") == "index"

        permalink = style(site_config["permalink"])
        suffix = if site_config["permalink"].to_s.strip == "pretty" || permalink.end_with?("/") then "/"
                 else ":output_ext"
                 end
        "/:path/:basename#{suffix}"
      end

      def placeholders(entry)
        source = entry.source_relative.to_s
        ext = File.extname(source)
        basename = File.basename(source, ext)
        slug_source = entry.data.is_a?(Hash) && entry.data["slug"].is_a?(String) ? entry.data["slug"] : filename_slug(basename, entry.kind)
        year, month, day = calendar(entry)
        values = {
          "collection" => entry.kind == :page ? nil : (entry.kind == :post ? "posts" : entry.collection.to_s),
          "path" => entry.kind == :page ? page_dir(source) : cleaned_relative_path(entry, source, ext),
          "basename" => basename,
          "name" => slugify(basename),
          "title" => slugify(slug_source, mode: "pretty", cased: true),
          "slug" => slugify(slug_source),
          "categories" => categories(entry),
          "output_ext" => ".html"
        }
        if year
          time = Time.utc(year, month, day)
          values.merge!("year" => format("%04d", year), "month" => format("%02d", month), "day" => format("%02d", day),
                        "i_month" => month.to_s, "i_day" => day.to_s, "short_year" => time.strftime("%y"),
                        "y_day" => time.strftime("%j"))
        end
        values
      end

      def calendar(entry)
        raw = entry.date_raw.to_s
        if (match = /\A(\d{4})-(\d{1,2})-(\d{1,2})/.match(raw))
          return [match[1].to_i, match[2].to_i, match[3].to_i]
        end
        return [entry.date.year, entry.date.month, entry.date.day] if entry.date

        [nil, nil, nil]
      end

      def filename_slug(basename, kind)
        kind == :post ? basename.sub(/\A\d{2,4}-\d{1,2}-\d{1,2}-/, "") : basename
      end

      # `Document#cleaned_relative_path`: the path under the collection's
      # directory, without the extension, with a leading slash.
      def cleaned_relative_path(entry, source, ext)
        label = entry.kind == :post ? "posts" : entry.collection.to_s
        marker = "_#{label}/"
        index = source.index(marker)
        tail = index ? source[(index + marker.length)..] : File.basename(source)
        "/#{tail.delete_suffix(ext).sub(/\.*\z/, "")}"
      end

      def page_dir(source)
        dir = File.dirname(source)
        dir == "." ? "" : dir
      end

      def categories(entry)
        return "" unless entry.data.is_a?(Hash)

        Array(entry.data["categories"] || entry.data["category"]).flatten.map { |c| c.to_s.downcase }.uniq.join("/")
      end

      def slugify(text, mode: "default", cased: false)
        return nil if text.nil?

        slug = text.to_s.gsub(mode == "pretty" ? SLUG_PRETTY : SLUG_DEFAULT, "-").gsub(/^-|-$/, "")
        cased ? slug : slug.downcase
      end

      def fill(template, values)
        template.gsub(%r{/?#{TOKEN}}) do |whole|
          key = Regexp.last_match(1)
          lead = whole.start_with?("/") ? "/" : ""
          value = values[key]
          next whole unless values.key?(key)
          next "" if value.nil?

          "#{lead}#{value.to_s.gsub(SAFE_PATH) { |c| c.bytes.map { |b| format("%%%02X", b) }.join }}"
        end
      end

      def sanitize(path)
        "/#{path}".gsub("..", "/").gsub("./", "").squeeze("/")
      end
    end
  end
end
