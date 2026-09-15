# frozen_string_literal: true

require "date"
require "digest"
require "json"
require "pathname"
require "psych"
require "yaml"
require_relative "cms/catalog"

module Zer0Cms
  # `zer0-cms doctor PATH` — is a content repository aligned with the zer0
  # stack (one theme, one image engine, one CMS)? The checks are exactly the
  # table in the zer0 stack RFC §4:
  #
  # | check        | error when                                            | warning when |
  # |--------------|-------------------------------------------------------|--------------|
  # | theme        | `_config.yml` unreadable, or not on zer0-mistakes      | no `.theme-overrides.yml` |
  # | image-engine | a vendored preview-generator fork exists              | no `preview_images:`; a Gemfile without the gem |
  # | cms          | `zer0.json` invalid JSON(C), or a content folder missing | no `zer0.json`; no `$schema` |
  # | fleet        | `fleet.manifest.yml` present but not strict YAML      | — |
  # | content      | a catalogued file whose front matter does not parse   | a key the theme's front-matter schema requires is missing |
  #
  # Findings use lifehacker.dev's findings.jsonl shape (`check_id, severity,
  # file, line, rule, evidence, fingerprint`), so the same triage tooling can
  # read them. Content warnings are report-only: content repos are on a
  # content stand-down, and a missing key is a backlog item, not a gate.
  module Doctor
    VENDORED_SCHEMA = File.expand_path("data/frontmatter_schema.yml", __dir__)
    SITE_SCHEMA = ".github/config/frontmatter_schema.yml"
    REMOTE_THEME = %r{\A(?:https?://github\.com/)?bamr87/zer0-mistakes(?:\.git)?(?:@\S+)?\z}i
    THEME_GEM = "jekyll-theme-zer0"
    IMAGE_GEM = "zer0-image-generator"
    PREVIEW_FORKS = %w[
      _plugins/preview_image_generator.rb
      _plugins/preview_generator.rb
      scripts/lib/preview_generator.py
    ].freeze
    CHECKS = %w[theme image-engine cms fleet distribution content].freeze
    # The per-site LinkedIn publisher the distribution lane replaced.
    VENDORED_LINKEDIN = %w[scripts/features/linkedin/posts.py scripts/features/linkedin/mcp_server.py].freeze

    Report = Struct.new(:root, :schema, :findings, keyword_init: true) do
      def errors = findings.count { |f| f["severity"] == "error" }
      def warnings = findings.count { |f| f["severity"] == "warning" }
      def ok? = errors.zero?
    end

    module_function

    def run(root, schema: nil)
      root = Pathname.new(File.expand_path(root.to_s))
      findings = []
      config = check_theme(root, findings)
      check_image_engine(root, config, findings)
      check_cms(root, findings)
      check_fleet(root, findings)
      check_distribution(root, findings)
      schema_path = check_content(root, schema, findings)
      Report.new(root: root, schema: schema_path, findings: findings)
    end

    # ---- distribution --------------------------------------------------------

    # Only a site that configures `distribution.linkedin` is checked beyond the
    # vendored-publisher warning. The environment is ignored on purpose: the
    # doctor reports what the repository says, the same on every machine.
    def check_distribution(root, findings)
      vendored = VENDORED_LINKEDIN.find { |rel| root.join(rel).file? }
      if vendored
        findings << finding("distribution", "warning", "vendored-linkedin-publisher",
                            "a per-site LinkedIn publisher; zer0-cms linkedin replaces it", file: vendored)
      end
      return unless root.join("zer0.json").file?

      require_relative "distribution"
      config = Distribution::Config.load(root, env: {})
      return unless config.configured?

      config.errors.each { |message| findings << finding("distribution", "error", "distribution-config-invalid", message, file: "zer0.json") }
      config.warnings.each { |message| findings << finding("distribution", "warning", "distribution-config", message, file: "zer0.json") }
      return if Distribution::Ledger.new(config.path(config.ledger)).readable?

      findings << finding("distribution", "error", "distribution-ledger-unreadable", "#{config.ledger} is not valid JSON", file: config.ledger)
    rescue Distribution::ConfigError, Cms::UnsafePath => e
      findings << finding("distribution", "error", "distribution-config-invalid", e.message, file: "zer0.json")
    end

    # The finding shape of lifehacker.dev scripts/ci/_lib.rb LH.finding, with
    # the fingerprint stamped: sha1("check_id|rule|file|evidence"), 12 hex.
    def finding(check_id, severity, rule, evidence, file: "", line: nil)
      {
        "check_id" => check_id,
        "severity" => severity,
        "file" => file.to_s,
        "line" => line,
        "rule" => rule,
        "evidence" => evidence.to_s,
        "fingerprint" => Digest::SHA1.hexdigest("#{check_id}|#{rule}|#{file}|#{evidence}")[0, 12]
      }
    end

    # ---- theme -------------------------------------------------------------

    def check_theme(root, findings)
      config = nil
      begin
        loaded = YAML.safe_load(root.join("_config.yml").read, permitted_classes: [Date, Time, Symbol], aliases: true)
        if loaded.is_a?(Hash)
          config = loaded
        else
          findings << finding("theme", "error", "config-unreadable", "_config.yml is not a mapping", file: "_config.yml")
        end
      rescue SystemCallError => e
        findings << finding("theme", "error", "config-unreadable", "cannot read _config.yml: #{e.class.name.split("::").last}", file: "_config.yml")
      rescue Psych::SyntaxError => e
        findings << finding("theme", "error", "config-unreadable", "_config.yml does not parse: #{e.problem}", file: "_config.yml", line: e.line)
      rescue Psych::Exception => e
        findings << finding("theme", "error", "config-unreadable", "_config.yml does not load: #{e.message}", file: "_config.yml")
      end

      if config
        remote = config["remote_theme"].to_s.strip
        theme = config["theme"].to_s.strip
        unless REMOTE_THEME.match?(remote) || theme == THEME_GEM
          evidence = if remote.empty? && theme.empty?
                       "no remote_theme: bamr87/zer0-mistakes or theme: #{THEME_GEM}"
                     else
                       "remote_theme: #{remote.inspect}, theme: #{theme.inspect}"
                     end
          findings << finding("theme", "error", "theme-not-zer0", evidence, file: "_config.yml")
        end
      end
      unless root.join(".theme-overrides.yml").file?
        findings << finding("theme", "warning", "no-theme-overrides", "no .theme-overrides.yml", file: ".theme-overrides.yml")
      end
      config
    end

    # ---- image engine ------------------------------------------------------

    # A candidate path is a fork only when it reads the image engine's own
    # `preview_images` config. The name alone is not enough: it-journey's
    # `_plugins/preview_generator.rb` is a Front Matter CMS `/preview/` page
    # mirror that shares the filename and nothing else.
    def preview_fork?(path)
      path.file? && path.read(mode: "rb").include?("preview_images")
    rescue SystemCallError
      false
    end

    def check_image_engine(root, config, findings)
      PREVIEW_FORKS.each do |rel|
        next unless preview_fork?(root.join(rel))

        findings << finding("image-engine", "error", "vendored-preview-fork",
                            "a vendored preview generator; use the #{IMAGE_GEM} gem", file: rel)
      end
      if config && !config["preview_images"].is_a?(Hash)
        findings << finding("image-engine", "warning", "no-preview-images-config", "no preview_images: block", file: "_config.yml")
      end
      gemfile = root.join("Gemfile")
      return unless gemfile.file?
      return if gemfile.read.match?(/^\s*gem\s+["']#{Regexp.escape(IMAGE_GEM)}["']/)

      findings << finding("image-engine", "warning", "gemfile-missing-image-generator", "Gemfile does not require #{IMAGE_GEM}", file: "Gemfile")
    end

    # ---- cms -----------------------------------------------------------------

    def check_cms(root, findings)
      file = root.join("zer0.json")
      unless file.file?
        findings << finding("cms", "warning", "no-zer0-json", "no zer0.json", file: "zer0.json")
        return
      end

      begin
        data = Jsonc.parse(file.read)
      rescue JSON::ParserError => e
        findings << finding("cms", "error", "zer0-json-invalid", "zer0.json is not valid JSON(C): #{e.message.lines.first.to_s.strip[0, 160]}", file: "zer0.json")
        return
      end
      unless data.is_a?(Hash)
        findings << finding("cms", "error", "zer0-json-invalid", "zer0.json is not an object", file: "zer0.json")
        return
      end

      schema = data["$schema"]
      unless schema.is_a?(String) && !schema.strip.empty?
        findings << finding("cms", "warning", "zer0-json-no-schema", "zer0.json has no $schema", file: "zer0.json")
      end
      folders = data["contentFolders"].is_a?(Array) ? data["contentFolders"] : []
      folders.each_with_index do |folder, index|
        path = folder.is_a?(Hash) ? folder["path"] : nil
        next unless path.is_a?(String)

        dir = content_folder(root, path)
        next if dir.directory?

        findings << finding("cms", "error", "content-folder-missing",
                            "contentFolders[#{index}].path #{path} does not exist", file: "zer0.json")
      end
    end

    # `[[workspace]]` is the site root; a `*` or `{{…}}` placeholder cuts the
    # path back to the last directory that is literal.
    def content_folder(root, path)
      text = path.gsub("[[workspace]]", root.to_s)
      wild = text.index(/\*|\{\{/)
      text = text[0, wild].sub(%r{[^/]*\z}, "") if wild
      Pathname.new(File.expand_path(text.empty? ? "." : text, root.to_s))
    end

    # ---- fleet -----------------------------------------------------------------

    # Strict: Psych loads it with no aliases and no custom classes, the top
    # level is a mapping, and no mapping repeats a key.
    def check_fleet(root, findings)
      file = root.join("fleet.manifest.yml")
      return unless file.file?

      text = file.read
      rel = "fleet.manifest.yml"
      data = Psych.safe_load(text, permitted_classes: [], aliases: false)
      unless data.is_a?(Hash)
        findings << finding("fleet", "error", "fleet-manifest-invalid", "top level is not a mapping", file: rel)
        return
      end
      duplicate = first_duplicate_key(Psych.parse(text))
      return unless duplicate

      findings << finding("fleet", "error", "fleet-manifest-invalid", "duplicate key #{duplicate[0].inspect}", file: rel, line: duplicate[1])
    rescue Psych::SyntaxError => e
      findings << finding("fleet", "error", "fleet-manifest-invalid", "not valid YAML: #{e.problem} (column #{e.column})", file: rel, line: e.line)
    rescue Psych::Exception => e
      findings << finding("fleet", "error", "fleet-manifest-invalid", "not strict YAML: #{e.message}", file: rel)
    end

    def first_duplicate_key(node)
      return nil unless node

      if node.is_a?(Psych::Nodes::Mapping)
        seen = {}
        node.children.each_slice(2) do |key, _|
          next unless key.is_a?(Psych::Nodes::Scalar)
          return [key.value, key.start_line + 1] if seen[key.value]

          seen[key.value] = true
        end
      end
      Array(node.children).each do |child|
        found = first_duplicate_key(child)
        return found if found
      end
      nil
    end

    # ---- content -----------------------------------------------------------------

    def check_content(root, schema_option, findings)
      schema_path = schema_file(root, schema_option)
      schema = load_schema(schema_path, root, findings)
      begin
        result = Cms::Catalog.scan(root)
      rescue Cms::UnsafePath => e
        findings << finding("content", "error", "unsafe-path", e.message, file: "_config.yml")
        return schema_path
      end
      result.entries.each do |entry|
        if entry.error.to_s.start_with?("front matter:")
          findings << finding("content", "error", "front-matter-invalid", entry.error, file: entry.relative, line: error_line(entry))
          next
        end
        next unless schema

        required_keys(schema, entry).each do |key|
          value = entry.data[key]
          next unless value.nil? || (value.respond_to?(:empty?) && value.empty?)

          findings << finding("content", "warning", "missing-key:#{key}",
                              "#{entry.collection} requires #{key}", file: entry.relative)
        end
      end
      schema_path
    end

    def schema_file(root, option)
      return File.expand_path(option) if option

      site = root.join(SITE_SCHEMA)
      site.file? ? site.to_s : VENDORED_SCHEMA
    end

    def load_schema(path, root, findings)
      data = YAML.safe_load(File.read(path), aliases: true)
      return data if data.is_a?(Hash)

      findings << finding("content", "error", "schema-unreadable", "#{display(path, root)} is not a mapping")
      nil
    rescue SystemCallError, Psych::Exception => e
      findings << finding("content", "error", "schema-unreadable", "#{display(path, root)}: #{e.message.lines.first.to_s.strip}")
      nil
    end

    def display(path, root)
      path.to_s.delete_prefix("#{root}/")
    end

    # The schema's global required fields, plus the collection's own. The
    # catalog calls every loose page "pages"; the schema's `pages` collection
    # means only the files its path_pattern matches.
    def required_keys(schema, entry)
      global = Array(schema.dig("global", "required_fields"))
      collections = schema["collections"].is_a?(Hash) ? schema["collections"] : {}
      spec = collections[entry.collection]
      spec = nil unless spec.is_a?(Hash)
      if spec && entry.kind == :page && spec["path_pattern"].is_a?(String)
        spec = nil unless File.fnmatch?(spec["path_pattern"], entry.relative, File::FNM_PATHNAME | File::FNM_EXTGLOB)
      end
      (global + Array(spec && spec["required"])).map(&:to_s).uniq
    end

    def error_line(entry)
      Cms::FrontMatter.parse(File.binread(entry.path).force_encoding("UTF-8").scrub, strict: true)
      nil
    rescue Psych::SyntaxError => e
      e.line
    rescue StandardError
      nil
    end

    # ---- output ------------------------------------------------------------------

    def to_jsonl(report)
      report.findings.map { |f| JSON.generate(f) }.join("\n")
    end

    def to_text(report)
      out = ["zer0 doctor: #{report.root}", "  front-matter schema: #{display(report.schema, report.root)}"]
      CHECKS.each do |check|
        mine = report.findings.select { |f| f["check_id"] == check }
        errors = mine.count { |f| f["severity"] == "error" }
        warnings = mine.count { |f| f["severity"] == "warning" }
        status = errors.zero? && warnings.zero? ? "ok" : "#{errors} error(s), #{warnings} warning(s)"
        out << "  #{check.ljust(13)} #{status}"
        mine.each do |f|
          next if check == "content" && f["severity"] == "warning"

          location = f["file"].empty? ? "" : " #{f["file"]}#{f["line"] ? ":#{f["line"]}" : ""}"
          out << "    #{f["severity"] == "error" ? "ERROR" : "warn "} #{f["rule"]}#{location} — #{f["evidence"]}"
        end
        by_rule = mine.select { |f| f["severity"] == "warning" && check == "content" }.group_by { |f| f["rule"] }
        by_rule.sort_by { |rule, list| [-list.size, rule] }.each do |rule, list|
          out << "    warn  #{rule.ljust(28)} #{list.size} file(s)"
        end
      end
      out << "result: #{report.errors} error(s), #{report.warnings} warning(s)"
      out.join("\n")
    end

    # JSON with comments and trailing commas (the zer0.json dialect), read
    # with the stdlib JSON parser after both are stripped outside strings.
    module Jsonc
      module_function

      def parse(text)
        JSON.parse(strip_trailing_commas(strip_comments(text.to_s.delete_prefix("﻿"))))
      end

      def strip_comments(text)
        chars = text.chars
        out = +""
        i = 0
        in_string = false
        while i < chars.size
          char = chars[i]
          if in_string
            out << char
            if char == "\\"
              out << chars[i + 1].to_s
              i += 1
            elsif char == '"'
              in_string = false
            end
          elsif char == '"'
            in_string = true
            out << char
          elsif char == "/" && chars[i + 1] == "/"
            i += 1 while i < chars.size && chars[i] != "\n"
            next
          elsif char == "/" && chars[i + 1] == "*"
            close = i + 2
            close += 1 while close < chars.size && !(chars[close] == "*" && chars[close + 1] == "/")
            raise JSON::ParserError, "unterminated /* comment" if close >= chars.size

            out << chars[i..(close + 1)].join.gsub(/[^\n]/, " ")
            i = close + 2
            next
          else
            out << char
          end
          i += 1
        end
        out
      end

      def strip_trailing_commas(text)
        chars = text.chars
        out = +""
        in_string = false
        i = 0
        while i < chars.size
          char = chars[i]
          if in_string
            out << char
            if char == "\\"
              out << chars[i + 1].to_s
              i += 1
            elsif char == '"'
              in_string = false
            end
          elsif char == '"'
            in_string = true
            out << char
          elsif char == ","
            j = i + 1
            j += 1 while j < chars.size && chars[j].match?(/\s/)
            out << char unless ["]", "}"].include?(chars[j])
          else
            out << char
          end
          i += 1
        end
        out
      end
    end
  end
end
