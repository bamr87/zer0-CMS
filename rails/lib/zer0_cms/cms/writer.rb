# frozen_string_literal: true

require "date"
require "fileutils"
require_relative "catalog"
require_relative "front_matter"

module Zer0Cms
  module Cms
    module Writer
      module_function

      def create(root, collection:, title:, slug: nil, extras: {}, body: "")
        root = Pathname.new(root.to_s)
        collection = collection.to_s.delete_prefix("_")
        dir = Catalog.collection_dir(root, collection)
        raise ArgumentError, "unknown collection #{collection}" unless dir.directory?

        slug = slug.to_s.strip
        slug = slugify(title) if slug.empty?
        filename = collection == "posts" ? "#{Date.today.iso8601}-#{slug}.md" : "#{slug}.md"
        path = dir.join(filename)
        raise ArgumentError, "#{path.basename} already exists" if path.exist?

        extras = extras.to_h.transform_keys(&:to_s)
        extras["title"] = title
        extras["date"] ||= Date.today.iso8601
        lines = ["---"]
        extras.each { |key, value| lines << "#{key}: #{FrontMatter.yaml_value(value)}" }
        lines << "---"
        lines << body.to_s.sub(/\A\n/, "")
        lines << "" unless lines.last.end_with?("\n")
        File.write(path, "#{lines.join("\n").rstrip}\n")
        path
      end

      def duplicate(path)
        path = Pathname.new(path.to_s)
        stem = path.basename(".md").to_s
        copy = path.dirname.join("#{stem}-copy.md")
        n = 2
        while copy.exist?
          copy = path.dirname.join("#{stem}-copy-#{n}.md")
          n += 1
        end
        FileUtils.cp(path, copy)
        copy
      end

      def slugify(title)
        title.to_s.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/\A-|-\z/, "")[0, 60]
      end
    end
  end
end
