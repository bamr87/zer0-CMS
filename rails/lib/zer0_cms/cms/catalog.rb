# frozen_string_literal: true

require "date"
require "pathname"
require "yaml"
require_relative "front_matter"

module Zer0Cms
  module Cms
    # Walk a Jekyll (or zer0-mistakes) site and list markdown content files.
    module Catalog
      Entry = Struct.new(
        :path, :relative, :title, :collection, :date, :status, :draft,
        :preview, :description, :author, :tags, :categories, :data,
        keyword_init: true
      )

      Result = Struct.new(:config, :collections, :entries, keyword_init: true) do
        def total = entries.size
        def drafts = entries.count { |e| e.draft || e.status.to_s == "draft" }
        def published = total - drafts
      end

      module_function

      def scan(root)
        root = Pathname.new(root.to_s)
        config = read_config(root)
        collections_dir = config["collections_dir"].to_s
        source = config["source"].to_s
        base = root
        base = base.join(source) unless source.empty?
        content_root = collections_dir.empty? ? base : base.join(collections_dir)

        names = collection_names(config, content_root)
        entries = names.flat_map { |name| scan_collection(root, content_root, name) }
        Result.new(config: config, collections: names, entries: entries.sort_by { |e| [e.date.to_s, e.relative] }.reverse)
      end

      def read_config(root)
        file = Pathname.new(root).join("_config.yml")
        return {} unless file.file?

        data = YAML.safe_load(file.read, aliases: true, permitted_classes: [Date, Time, Symbol])
        data.is_a?(Hash) ? data : {}
      rescue Psych::SyntaxError
        {}
      end

      def content_root_for(root)
        root = Pathname.new(root.to_s)
        config = read_config(root)
        collections_dir = config["collections_dir"].to_s
        source = config["source"].to_s
        base = root
        base = base.join(source) unless source.empty?
        collections_dir.empty? ? base : base.join(collections_dir)
      end

      def collection_dir(root, name)
        content_root_for(root).join("_#{name.to_s.delete_prefix("_")}")
      end

      def media(root)
        root = Pathname.new(root.to_s)
        globs = %w[assets/**/*.{png,jpg,jpeg,svg,webp,gif} images/**/*.{png,jpg,jpeg,svg,webp,gif}]
        globs.flat_map { |pattern| Pathname.glob(root.join(pattern)) }
             .select(&:file?)
             .uniq
             .sort_by { |path| path.mtime }
             .reverse
      end

      def collection_names(config, content_root)
        declared = Array(config.dig("collections")&.keys || config["collections"])
        declared = [] unless declared.all? { |item| item.is_a?(String) }
        on_disk = content_root.directory? ? content_root.children.select(&:directory?).map { |d| d.basename.to_s.delete_prefix("_") } : []
        (["posts"] + declared + on_disk).map(&:to_s).uniq.select do |name|
          content_root.join("_#{name}").directory?
        end
      end

      def scan_collection(root, content_root, name)
        dir = content_root.join("_#{name}")
        return [] unless dir.directory?

        dir.glob("**/*.md").sort.filter_map do |path|
          next if path.basename.to_s.start_with?(".")

          doc = FrontMatter.parse(path.read)
          data = doc.data
          Entry.new(
            path: path.to_s,
            relative: path.relative_path_from(root).to_s,
            title: data["title"].to_s.empty? ? path.basename(".md").to_s : data["title"].to_s,
            collection: name,
            date: data["date"].to_s,
            status: data["status"].to_s,
            draft: truthy?(data["draft"]),
            preview: (data["preview"].to_s.empty? ? data["image"].to_s : data["preview"].to_s),
            description: data["description"].to_s,
            author: data["author"].to_s,
            tags: Array(data["tags"]),
            categories: Array(data["categories"]),
            data: data
          )
        end
      end

      def truthy?(value)
        value == true || value.to_s == "true" || value.to_s == "1"
      end
    end
  end
end
