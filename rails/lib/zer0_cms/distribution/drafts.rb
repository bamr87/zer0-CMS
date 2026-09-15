# frozen_string_literal: true

require "fileutils"

module Zer0Cms
  module Distribution
    # The governed draft queue — the folder proposed posts wait in, and the
    # only place publishing reads from.
    #
    # The dialect is the one the VS Code extension (src/core/governance/drafts.ts)
    # and the Python publisher already share, so a queue written by any of them
    # reads the same here:
    #
    #   type:   article | update   (`text` is accepted for update; default article)
    #   status: pending | approved | published   (default pending)
    #   source: the page an article shares (a path, or a Python-style
    #           `section/YYYY-MM-DD-slug` reference)
    #   title / description / link: an article's own card, when it shares
    #           something other than a page of this site
    #   no_thumbnail: true to post without a card image
    #
    # The body is the text that publishes. Top-level `*.md` files only, so an
    # `examples/` folder never publishes, and a file with no front matter (a
    # README) is documentation, not a draft.
    #
    # A new draft is always `pending`: creating a draft and approving one are
    # different acts, and only the second is a person's decision. Status changes
    # are line surgery through `Cms::FrontMatter.update_keys`, so approving is a
    # one-line diff in review.
    module Drafts
      STATUSES = %w[pending approved published].freeze
      TYPES = %w[article update].freeze
      ID = /\A[A-Za-z0-9][A-Za-z0-9._-]{0,150}\z/
      SLUG = /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/

      Draft = Struct.new(:path, :relative, :meta, :body, :errors, keyword_init: true) do
        def id
          File.basename(path, ".md")
        end

        def status
          value = meta["status"].to_s.strip.downcase
          value.empty? ? "pending" : value
        end

        def type
          value = meta["type"].to_s.strip.downcase
          return "article" if value.empty?

          value == "text" ? "update" : value
        end

        def update?
          type == "update"
        end

        def commentary
          text = body.to_s.strip
          text.empty? ? meta["commentary"].to_s.strip : text
        end

        %w[source link title description].each do |key|
          define_method(key) { meta[key].to_s.strip }
        end

        def no_thumbnail?
          [true, "true", "yes", "1"].include?(meta["no_thumbnail"])
        end
      end

      module_function

      def directory(config)
        config.path(config.queue)
      end

      def list(config)
        dir = directory(config)
        return [] unless File.directory?(dir)

        Dir.children(dir).sort.filter_map do |name|
          full = File.join(dir, name)
          next unless name.end_with?(".md") && File.file?(full) && !File.symlink?(full)

          draft = read(config, full)
          draft.meta.empty? ? nil : draft
        end
      end

      def read(config, path)
        text = File.read(path, encoding: "UTF-8")
        doc = Cms::FrontMatter.parse(text)
        Draft.new(path: path, relative: Pathname.new(path).relative_path_from(Pathname.new(config.root)).to_s,
                  meta: doc.data.transform_keys(&:to_s), body: doc.body, errors: doc.errors)
      end

      # By id (`2026-07-30-x`), filename (`2026-07-30-x.md`) or queue path.
      def find(config, ref)
        name = File.basename(ref.to_s.strip)
        name = name.delete_suffix(".md")
        raise ArgumentError, "not a draft id: #{ref.inspect}" unless ID.match?(name)

        list(config).find { |draft| draft.id == name }
      end

      def find!(config, ref)
        find(config, ref) || raise(ArgumentError, "no draft named #{ref.inspect} in #{config.queue}")
      end

      # Write a new pending draft and return it. A name collision becomes
      # `-2`, `-3`, … — the queue is append-only from this direction.
      def create(config, type:, slug:, body:, meta: {})
        raise ArgumentError, "type must be article or update" unless TYPES.include?(type.to_s)
        raise ArgumentError, "draft slug must be lowercase words joined by hyphens: #{slug.inspect}" unless SLUG.match?(slug.to_s)
        raise ArgumentError, "a draft needs a body" if body.to_s.strip.empty? && type.to_s == "update"

        fields = { "type" => type.to_s, "status" => "pending" }
        meta.each do |key, value|
          next if key.to_s == "status" || value.nil? || value.to_s.empty?

          fields[key.to_s] = value.to_s
        end
        text = "#{Cms::FrontMatter.dump(fields)}\n#{body.to_s.strip}\n"
        dir = directory(config)
        FileUtils.mkdir_p(dir)
        path = exclusive_write(dir, slug.to_s, text)
        read(config, path)
      end

      # Flip `status` (and set any `extra` keys) by line surgery.
      def set_status(draft, status, extra = {})
        raise ArgumentError, "unknown status #{status.inspect}" unless STATUSES.include?(status)

        text = File.read(draft.path, encoding: "UTF-8")
        updated = Cms::FrontMatter.update_keys(text, { "status" => status }.merge(extra))
        File.write(draft.path, updated) unless updated == text
        status
      end

      def exclusive_write(dir, slug, text)
        (1..100).each do |n|
          path = File.join(dir, n == 1 ? "#{slug}.md" : "#{slug}-#{n}.md")
          begin
            File.open(path, File::WRONLY | File::CREAT | File::EXCL, 0o644) { |file| file.write(text) }
            return path
          rescue Errno::EEXIST
            next
          end
        end
        raise ArgumentError, "too many drafts named #{slug}"
      end
    end
  end
end
