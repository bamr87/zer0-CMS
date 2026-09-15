# frozen_string_literal: true

require "date"
require "pathname"
require_relative "catalog"
require_relative "front_matter"

module Zer0Cms
  module Cms
    # Creates and duplicates content files — the only two ways this library
    # makes a new path, so both are confined:
    #
    # * the collection must be one the site declares, and its directory (and
    #   any section subdirectory, which must already exist) must resolve inside
    #   the collection after realpath;
    # * a slug is `a-z0-9` words joined by single hyphens, after common Latin
    #   accents are transliterated, cut at a word boundary to 60 characters;
    # * files are created with O_EXCL, so an existing file or a symlink planted
    #   at the target is never followed or overwritten.
    module Writer
      SLUG = /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/
      SLUG_MAX = 60
      SECTION_SEGMENT = /\A[A-Za-z0-9][A-Za-z0-9_-]*\z/
      # Letters Unicode decomposition does not reduce to ASCII.
      LETTERS = {
        "ß" => "ss", "ẞ" => "ss", "æ" => "ae", "Æ" => "ae", "œ" => "oe", "Œ" => "oe", "ø" => "o", "Ø" => "o",
        "đ" => "d", "Đ" => "d", "ð" => "d", "Ð" => "d", "þ" => "th", "Þ" => "th", "ł" => "l", "Ł" => "l",
        "ı" => "i", "ħ" => "h", "Ħ" => "h", "ŀ" => "l", "Ŀ" => "l"
      }.freeze
      # A copy must not claim the original's URL, redirects or banner.
      DUPLICATE_DROPS = %w[permalink redirect_from preview].freeze

      module_function

      def create(root, collection:, title:, slug: nil, section: nil, extras: {}, body: "", date: Date.today)
        site = Catalog.site_for(root)
        name = collection.to_s
        allowed = name == "posts" || (site.collection_names.include?(name) && name != "data")
        raise ArgumentError, "unknown collection #{name.inspect}" unless allowed

        base = Catalog.collection_directory(site, name)
        raise ArgumentError, "collection #{name} has no directory" unless base.directory? && !base.symlink?

        dir = section_dir(base, section)
        slug = slug_for(slug, title)
        filename = name == "posts" ? "#{date.iso8601}-#{slug}.md" : "#{slug}.md"
        path = dir.join(filename)
        confine!(base, path)

        data = { "title" => title.to_s, "date" => date }
        extras.to_h.each { |key, value| data[key.to_s] = value }
        text = FrontMatter.dump(data) + body.to_s.sub(/\A\n/, "")
        text << "\n" unless text.end_with?("\n")
        write_new(path, text)
        path
      end

      # Copy a file next to itself as `<stem>-copy.md` (then `-copy-2`, …):
      # a draft titled "<title> (copy)" without the original's permalink,
      # redirects or preview. With `root:`, the source must resolve inside it.
      def duplicate(path, root: nil)
        path = Pathname.new(File.expand_path(path.to_s))
        raise ArgumentError, "#{path.basename} is a symlink" if path.symlink?
        raise ArgumentError, "#{path.basename} is not a file" unless path.file?

        confine!(Pathname.new(root.to_s), path) if root
        text = File.binread(path).force_encoding("UTF-8")
        ext = path.extname
        stem = path.basename(ext).to_s
        title = FrontMatter.parse(text).data["title"].to_s
        title = stem if title.empty?
        changes = DUPLICATE_DROPS.to_h { |key| [key, nil] }.merge("draft" => true, "title" => "#{title} (copy)")
        copy_text = FrontMatter.update_keys(text, changes)

        n = 1
        loop do
          copy = path.dirname.join(n == 1 ? "#{stem}-copy#{ext}" : "#{stem}-copy-#{n}#{ext}")
          begin
            write_new(copy, copy_text)
            return copy
          rescue ArgumentError
            n += 1
            raise if n > 1000
          end
        end
      end

      def slug_for(slug, title)
        given = slug.to_s.strip
        candidate = given.empty? ? slugify(title) : truncate(transliterate(given).downcase)
        return candidate if SLUG.match?(candidate)

        raise ArgumentError, "invalid slug #{candidate.inspect}: use a-z, 0-9 and single hyphens"
      end

      def slugify(title)
        truncate(transliterate(title.to_s).downcase.gsub(/[^a-z0-9]+/, "-").gsub(/\A-+|-+\z/, ""))
      end

      def transliterate(text)
        text.to_s.scrub("").gsub(Regexp.union(LETTERS.keys), LETTERS).unicode_normalize(:nfd).gsub(/\p{Mn}/, "")
      end

      # Cut at the last hyphen at or before SLUG_MAX; a single word longer
      # than that is cut hard.
      def truncate(slug)
        return slug if slug.length <= SLUG_MAX

        head = slug[0, SLUG_MAX]
        cut = if slug[SLUG_MAX] == "-" then head
              elsif (at = head.rindex("-"))&.positive? then head[0, at]
              else head
              end
        cut.sub(/-+\z/, "")
      end

      def section_dir(base, section)
        text = section.to_s.strip
        return base if text.empty?

        segments = text.split("/")
        unless segments.all? { |segment| SECTION_SEGMENT.match?(segment) }
          raise ArgumentError, "invalid section #{text.inspect}"
        end

        dir = base.join(*segments)
        raise ArgumentError, "section #{text} does not exist" unless dir.directory?

        confine!(base, dir)
        dir
      end

      # `path` (or, when it does not exist yet, its parent) must resolve
      # strictly inside `base`.
      def confine!(base, path)
        real_base = base.realpath.to_s
        target = path.exist? || path.symlink? ? path.realpath : path.dirname.realpath.join(path.basename)
        return if target.to_s.start_with?("#{real_base}/")

        raise UnsafePath, "#{path} resolves outside #{base}"
      rescue Errno::ENOENT
        raise UnsafePath, "#{path} does not resolve inside #{base}"
      end

      def write_new(path, text)
        File.open(path.to_s, File::WRONLY | File::CREAT | File::EXCL, 0o644) { |file| file.write(text) }
      rescue Errno::EEXIST
        raise ArgumentError, "#{path.basename} already exists"
      end
    end
  end
end
