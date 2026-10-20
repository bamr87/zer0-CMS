# frozen_string_literal: true

# Port of the settings layer of lib/zer0_image_generator/preview_generator.py:
# the Settings value object, resolve_settings' CLI>env>config>DEFAULTS
# precedence chain, and the per-file override machinery (author + collection
# style blocks). The Python file stays the oracle;
# test/ruby/test_settings.rb differential-tests resolve_settings against it.

require_relative "config"
require_relative "svg/local_renderer" # BANNER_PALETTES, for palette names

module Zer0ImageGenerator
  # Fully-resolved run settings (before per-file author overrides).
  #
  # Ports the Python `@dataclass Settings`. Field names and defaults match the
  # oracle one-for-one so `to_h` diffs cleanly against `dataclasses.asdict`.
  class Settings
    ATTRIBUTES = %i[
      provider model size quality style style_modifiers output_dir
      assets_prefix auto_prefix enabled collections collections_dir
      collection_styles front_matter_key authors_file prompt_engine
      review_engine claude_model claude_effort dry_run verbose force
      list_only parallel batch file collection enhance enhance_prompt
      enhance_model enhance_quality enhance_fidelity enhance_format
      rasterizer provider_explicit
      style_card palette claude_plan claude_rounds claude_min_score
      claude_require_thumbnail svg_text svg_max_kb look_rasterizer
      claude_budget_usd telemetry changed exclude_re
    ].freeze

    attr_accessor(*ATTRIBUTES)

    def initialize(**overrides)
      @provider = DEFAULTS["provider"]
      @model = DEFAULTS["model"]
      @size = DEFAULTS["size"]
      @quality = DEFAULTS["quality"]
      @style = DEFAULTS["style"]
      @style_modifiers = DEFAULTS["style_modifiers"]
      @output_dir = DEFAULTS["output_dir"]
      @assets_prefix = DEFAULTS["assets_prefix"]
      @auto_prefix = DEFAULTS["auto_prefix"]
      @enabled = true
      # Fresh copies so two Settings never share the same mutable default
      # (mirrors the dataclass field(default_factory=...)).
      @collections = DEFAULTS["collections"].dup
      @collections_dir = DEFAULTS["collections_dir"]
      @collection_styles = {}
      @front_matter_key = DEFAULTS["front_matter_key"]
      @authors_file = DEFAULTS["authors_file"]
      @prompt_engine = DEFAULTS["prompt_engine"]
      @review_engine = DEFAULTS["review_engine"]
      @claude_model = DEFAULTS["claude_model"]
      @claude_effort = DEFAULTS["claude_effort"]

      @dry_run = false
      @verbose = false
      @force = false
      @list_only = false
      @parallel = 4
      @batch = 0

      @file = ""
      @collection = ""

      @enhance = false
      @enhance_prompt = ""
      @enhance_model = ENHANCE_DEFAULTS["model"]
      @enhance_quality = ENHANCE_DEFAULTS["quality"]
      @enhance_fidelity = ENHANCE_DEFAULTS["fidelity"]
      @enhance_format = ENHANCE_DEFAULTS["format"]

      @rasterizer = "auto"
      @provider_explicit = false

      # The `claude` provider's illustration loop (see DEFAULTS).
      @style_card = DEFAULTS["style_card"]
      @palette = []
      @claude_plan = DEFAULTS["claude_plan"]
      @claude_rounds = DEFAULTS["claude_rounds"]
      @claude_min_score = DEFAULTS["claude_min_score"].to_f
      @claude_require_thumbnail = DEFAULTS["claude_require_thumbnail"]
      @svg_text = DEFAULTS["svg_text"]
      @svg_max_kb = DEFAULTS["svg_max_kb"].to_f
      @look_rasterizer = DEFAULTS["look_rasterizer"]
      @claude_budget_usd = DEFAULTS["claude_budget_usd"].to_f
      @telemetry = ""
      @changed = false
      @exclude_re = ""

      overrides.each { |key, value| public_send("#{key}=", value) }
    end

    def to_h
      ATTRIBUTES.each_with_object({}) { |attr, acc| acc[attr] = public_send(attr) }
    end

    # Port of dataclasses.replace(settings, **changes): a copy with `changes`
    # applied. Accepts string or symbol keys (OVERRIDE_KEYS are strings).
    def dup_with(changes)
      copy = dup
      copy.instance_variable_set(:@collections, @collections.dup)
      copy.instance_variable_set(:@collection_styles, @collection_styles.dup)
      copy.instance_variable_set(:@palette, @palette.dup)
      changes.each { |key, value| copy.public_send("#{key}=", value) }
      copy
    end

    def ==(other)
      other.is_a?(Settings) && to_h == other.to_h
    end
  end

  # Mirrors the argparse.Namespace resolve_settings consumes. A CLI builds one
  # from parsed flags; a Rails controller builds one from request params. Field
  # names and defaults match build_arg_parser's `dest=` / `default=`.
  #
  # Build with a Hash (string or symbol keys); `Args.build` applies argparse
  # defaults for anything omitted and reproduces parse_args' post-processing
  # (the historical rule that --enhance-prompt / -fidelity / -format imply
  # --enhance) so a Rails caller behaves identically to the CLI.
  class Args
    DEFAULTS = {
      dry_run: false, verbose: false, file: nil, collection: nil,
      provider: nil, model: nil, output_dir: nil, force: false,
      list_missing: false, parallel: nil, enhance: false,
      enhance_prompt: nil, enhance_model: nil, enhance_quality: nil,
      enhance_fidelity: nil, enhance_format: nil, prompt_engine: nil,
      review: nil, rasterizer: nil, style: nil, assets_prefix: nil,
      no_auto_prefix: false, collections_dir: nil, front_matter_key: nil,
      authors_file: nil, batch: 0, log_file: nil, rate_limit: nil,
      # illustration loop
      style_card: nil, palette: nil, claude_plan: nil, claude_rounds: nil,
      claude_min_score: nil, claude_require_thumbnail: nil, svg_text: nil,
      svg_max_kb: nil, look_rasterizer: nil, claude_budget_usd: nil,
      telemetry: nil, changed: false, exclude_re: nil, inspect: nil, critic: false,
      shape: nil
    }.freeze

    attr_accessor(*DEFAULTS.keys)

    def self.build(source = {})
      return source if source.is_a?(Args)

      normalized = {}
      (source.respond_to?(:to_h) ? source.to_h : source).each do |key, value|
        normalized[key.to_sym] = value
      end
      new(normalized).tap(&:apply_enhance_implication!)
    end

    def initialize(overrides = {})
      DEFAULTS.each { |key, value| instance_variable_set("@#{key}", value) }
      overrides.each do |key, value|
        sym = key.to_sym
        # Unknown keys would silently vanish; surface them instead of masking a
        # caller typo (e.g. :front_matter vs :front_matter_key).
        raise ArgumentError, "unknown Args field: #{key}" unless DEFAULTS.key?(sym)

        instance_variable_set("@#{sym}", value)
      end
    end

    # parse_args post-processing: these three flags imply --enhance, but
    # --enhance-model deliberately does not (historical behavior).
    def apply_enhance_implication!
      @enhance = true if @enhance_prompt || @enhance_fidelity || @enhance_format
      self
    end
  end

  module_function

  # Truthy spellings for booleans that arrive as strings (env vars, CLI values,
  # quoted YAML). Port of the oracle's _TRUE_WORDS.
  TRUE_WORDS = %w[1 true yes on].freeze

  # Port of _setting_bool: real booleans pass through, numbers are != 0, and
  # anything else is truthy only when it spells one of TRUE_WORDS.
  def _setting_bool(value)
    return value if value == true || value == false
    return value != 0 if value.is_a?(Numeric)

    TRUE_WORDS.include?(python_str(value).strip.downcase)
  end

  # Port of _setting_number: float(value), falling back to `default` on
  # anything float() rejects. Booleans are rejected explicitly in the oracle.
  def _setting_number(value, default)
    return default if value == true || value == false || value.nil?
    return value.to_f if value.is_a?(Numeric)

    Float(value.to_s.strip)
  rescue ArgumentError, TypeError
    default
  end

  HEX_TOKEN = /\A#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\z/.freeze

  # Port of palette_tokens: a YAML list of hex strings, a comma/space separated
  # string of them, or the name of a banner palette → lowercase hex tokens.
  def palette_tokens(value)
    if value.is_a?(String)
      name = value.strip
      palettes = Svg::LocalRenderer::BANNER_PALETTES
      return palettes[name].dup if palettes.key?(name)

      value = name.split(/[\s,]+/).reject(&:empty?)
    end
    return [] unless value.is_a?(Array)

    value.map { |v| python_str(v).strip }.select { |t| t.match?(HEX_TOKEN) }.map(&:downcase)
  end

  # Settings fields an override block may replace per file (see constants.rb's
  # OVERRIDE_KEYS). Keep only recognized keys with non-empty stringified values.
  def _filter_override_block(block)
    return {} unless block.is_a?(Hash)

    result = {}
    block.each do |key, value|
      next unless OVERRIDE_KEYS.include?(key)
      next if value.nil?

      # python_str, not to_s: a boolean override value must stringify as
      # "True"/"False" (CPython str()) to stay byte-identical to the oracle.
      stripped = python_str(value).strip
      result[key] = stripped unless stripped.empty?
    end
    result
  end

  # `preview:` override block for an author key. `author:` may be a list or
  # mapping in some posts — only a plain string key can index authors.yml.
  def author_preview_overrides(authors, author_key)
    return {} unless author_key.is_a?(String) && !author_key.empty?

    author = authors[author_key]
    return {} unless author.is_a?(Hash)

    _filter_override_block(author["preview"])
  end

  # The file's collection, from the nearest `_<name>` ancestor directory
  # (Jekyll's collection layout) — "" for files outside any collection.
  def collection_of(path)
    Pathname.new(path.to_s).expand_path.parent.ascend do |ancestor|
      name = ancestor.basename.to_s
      return name[1..] if name.start_with?("_") && name.length > 1
    end
    ""
  end

  # The file's section — the directory immediately INSIDE its collection
  # (`pages/_posts/hacks/x.md` -> 'hacks') — or "" when the collection holds its
  # files flat. Sites that fold several kinds of writing into one collection
  # carry the editorial distinction here, and it is the strongest single signal
  # for what a banner should look like.
  def section_of(path)
    parts = Pathname.new(path.to_s).expand_path.to_s.split(File::SEPARATOR)
    parts.each_with_index do |name, i|
      next unless name.start_with?("_") && name.length > 1

      # parts[i + 1] is a directory only when something follows it.
      return i + 2 < parts.length ? parts[i + 1] : ""
    end
    ""
  end

  # The page context the local renderer derives its art from.
  def article_art_context(content_file, slug)
    {
      "slug" => slug,
      "section" => (s = section_of(content_file.path)).empty? ? collection_of(content_file.path) : s,
      "title" => content_file.title.to_s,
      "description" => content_file.description.to_s,
      "categories" => content_file.categories.to_s,
      "body" => content_file.content.to_s,
    }
  end

  # `collection_styles:` override block for a collection — same keys as author
  # overrides, so each collection can carry its own visual theme.
  def collection_preview_overrides(collection_styles, collection)
    return {} if collection.nil? || collection.empty? || !collection_styles.is_a?(Hash)

    _filter_override_block(collection_styles[collection])
  end

  # Merge CLI > env > _config.yml `preview_images:` > DEFAULTS into a Settings.
  # `config` is the site's FULL _config.yml Hash — the block is extracted here,
  # and two top-level Jekyll keys are honored as fallbacks: collections_dir and
  # (for `collections: auto`) the collections: map.
  #
  # `args` is an Args (or any Hash/Struct Args.build accepts).
  def resolve_settings(args, config)
    args = Args.build(args)

    site = config["preview_images"]
    site = {} unless site.is_a?(Hash)

    cfg = lambda do |key, default|
      value = site[key]
      value.nil? ? default : value
    end

    # env only wins when the CLI value is nil AND the env value is non-empty.
    pick = lambda do |cli_value, env_name, cfg_key|
      return cli_value unless cli_value.nil?

      env_value = ENV[env_name]
      return env_value if !env_value.nil? && !env_value.empty?

      python_str(cfg.call(cfg_key, DEFAULTS[cfg_key]))
    end

    # pick() without the str(): CLI > non-empty env > config > default, raw.
    layered = lambda do |cli_value, env_name, cfg_key|
      return cli_value unless cli_value.nil?

      env_value = ENV[env_name]
      return env_value if !env_value.nil? && !env_value.empty?

      cfg.call(cfg_key, DEFAULTS[cfg_key])
    end

    # collections_dir: block override > Jekyll's own top-level key > default.
    collections_dir = cfg.call(
      "collections_dir",
      python_first_truthy(config["collections_dir"], DEFAULTS["collections_dir"])
    )
    collections_dir = args.collections_dir unless args.collections_dir.nil?

    collections = cfg.call("collections", DEFAULTS["collections"])
    if collections == "auto" || (collections.is_a?(Array) && collections.include?("auto"))
      # Discover from Jekyll's own collections: map; posts always exists.
      declared = config["collections"]
      names = declared.is_a?(Hash) ? declared.keys : []
      collections = ["posts"] + names.reject { |n| n == "posts" }
    end
    collections = DEFAULTS["collections"].dup unless collections.is_a?(Array) && !collections.empty?

    parallel_env = ENV.fetch("MAX_PARALLEL", "")
    parallel = if !args.parallel.nil?
                 args.parallel
               elsif parallel_env.match?(/\A[0-9]+\z/)
                 Integer(parallel_env, 10)
               else
                 4
               end

    collection_styles = cfg.call("collection_styles", {})
    collection_styles = {} unless collection_styles.is_a?(Hash)

    Settings.new(
      provider: pick.call(args.provider, "AI_PROVIDER", "provider"),
      model: pick.call(args.model, "IMAGE_MODEL", "model"),
      size: pick.call(nil, "IMAGE_SIZE", "size"),
      quality: pick.call(nil, "IMAGE_QUALITY", "quality"),
      style: pick.call(args.style, "IMAGE_STYLE", "style"),
      style_modifiers: pick.call(nil, "IMAGE_STYLE_MODIFIERS", "style_modifiers"),
      output_dir: pick.call(args.output_dir, "OUTPUT_DIR", "output_dir"),
      assets_prefix: (
        args.assets_prefix.nil? ? python_str(cfg.call("assets_prefix", DEFAULTS["assets_prefix"])) : args.assets_prefix
      ),
      auto_prefix: (
        args.no_auto_prefix ? false : python_bool(cfg.call("auto_prefix", DEFAULTS["auto_prefix"]))
      ),
      enabled: python_bool(cfg.call("enabled", true)),
      collections: collections.map { |c| python_str(c) },
      collection_styles: collection_styles,
      collections_dir: python_str(python_first_truthy(collections_dir, "")).strip.gsub(%r{\A/+|/+\z}, ""),
      front_matter_key: python_first_truthy(
        args.front_matter_key,
        python_str(cfg.call("front_matter_key", DEFAULTS["front_matter_key"])).strip,
        DEFAULTS["front_matter_key"]
      ),
      authors_file: (
        if args.authors_file.nil?
          python_str(python_first_truthy(cfg.call("authors_file", DEFAULTS["authors_file"]), ""))
        else
          args.authors_file
        end
      ),
      prompt_engine: pick.call(args.prompt_engine, "PROMPT_ENGINE", "prompt_engine"),
      review_engine: pick.call(args.review, "REVIEW_ENGINE", "review_engine"),
      claude_model: python_str(python_first_truthy(cfg.call("claude_model", ""), "")),
      claude_effort: python_str(python_first_truthy(cfg.call("claude_effort", DEFAULTS["claude_effort"]), "")),
      dry_run: (args.dry_run ? true : _env_flag("DRY_RUN")),
      verbose: (args.verbose ? true : _env_flag("VERBOSE")),
      force: (args.force ? true : _env_flag("FORCE")),
      list_only: (args.list_missing ? true : _env_flag("LIST_ONLY")),
      parallel: parallel,
      batch: python_first_truthy(args.batch, 0),
      # These mirror bare `args.x or default` chains in the oracle (no str()
      # wrapper), so values pass through uncoerced exactly as Python leaves them.
      file: python_first_truthy(args.file, ""),
      collection: python_first_truthy(args.collection, ""),
      enhance: (args.enhance ? true : _env_flag("ENHANCE")),
      enhance_prompt: python_first_truthy(args.enhance_prompt, ""),
      enhance_model: python_first_truthy(args.enhance_model, ENV["ENHANCE_MODEL"], ENHANCE_DEFAULTS["model"]),
      enhance_quality: python_first_truthy(args.enhance_quality, ENV["ENHANCE_QUALITY"], ENHANCE_DEFAULTS["quality"]),
      enhance_fidelity: python_first_truthy(args.enhance_fidelity, ENV["ENHANCE_FIDELITY"], ENHANCE_DEFAULTS["fidelity"]),
      enhance_format: python_first_truthy(args.enhance_format, ENV["ENHANCE_FORMAT"], ENHANCE_DEFAULTS["format"]),
      rasterizer: pick.call(args.rasterizer, "IMAGE_RASTERIZER", "rasterizer"),
      provider_explicit: !args.provider.nil? || python_bool(ENV["AI_PROVIDER"]),
      style_card: python_str(pick.call(args.style_card, "IMAGE_STYLE_CARD", "style_card")).strip,
      palette: palette_tokens(layered.call(args.palette, "IMAGE_PALETTE", "palette")),
      claude_plan: _setting_bool(layered.call(args.claude_plan, "CLAUDE_PLAN", "claude_plan")),
      claude_rounds: [0, _setting_number(
        layered.call(args.claude_rounds, "CLAUDE_ROUNDS", "claude_rounds"),
        DEFAULTS["claude_rounds"].to_f
      ).to_i].max,
      claude_min_score: _setting_number(
        layered.call(args.claude_min_score, "CLAUDE_MIN_SCORE", "claude_min_score"),
        DEFAULTS["claude_min_score"].to_f
      ),
      claude_require_thumbnail: _setting_bool(layered.call(
        args.claude_require_thumbnail, "CLAUDE_REQUIRE_THUMBNAIL", "claude_require_thumbnail"
      )),
      svg_text: python_str(pick.call(args.svg_text, "SVG_TEXT", "svg_text")).strip.downcase,
      svg_max_kb: _setting_number(
        layered.call(args.svg_max_kb, "SVG_MAX_KB", "svg_max_kb"), DEFAULTS["svg_max_kb"].to_f
      ),
      look_rasterizer: pick.call(args.look_rasterizer, "LOOK_RASTERIZER", "look_rasterizer"),
      claude_budget_usd: _setting_number(
        layered.call(args.claude_budget_usd, "CLAUDE_BUDGET_USD", "claude_budget_usd"),
        DEFAULTS["claude_budget_usd"].to_f
      ),
      telemetry: args.telemetry.nil? ? ENV.fetch("PREVIEW_TELEMETRY", "") : args.telemetry,
      changed: python_bool(args.changed),
      exclude_re: args.exclude_re.nil? ? ENV.fetch("PREVIEW_EXCLUDE_RE", "") : args.exclude_re
    )
  end

  # Per-file settings copy with override blocks applied in order — later blocks
  # win (pass collection styles first, author overrides on top). Returns the
  # same object when nothing overrides, matching dataclasses.replace's identity
  # short-circuit in the oracle.
  def apply_preview_overrides(settings, *override_blocks)
    merged = {}
    override_blocks.each { |block| merged.update(block || {}) }
    return settings if merged.empty?

    changes = {}
    OVERRIDE_KEYS.each do |key|
      changes[key] = merged.key?(key) ? merged[key] : settings.public_send(key)
    end
    settings.dup_with(changes)
  end

  # The per-file settings: global → collection_styles[collection] → author
  # preview: block (most specific wins). `cf` is any object exposing `path` and
  # `author` (the ContentFile from the front-matter slice).
  def file_preview_settings(settings, cf, authors)
    coll_overrides = collection_preview_overrides(settings.collection_styles, collection_of(cf.path))
    author_overrides = author_preview_overrides(authors, cf.author)
    result = apply_preview_overrides(settings, coll_overrides, author_overrides)
    info("  ↳ Collection '#{collection_of(cf.path)}' preview style applied") unless coll_overrides.empty?
    unless author_overrides.empty?
      info("  ↳ Author '#{cf.author}' preview overrides applied (#{settings.authors_file})")
    end
    result
  end

  # Model-name prefix → provider family, or nil. FIRST matching prefix wins, in
  # MODEL_FAMILIES insertion order (see constants.rb).
  def model_family(model)
    m = (model || "").to_s.strip.downcase
    MODEL_FAMILIES.each { |prefix, family| return family if m.start_with?(prefix) }
    nil
  end

  # Configured model when it belongs to the provider's family, else the provider
  # default (with a warning) — never emit a guaranteed-400 request. `provider`
  # is any object exposing `name` and `default_model` (the Provider slice).
  def effective_model(settings, provider)
    model = (settings.model || "").to_s.strip
    return provider.default_model if model.empty?

    family = model_family(model)
    if !family.nil? && family != provider.name
      warn("Model '#{model}' belongs to the '#{family}' family; using " \
           "#{provider.name} default '#{provider.default_model}' instead")
      return provider.default_model
    end
    model
  end
end
