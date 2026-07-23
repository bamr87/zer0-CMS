# frozen_string_literal: true

# Drives the engine's image pipeline for a single interactive Composition.
#
# The Runner is file-oriented (discover markdown, update front matter), which is
# wrong for a standalone image. So the forge calls the same engine building
# blocks the Runner does — build_prompt, claude_article_brief, provider.generate,
# claude_review_image, provider.edit — directly, against a ContentFile
# synthesized from the composition's title + brief. One engine, no second brain.
#
# All the Claude work authenticates through the engine's own credential chain
# (CLAUDE_CODE_OAUTH_TOKEN first), so a stored Claude Code OAuth token or one in
# the environment makes the analyze/review stages live with no extra wiring.
class Forge
  class Error < StandardError; end

  def initialize(env: ENV.to_h, logger: nil)
    EngineBridge.load!
    @env = env
    @log = logger || ->(_msg) {}
  end

  # Run analyze -> produce -> (review -> maybe revise) for a composition.
  # Persists a CompositionImage per produced version and returns them.
  def compose(composition)
    settings = settings_for(composition)
    cf = content_file(composition)
    ctx = context_for(composition, slug: slug_for(composition))
    provider = provider!(settings.provider)
    orchestrated = settings.provider != "local"

    produced = []

    # ---- Analyze: Claude reads the brief and writes the art direction -------
    base_prompt = Zer0ImageGenerator::Prompt.build_prompt(cf, settings)
    prompt = base_prompt
    if orchestrated && settings.prompt_engine == "claude"
      log("Analyzing brief with Claude (#{claude_source})…")
      prompt = Zer0ImageGenerator::Orchestration.claude_article_brief(ctx.claude, cf, settings, base_prompt)
      log(prompt == base_prompt ? "Claude unavailable — using the template prompt." : "Claude wrote the art brief.")
    else
      log("Using the template prompt (provider=#{settings.provider}, prompt_engine=#{settings.prompt_engine}).")
    end

    # ---- Produce: the chosen renderer makes the image -----------------------
    out_base = forge_dir(composition).join(next_slug(composition, "render"))
    log("Rendering with #{settings.provider}…")
    result = provider.generate(prompt, settings, out_base, ctx)
    raise Error, (result.error.presence || "renderer failed") unless result.ok?

    # Claude actually directed this render only if the brief it produced
    # differs from the template fallback — a failed/unavailable Claude call
    # leaves prompt == base_prompt.
    directed = orchestrated && settings.prompt_engine == "claude" && prompt != base_prompt
    produced << persist(composition, result, stage: "render", vendor: settings.provider,
                                     prompt: prompt, settings: settings, claude_directed: directed)
    log("Rendered #{File.basename(result.path.to_s)}.")

    # ---- Review: Claude inspects the render; at most ONE revision -----------
    if orchestrated && settings.review_engine == "claude" && result.ok? && result.kind == "png"
      log("Reviewing the render with Claude…")
      approved, critique, revised = Zer0ImageGenerator::Orchestration.claude_review_image(
        ctx.claude, result.path, cf, prompt, settings
      )
      produced.last.update!(critique: critique) if critique.present?
      if approved
        log(critique.present? ? "Claude approved: #{critique}" : "Claude approved the render.")
      else
        log("Claude requested a revision: #{critique}")
        revised_base = forge_dir(composition).join(next_slug(composition, "revision"))
        retry_result = provider.generate(revised, settings, revised_base, ctx)
        if retry_result.ok?
          produced << persist(composition, retry_result, stage: "revision", vendor: settings.provider,
                                          prompt: revised, settings: settings, critique: critique,
                                          claude_directed: true)
          log("Regenerated with Claude's revised brief.")
        else
          log("Revision render failed (#{retry_result.error}); keeping the original.")
        end
      end
    end

    produced
  end

  # Process an existing image further with OpenAI's images/edits endpoint.
  # Returns the new enhanced CompositionImage.
  def enhance(image, prompt: nil)
    composition = image.composition
    settings = settings_for(composition)
    ctx = context_for(composition, slug: slug_for(composition))
    provider = provider!("openai")
    unless provider.is_configured(@env)
      raise Error, "OpenAI is not configured — add an OPENAI_API_KEY credential to enhance."
    end
    unless image.exists?
      raise Error, "The source image is no longer on disk."
    end

    enhance_prompt = prompt.presence || Zer0ImageGenerator::DEFAULT_ENHANCE_PROMPT
    out_base = forge_dir(composition).join(next_slug(composition, "enhanced"))
    log("Enhancing with OpenAI (images/edits)…")
    result = provider.edit(image.pathname, enhance_prompt, settings, ctx, out_base)
    raise Error, (result.error.presence || "OpenAI enhance failed") unless result.ok?

    log("Enhanced #{File.basename(result.path.to_s)}.")
    persist(composition, result, stage: "enhanced", vendor: "openai",
                        prompt: enhance_prompt, settings: settings)
  end

  private

  def log(message)
    @log.call(message)
  end

  # Build engine Settings from the composition's knobs, honoring env precedence.
  def settings_for(composition)
    args = {
      provider: composition.provider,
      model: composition.model.presence,
      style: composition.style.presence,
      prompt_engine: composition.prompt_engine,
      review: composition.review_engine,
    }.compact
    settings = EngineBridge.resolve_settings(args, {})
    # Fields resolve_settings reads only from config/env, applied here from the
    # composition so the workspace's knobs win.
    settings.size = composition.size if composition.size.present?
    settings.quality = composition.quality if composition.quality.present?
    settings.style_modifiers = composition.style_modifiers if composition.style_modifiers.present?
    settings
  end

  # A ContentFile the engine's prompt/analyze/review code understands, built
  # from the composition rather than a markdown file on disk.
  def content_file(composition)
    Zer0ImageGenerator::ContentFile.new(
      "composition-#{composition.id}", # path (only used for logging)
      composition.title.to_s,          # title
      composition.brief.to_s.lines.first.to_s.strip, # description = first line
      "",                              # categories
      nil,                             # preview
      nil,                             # author
      composition.brief.to_s,          # content (the full brief)
      {}                               # data
    )
  end

  def context_for(composition, slug:)
    Zer0ImageGenerator::RunContext.new(
      project_root: Pathname.new(forge_dir(composition).to_s), env: @env, slug: slug
    )
  end

  def provider!(name)
    Zer0ImageGenerator::PROVIDERS.fetch(name) { raise Error, "Unknown provider: #{name}" }
  end

  def forge_dir(composition)
    dir = Rails.application.config.repo_root.join(".forge", "composition-#{composition.id}")
    FileUtils.mkdir_p(dir)
    dir
  end

  def slug_for(composition)
    base = Zer0ImageGenerator::Content.generate_filename(composition.title)
    base.presence || "image-#{composition.id}"
  end

  # A unique, ordered basename per produced version so files never clobber.
  def next_slug(composition, stage)
    n = composition.images.count + 1
    "#{slug_for(composition)}-#{format('%02d', n)}-#{stage}"
  end

  def persist(composition, result, stage:, vendor:, prompt:, settings:, critique: nil, claude_directed: false)
    path = result.path.to_s
    composition.images.create!(
      stage: stage, vendor: vendor, prompt: prompt, critique: critique,
      path: path, kind: result.kind, byte_size: (File.size(path) if File.file?(path)),
      position: composition.images.count,
      metadata: {
        # Whether Claude actually wrote/revised this brief, not merely whether
        # it was requested — a local render or a failed Claude call is not
        # "claude-directed".
        claude_directed: claude_directed,
        prompt_engine: settings.prompt_engine, review_engine: settings.review_engine,
        model: settings.model, size: settings.size, quality: settings.quality
      }
    )
  end

  def claude_source
    Credential.claude_source(@env) || "credential chain"
  end
end
