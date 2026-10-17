# frozen_string_literal: true

require "date"
require "fileutils"
require "yaml"

module Zer0ImageGenerator
  # A parsed content file. `categories` is the already-joined "a, b" string the
  # prompt layer wants, not a list — the Python dataclass shipped it that way and
  # callers depend on it.
  ContentFile = Struct.new(:path, :title, :description, :categories, :preview,
                           :author, :content, :front_matter)

  # Front-matter layer: read a Jekyll content file, and — the dangerous half —
  # write one key back into a file a human owns without disturbing a byte of
  # anything else.
  #
  # Ported from lib/zer0_image_generator/preview_generator.py (the oracle).
  # Several helpers below reimplement CPython string semantics rather than using
  # the nearest Ruby method, because the nearest Ruby method is subtly different
  # and this layer rewrites user source files.
  module Content
    # Front matter opens on the very first line; trailing spaces/tabs are
    # tolerated because editors leave them and Jekyll accepts them.
    FM_OPEN = /\A---[ \t]*\r?\n/.freeze
    FM_CLOSE = /^---[ \t]*\r?$/.freeze

    # CPython's `str.isspace()` set — verified identical to what `re`'s `\s`
    # matches for str patterns, and to what `str.strip()` removes. Ruby's `\s`
    # is ASCII-only and `[[:space:]]` follows Unicode White_Space (which excludes
    # U+001C..U+001F), so neither is a drop-in substitute. Built from codepoints
    # so the source stays ASCII; none of these characters are class-special.
    PY_SPACE_CODEPOINTS = [
      0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x85, 0xA0,
      0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007,
      0x2008, 0x2009, 0x200A, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000
    ].freeze
    PY_SPACE_CLASS = PY_SPACE_CODEPOINTS.map { |cp| cp.chr(Encoding::UTF_8) }.join.freeze
    PY_SPACE = /[#{PY_SPACE_CLASS}]/.freeze

    # `str.splitlines(keepends=True)` breaks on far more than `\n`: VT, FF, the
    # C0 separators (but NOT U+001F, which isspace() counts yet splitlines does
    # not), NEL, and the Unicode line/paragraph separators all end a line.
    # `String#lines` only knows `\n`, which would merge two front-matter lines
    # into one and put the new key in the wrong place.
    PY_LINE_BREAK_CODEPOINTS = [
      0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029
    ].freeze
    PY_LINE_BREAK = PY_LINE_BREAK_CODEPOINTS.map { |cp| cp.chr(Encoding::UTF_8) }.join.freeze
    PY_SPLITLINES = /[^#{PY_LINE_BREAK}]*(?:\r\n|[#{PY_LINE_BREAK}])?/.freeze

    # Offsets of the raw front-matter body between the opening and closing `---`
    # fences: [fm_start, fm_end, fm_text], or nil when the file has none.
    # Offsets are character indices, as in the oracle.
    def self.split_front_matter(text)
      open_match = FM_OPEN.match(text)
      return nil unless open_match

      fm_start = open_match.end(0)
      close = FM_CLOSE.match(text, fm_start)
      return nil unless close

      [fm_start, close.begin(0), text[fm_start...close.begin(0)]]
    end

    def self.parse_front_matter(path, fm_key = "preview")
      text = read_text(path)
      return nil unless text

      parts = split_front_matter(text)
      unless parts
        log(:debug, "No front matter found in: #{path}")
        return nil
      end
      fm_end = parts[1]

      begin
        data = YAML.safe_load(parts[2], permitted_classes: [Date, Time], aliases: true)
      rescue Psych::Exception => e
        log(:warn, "Failed to parse YAML in #{path}: #{e.message}")
        return nil
      end
      return nil unless data.is_a?(Hash)

      categories = data.fetch("categories", [])
      categories = [categories] if categories.is_a?(String)
      categories = [] unless categories.is_a?(Array)

      body_start = text.index("\n", fm_end)
      body = body_start ? text[(body_start + 1)..] : ""

      preview = data[fm_key]
      ContentFile.new(
        path.to_s,
        py_str(truthy?(data["title"]) ? data["title"] : ""),
        py_str(truthy?(data["description"]) ? data["description"] : ""),
        categories.map { |c| py_str(c) }.join(", "),
        preview.is_a?(String) ? preview : nil,
        data["author"],
        body,
        data
      )
    end

    # Set `<key>:` inside the front-matter block ONLY (first match).
    #
    # Replaces an existing `<key>:` line, else inserts after the first
    # `description:` line, else after the first `title:` line. Everything outside
    # the front-matter block is preserved byte-for-byte (the former sed/regex
    # implementations operated file-wide and could corrupt body lines that start
    # with the key). Writes a transient `.bak`, replaces atomically, removes the
    # `.bak` on success — CI asserts no `.bak` survives a successful run.
    def self.update_front_matter(path, preview_path, dry_run: false, key: "preview")
      if dry_run
        log(:info, "[DRY RUN] Would update #{key} in #{path} to: #{preview_path}")
        return true
      end

      # Bytes round-trip: the newline-translating read used by parse_front_matter
      # would silently rewrite a CRLF file as LF.
      text = read_text(path, universal_newlines: false)
      return false unless text

      parts = split_front_matter(text)
      unless parts
        log(:warn, "No front matter block in #{path}; not updating")
        return false
      end
      fm_start, fm_end, fm_text = parts

      eol = fm_text.include?("\r\n") ? "\r\n" : "\n"
      lines = splitlines(fm_text)

      preview_idx = find_key(lines, "#{key}:")
      if preview_idx != -1
        line = lines[preview_idx]
        line_eol = if line.end_with?("\r\n") then "\r\n"
                   elsif line.end_with?("\n") then "\n"
                   else ""
                   end
        lines[preview_idx] = "#{key}: #{preview_path}#{line_eol}"
      else
        anchor = find_key(lines, "description:")
        anchor = find_key(lines, "title:") if anchor == -1
        if anchor == -1
          log(:warn, "No #{key}:/description:/title: anchor in #{path} front matter")
          return false
        end
        insert_at = end_of_block(lines, anchor)
        if !lines[anchor].end_with?("\n") && insert_at == anchor + 1
          lines[anchor] += eol # anchor was the final unterminated line
        end
        lines.insert(insert_at, "#{key}: #{preview_path}#{eol}")
      end

      new_text = text[0, fm_start] + lines.join + text[fm_end..]
      write_atomically(path, new_text) or return false

      log(:success, "Updated front matter with #{key}: #{preview_path}")
      true
    end

    # Slug identical to the historical Bash chain (trim before the 50-cut).
    def self.generate_filename(title)
      slug = title.downcase.gsub(/[^a-z0-9]/, "-")
      slug = slug.gsub(/-+/, "-").sub(/\A-+/, "").sub(/-+\z/, "")
      slug[0, 50]
    end

    # Front-matter path -> site-absolute path (/assets/... form) for existence
    # checks. External URLs pass through unchanged.
    def self.normalize_preview_path(preview, settings)
      return preview if preview.nil? || preview.empty?
      return preview if preview.start_with?("http://", "https://")

      # Substring (not prefix) check is deliberate: it mirrors the Liquid
      # `contains` logic in components/preview-image.html and content/seo.html —
      # the engine's idea of "already prefixed" must match what the site renders.
      if settings.auto_prefix && !preview.include?(settings.assets_prefix)
        return "#{settings.assets_prefix}#{preview}"
      end

      preview
    end

    def self.check_preview_exists(preview, settings, root)
      return false if preview.nil? || preview.empty?
      # External URLs count as present (matches the Liquid component + SEO tags;
      # the old Bash engine would silently regenerate over them).
      return true if preview.start_with?("http://", "https://")

      normalized = normalize_preview_path(preview, settings) || ""
      clean = normalized.sub(%r{\A/+}, "")
      [join_path(root, clean), join_path(root, "assets", clean)].any? { |p| File.file?(p) }
    end

    # The value written to front matter — WITHOUT the assets prefix (Liquid adds
    # it): assets/images/previews -> /images/previews/<filename>.
    def self.preview_front_matter_path(settings, filename)
      out = strip_slashes(settings.output_dir)
      prefix = strip_slashes(settings.assets_prefix)
      if !prefix.empty? && (out == prefix || out.start_with?("#{prefix}/"))
        out = strip_slashes(out[prefix.length..])
      end
      out.empty? ? "/#{filename}" : "/#{out}/#{filename}"
    end

    # Locate an existing preview image on disk (for --enhance).
    def self.find_preview_image(preview, settings, root)
      return nil if preview.nil? || preview.empty?
      return nil if preview.start_with?("http://", "https://")

      clean = preview.sub(%r{\A/+}, "")
      candidates = [
        join_path(root, clean),
        join_path(root, "assets", clean),
        join_path(root, settings.output_dir, File.basename(clean)),
      ]
      candidates.find { |candidate| File.file?(candidate) }
    end

    # pathlib's `/` operator, which is what the oracle joins with: empty and "."
    # components are dropped, runs of slashes collapse, and an absolute
    # component resets the path. `File.join` does none of that, and
    # find_preview_image hands the joined string back to its caller.
    def self.join_path(*parts)
      absolute = false
      segments = []
      parts.each do |part|
        str = part.to_s
        if str.start_with?("/")
          absolute = true
          segments.clear
        end
        segments.concat(str.split("/").reject { |seg| seg.empty? || seg == "." })
      end
      joined = segments.join("/")
      return "/#{joined}" if absolute

      joined.empty? ? "." : joined
    end

    # --- CPython string semantics -------------------------------------------

    # `str.splitlines(keepends=True)`.
    def self.splitlines(text)
      parts = text.scan(PY_SPLITLINES)
      parts.pop if parts.last == "" # the scan always closes with an empty match
      parts
    end

    # `re.sub(r"\s+", " ", text).strip()` — the excerpt normalizer shared with
    # the prompt layer. Exposed because `String#strip` also eats NUL, which
    # Python's does not, and because both `\s+` and the final strip must use the
    # CPython whitespace set.
    def self.collapse_whitespace(text)
      collapsed = text.gsub(/[#{PY_SPACE_CLASS}]+/, " ")
      # After collapsing, every whitespace run is a single ASCII space, so
      # trimming leading/trailing spaces reproduces str.strip() exactly.
      collapsed.sub(/\A +/, "").sub(/ +\z/, "")
    end

    # Python truthiness, which is what `data.get("title") or ""` tests.
    def self.truthy?(value)
      case value
      when nil, false then false
      when String, Array, Hash then !value.empty?
      when Numeric then !value.zero?
      else true
      end
    end

    # Python's `str()` over the scalar shapes a YAML front-matter value can take.
    # Containers and floats fall through to Ruby's #to_s, which formats
    # differently from CPython's repr() — see DEVIATIONS in the port notes.
    def self.py_str(value)
      case value
      when String then value
      when true then "True"
      when false then "False"
      when nil then "None"
      else value.to_s
      end
    end

    # --- internals ------------------------------------------------------------

    def self.strip_slashes(text)
      text.sub(%r{\A/+}, "").sub(%r{/+\z}, "")
    end
    private_class_method :strip_slashes

    def self.find_key(lines, prefix)
      lines.index { |line| line.start_with?(prefix) } || -1
    end
    private_class_method :find_key

    # Index just past a key line and any indented continuation lines
    # (folded/literal scalars, nested maps).
    def self.end_of_block(lines, idx)
      j = idx + 1
      while j < lines.length && (lines[j].start_with?(" ", "\t") || blank?(lines[j]))
        # A blank line only continues the block if an indented line follows.
        break if blank?(lines[j]) &&
                 !(j + 1 < lines.length && lines[j + 1].start_with?(" ", "\t"))

        j += 1
      end
      j
    end
    private_class_method :end_of_block

    # `line.strip() == ""`: True when the line is empty or all-whitespace.
    def self.blank?(line)
      line.match?(/\A[#{PY_SPACE_CLASS}]*\z/)
    end
    private_class_method :blank?

    # `Path.read_text(encoding="utf-8")` (universal newlines) or `read_bytes()
    # .decode("utf-8")`. Both raise on unreadable/undecodable input; the oracle
    # warns and returns None for either, so this returns nil.
    def self.read_text(path, universal_newlines: true)
      raw = begin
        File.binread(path.to_s)
      rescue SystemCallError, IOError => e
        log(:warn, "Failed to read #{path}: #{e.message}")
        return nil
      end

      text = raw.force_encoding(Encoding::UTF_8)
      unless text.valid_encoding?
        # Python raises UnicodeDecodeError here and the oracle handles it
        # identically to an OSError.
        log(:warn, "Failed to read #{path}: invalid UTF-8")
        return nil
      end

      universal_newlines ? text.gsub(/\r\n?/, "\n") : text
    end
    private_class_method :read_text

    # `.bak` then atomic rename. On failure the `.bak` is deliberately left
    # behind (the oracle only unlinks the temp file) — it is the user's only
    # copy if the rename tore.
    def self.write_atomically(path, new_text)
      target = path.to_s
      backup = "#{target}.bak"
      tmp = "#{target}.tmp~"
      begin
        FileUtils.cp(target, backup, preserve: true)
        File.binwrite(tmp, new_text)
        File.rename(tmp, target)
        File.unlink(backup) if File.exist?(backup)
      rescue SystemCallError, IOError => e
        log(:warn, "Failed to update front matter in #{path}: #{e.message}")
        File.unlink(tmp) if File.exist?(tmp)
        return false
      end
      true
    end
    private_class_method :write_atomically

    # The engine's shared logger lives in the `Zer0ImageGenerator::Logging`
    # slice (info/warn/success/debug/step class methods, --verbose-gated debug).
    # Route through it when present. Until it is loaded, warnings still have to
    # reach a human — a silently-skipped front-matter write is the worst failure
    # mode this file has — so fall back to stderr. `:debug` is dropped by the
    # fallback because the shared logger gates it on --verbose (off by default).
    def self.log(level, message)
      logger = Zer0ImageGenerator.const_defined?(:Logging, false) ? Zer0ImageGenerator::Logging : nil
      if logger.respond_to?(level)
        logger.public_send(level, message)
      elsif level != :debug
        $stderr.puts("[#{level.to_s.upcase}] #{message}")
      end
    end
    private_class_method :log
  end
end
