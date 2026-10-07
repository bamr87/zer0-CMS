# frozen_string_literal: true

require "base64"
require "pathname"

# Port of the provider-layer scaffolding from preview_generator.py
# (ImageResult, EditUnsupported, Provider, RunContext, adapt_openai_size_quality,
# and the shared _write_image_payload helper). The concrete providers live in
# sibling files; this one carries only what they all share.
#
# Cross-slice dependencies are referenced by their natural names and resolved at
# call time (never at load time), so this file loads even while the http/svg/
# settings/logging slices are still landing:
#   Zer0ImageGenerator::Http         — .json/.multipart/.download_to/.with_retries
#   Zer0ImageGenerator::HttpStatusError#error_message
#   Zer0ImageGenerator::Svg::Sanitizer.sanitize_svg / ::LocalRenderer.{seed_for,
#     render_local_svg} / ::Rasterizer.rasterize_svg + Svg::SvgError
#   Zer0ImageGenerator.effective_model(settings, provider)
#   Zer0ImageGenerator::Logging.warn / .info / .debug
module Zer0ImageGenerator
  # Historical engine behavior: adapt shared size/quality settings per model
  # family. The mapping MUST stay exact — gpt-image-* and dall-e-3 accept
  # disjoint size/quality vocabularies, and a wrong value 400s the request.
  def self.adapt_openai_size_quality(model, size, quality)
    if model.start_with?("gpt-image-") && size == "1792x1024"
      size = "1536x1024"
    elsif model.start_with?("dall-e-") && quality == "auto"
      quality = "standard"
    end
    [size, quality]
  end

  # Outcome of one generate/edit call. Positional (ok, kind, path) mirrors the
  # Python dataclass construction order; `error` stays a keyword so the many
  # `ImageResult(False, error=...)` call sites read the same in Ruby.
  class ImageResult
    attr_reader :ok, :kind, :path, :error

    def initialize(ok, kind = "png", path = nil, error: nil)
      @ok = ok
      @kind = kind    # "png" | "svg"
      @path = path
      @error = error
    end

    # Runner (another slice) reads `.ok`; `.ok?` is the idiomatic Ruby alias.
    def ok?
      @ok
    end
  end

  # Raised by Provider#edit for renderers with no image-edit capability; the
  # runner catches it and falls back to OpenAI (the historical --enhance path).
  class EditUnsupported < StandardError
    attr_reader :provider

    def initialize(provider)
      @provider = provider
      super("provider '#{provider}' has no image-edit capability")
    end
  end

  class Provider
    def name
      "base"
    end

    def is_configured(_env)
      raise NotImplementedError
    end

    def missing_hint(_env)
      raise NotImplementedError
    end

    def default_model
      raise NotImplementedError
    end

    # One line naming the credential this run will authenticate with, for the
    # config banner. nil (the default) means "there is nothing interesting to
    # say" — a provider with exactly one possible credential.
    def auth_description(_env)
      nil
    end

    def generate(_prompt, _settings, _out_base, _ctx)
      raise NotImplementedError
    end

    # Enhance an existing image. Providers without an edit capability raise
    # EditUnsupported; the runner then falls back to OpenAI.
    def edit(_image_path, _prompt, _settings, _ctx, _out_path = nil)
      raise EditUnsupported, name
    end

    private

    # Persist one OpenAI-style data[0] entry (b64_json preferred, else url).
    # nil/empty strings count as "absent" to match Python's truthiness on
    # `entry.get(...)` — a present-but-empty value must not be treated as data.
    def write_image_payload(entry, out_path)
      b64 = entry["b64_json"]
      if b64 && !b64.empty?
        File.binwrite(out_path.to_s, Base64.decode64(b64))
        return true
      end
      url = entry["url"]
      if url && !url.empty?
        Http.download_to(url, out_path)
        return true
      end
      false
    end
  end

  # Run-scoped services handed to providers. The per-file `slug` is why the
  # runner hands each worker its OWN copy (see #copy_with): the local provider
  # derives its deterministic seed from the slug, so a shared mutable slug would
  # cross-contaminate concurrent renders.
  class RunContext
    attr_reader :project_root, :env
    attr_accessor :anthropic, :grok, :slug, :article

    def initialize(project_root:, env:, anthropic: nil, grok: nil, slug: "", article: nil)
      @project_root = project_root
      @env = env
      @anthropic = anthropic
      @grok = grok
      @slug = slug
      # The page's own context (slug/section/title/categories/description/body),
      # set per file by the runner. The local renderer derives BOTH composition
      # and palette from it, which is what makes a banner about its article
      # instead of about its filename.
      @article = article
    end

    def claude
      # Lazy, memoized — matches the Python `if self.anthropic is None`.
      @anthropic ||= AnthropicClient.new(@env)
    end

    def grok_client
      @grok ||= GrokClient.new(@env)
    end

    def orchestrator(engine)
      engine.to_s == "xai" ? grok_client : claude
    end

    # Per-file copy carrying a fresh slug (the runner calls `ctx.with_slug(slug)`
    # once per worker). project_root/env/anthropic are shared by reference on
    # purpose: env is read-only and the AnthropicClient is stateless after init,
    # so sharing them across workers is thread-safe; only the slug is per-file
    # and therefore must not be shared.
    def with_slug(slug, article: nil)
      RunContext.new(project_root: @project_root, env: @env,
                     anthropic: @anthropic, grok: @grok, slug: slug, article: article)
    end
  end
end
