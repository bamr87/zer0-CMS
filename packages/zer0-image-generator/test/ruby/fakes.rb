# frozen_string_literal: true

# Test doubles for the settings/content/providers/claude slices this slice
# depends on. The Runner/CLI reach every cross-slice symbol through a
# Collaborators object, so a fake with the same surface fully isolates this
# slice's logic — no other Ruby slice needs to exist for these tests to run.

require "pathname"

module Fakes
  PNG_SIGNATURE = "\x89PNG\r\n\x1a\n".b

  # Enough of Settings for the Runner/CLI to read. `with` mirrors the dataclass
  # `replace` the degrade path uses.
  Settings = Struct.new(
    :provider, :model, :size, :quality, :style, :style_modifiers, :output_dir,
    :assets_prefix, :auto_prefix, :enabled, :collections, :collections_dir,
    :collection_styles, :front_matter_key, :authors_file, :prompt_engine,
    :review_engine, :claude_model, :claude_effort, :dry_run, :verbose, :force,
    :list_only, :parallel, :batch, :file, :collection, :enhance,
    :enhance_prompt, :enhance_model, :enhance_quality, :enhance_fidelity,
    :enhance_format, :rasterizer, :provider_explicit,
    keyword_init: true
  ) do
    def with(**changes)
      dup.tap { |s| changes.each { |k, v| s[k] = v } }
    end
  end

  def self.settings(**overrides)
    Settings.new({
      provider: "openai", model: "", size: "1536x1024", quality: "auto",
      style: "s", style_modifiers: "sm", output_dir: "assets/images/previews",
      assets_prefix: "", auto_prefix: true, enabled: true,
      collections: ["posts"], collections_dir: "", collection_styles: {},
      front_matter_key: "preview", authors_file: "_data/authors.yml",
      prompt_engine: "claude", review_engine: "claude", claude_model: "",
      claude_effort: "medium", dry_run: false, verbose: false, force: false,
      list_only: false, parallel: 1, batch: 0, file: "", collection: "",
      enhance: false, enhance_prompt: "", enhance_model: "gpt-image-2",
      enhance_quality: "auto", enhance_fidelity: "high", enhance_format: "png",
      rasterizer: "auto", provider_explicit: false
    }.merge(overrides))
  end

  ContentFile = Struct.new(
    :path, :title, :description, :categories, :preview, :author, :content,
    :front_matter, keyword_init: true
  )

  ImageResult = Struct.new(:ok, :kind, :path, :error, keyword_init: true) do
    def initialize(ok:, kind: "png", path: nil, error: nil)
      super
    end
  end

  # Stand-in for RunContext. with_slug returns a COPY carrying the same claude
  # reference — the exact per-file copy the Runner relies on for thread safety.
  class Ctx
    attr_reader :env, :slug, :project_root

    def initialize(env: {}, claude: nil, slug: "", project_root: Pathname.new("."))
      @env = env
      @claude = claude || Object.new
      @slug = slug
      @project_root = project_root
    end

    def claude
      @claude
    end

    def with_slug(slug)
      Ctx.new(env: @env, claude: @claude, slug: slug, project_root: @project_root)
    end
  end

  class EditUnsupported < StandardError; end

  # Configurable provider double. Pass a block for generate; edit/config knobs
  # are keyword args.
  class Provider
    attr_reader :name

    def initialize(name:, configured: true, default_model: "m",
                   missing_hint: "missing key", edit: nil, &generate)
      @name = name
      @configured = configured
      @default_model = default_model
      @missing_hint = missing_hint
      @edit = edit
      @generate = generate
    end

    def is_configured(_env)
      @configured
    end

    def missing_hint(_env)
      @missing_hint
    end

    def default_model
      @default_model
    end

    def generate(prompt, settings, out_base, ctx)
      @generate.call(prompt, settings, out_base, ctx)
    end

    def edit(image_path, prompt, settings, ctx, out_path = nil)
      raise EditUnsupported, @name if @edit.nil?

      @edit.call(image_path, prompt, settings, ctx, out_path)
    end
  end

  # Implements the full Collaborators surface with test-configurable behavior.
  class Deps
    attr_accessor :providers, :authors, :parse_result, :preview_exists,
                  :preview_image, :review_replies, :fm_updates, :article_brief,
                  :front_matter_path

    def initialize(providers: {})
      @providers = providers
      @authors = {}
      @parse_map = {}
      @preview_exists = false
      @preview_image = nil
      @review_replies = []
      @fm_updates = []
      @article_brief = nil
      @front_matter_path = nil
    end

    # Map a specific path (String) to a ContentFile (or nil to skip).
    def stub_parse(path, cf)
      @parse_map[path.to_s] = cf
    end

    # -- content ---------------------------------------------------------
    def read_authors(_root, _authors_file)
      @authors
    end

    def parse_front_matter(path, _fm_key)
      return @parse_map.fetch(path.to_s) if @parse_map.key?(path.to_s)

      @parse_result
    end

    def check_preview_exists(_preview, _settings, _root)
      @preview_exists
    end

    def find_preview_image(_preview, _settings, _root)
      @preview_image
    end

    def generate_filename(title)
      title.to_s.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/\A-|-\z/, "")
    end

    def file_preview_settings(settings, _cf, _authors)
      settings
    end

    def build_prompt(cf, _settings)
      "PROMPT:#{cf.title}"
    end

    def build_enhance_prompt(cf, _settings)
      "ENHANCE:#{cf.title}"
    end

    def preview_front_matter_path(_settings, filename)
      return @front_matter_path.call(filename) if @front_matter_path

      "/images/previews/#{filename}"
    end

    def update_front_matter(path, value, dry_run:, key:)
      @fm_updates << { path: path.to_s, value: value, dry_run: dry_run, key: key }
      true
    end

    # -- claude ----------------------------------------------------------
    def claude_article_brief(_client, _cf, _settings, base_prompt)
      return @article_brief.call(base_prompt) if @article_brief

      base_prompt
    end

    def claude_review_image(_client, _image_path, _cf, _prompt, _settings)
      @review_replies.shift
    end

    # -- providers / ctx / constants ------------------------------------
    def provider_names_sorted
      @providers.keys.sort
    end

    def edit_unsupported
      EditUnsupported
    end

    def with_slug(ctx, slug)
      ctx.with_slug(slug)
    end

    def post_generation_sleep
      0
    end

    def new_run_context(_root, _env)
      Ctx.new
    end
  end
end
