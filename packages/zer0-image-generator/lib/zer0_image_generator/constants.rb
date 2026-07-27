# frozen_string_literal: true

# Port of the constants block of lib/zer0_image_generator/preview_generator.py
# (the Python engine remains the oracle). Values here are reproduced BYTE FOR
# BYTE: the palettes, composition variants and geometry feed the deterministic
# `local` provider, whose output is committed under docs/samples and
# docs/showcase — a changed literal silently re-skins every committed piece.
# test/ruby/test_constants.rb diffs the whole table against the Python module.

module Zer0ImageGenerator
  # Built-in fallbacks — used only when a key is absent from _config.yml, env,
  # and CLI. Claude orchestration (analysis + review) is on by default and
  # degrades gracefully without a Claude credential.
  #
  # String keys, because the same table is indexed by keys read straight out of
  # YAML; `resolve_settings` looks up DEFAULTS[cfg_key] with the config key.
  DEFAULTS = {
    "enabled" => true,
    "provider" => "openai",
    "model" => "", # empty → the active provider's default_model
    "size" => "1536x1024",
    "quality" => "auto",
    "style" => "retro pixel art, 8-bit video game aesthetic, vibrant colors, " \
               "nostalgic, clean pixel graphics",
    "style_modifiers" => "pixelated, retro gaming style, CRT screen glow effect, " \
                         "limited color palette",
    "output_dir" => "assets/images/previews",
    "assets_prefix" => "/assets",
    "auto_prefix" => true,
    "collections" => ["posts"].freeze, # or "auto": discover from Jekyll `collections:`
    "collections_dir" => "",           # Jekyll's collections_dir (zer0-mistakes: "pages")
    "front_matter_key" => "preview",   # jekyll-seo-tag users typically want "image"
    "authors_file" => "_data/authors.yml", # "" disables author overrides
    "prompt_engine" => "claude",       # claude analyzes the article; falls back to template
    "review_engine" => "claude",       # claude vision-reviews the render; `none` disables
    "claude_model" => "",              # empty → DEFAULT_CLAUDE_MODEL
    "claude_effort" => "low",          # output_config.effort for brief/review calls
                                       # (short creative tasks; "" sends no effort)
    "rasterizer" => "auto"             # SVG→PNG tool for the SVG providers (local,
                                       # claude): auto|rsvg|inkscape|magick|playwright
                                       # |none. "none" is SVG-only mode — the vector
                                       # banner IS the deliverable and no PNG is made.
  }.freeze

  # Enhance mode (OpenAI /v1/images/edits — see the OpenAI provider's `edit`).
  ENHANCE_DEFAULTS = {
    "model" => "gpt-image-2",
    "quality" => "auto",
    "fidelity" => "high",
    "format" => "png"
  }.freeze

  DEFAULT_ENHANCE_PROMPT = "Improve this preview banner image: fix any misspelled, garbled, or " \
                           "incorrect text so it reads clearly and accurately. Sharpen visual details " \
                           "and improve composition while preserving the original art style, color " \
                           "palette, and theme. Ensure the image is clean and professional."

  # Anthropic wire constants — keep in sync with templates/deploy/chat-proxy/worker.js.
  ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
  ANTHROPIC_VERSION = "2023-06-01"
  OAUTH_BETA = "oauth-2025-04-20"
  # Claude Code OAuth tokens require the FIRST system block to identify as Claude
  # Code, otherwise the API rejects the call with a misleading `rate_limit_error`.
  CLAUDE_CODE_SYSTEM_PROMPT = "You are Claude Code, Anthropic's official CLI for Claude."
  DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"
  CLAUDE_MAX_TOKENS = 16_000 # non-streaming ceiling; SVG banners fit comfortably

  # Model-name prefix → provider family. Used to ignore a configured/author model
  # that belongs to a different vendor than the active provider (never send a
  # request that is guaranteed to 400).
  #
  # Insertion order is part of the contract: `model_family` returns the FIRST
  # matching prefix, exactly as the Python dict iteration does.
  MODEL_FAMILIES = {
    "claude-" => "claude",
    "gpt-image-" => "openai",
    "dall-e-" => "openai",
    "grok-" => "xai",
    "stable-" => "stability",
    "sd3" => "stability",
    "gemini-" => "gemini",
    "imagen-" => "gemini"
  }.freeze

  # Banner geometry for SVG-producing providers (claude, local).
  SVG_WIDTH = 1536
  SVG_HEIGHT = 1024

  # Curated retro palettes: (sky/background, far, mid, near, accent, glow).
  # Selected deterministically per slug so re-runs stay visually stable.
  RETRO_PALETTES = [
    ["#1a1a2e", "#16213e", "#0f3460", "#533483", "#e94560", "#f9ed69"].freeze,
    ["#0d1b2a", "#1b263b", "#415a77", "#778da9", "#e0e1dd", "#ffb703"].freeze,
    ["#2d132c", "#801336", "#c72c41", "#ee4540", "#f9d276", "#f4f4f4"].freeze,
    ["#10002b", "#3c096c", "#7b2cbf", "#c77dff", "#e0aaff", "#72efdd"].freeze,
    ["#001219", "#005f73", "#0a9396", "#94d2bd", "#e9d8a6", "#ee9b00"].freeze,
    ["#03071e", "#370617", "#9d0208", "#dc2f02", "#f48c06", "#ffba08"].freeze,
    ["#0b132b", "#1c2541", "#3a506b", "#5bc0be", "#6fffe9", "#ff6b6b"].freeze,
    ["#232931", "#393e46", "#4ecca3", "#a5ecd7", "#eeeeee", "#f95959"].freeze,
    ["#1f0a24", "#571089", "#ab51e3", "#f7aef8", "#b388eb", "#8093f1"].freeze,
    ["#141e30", "#243b55", "#3c6382", "#82ccdd", "#f8c291", "#e55039"].freeze
  ].freeze

  COMPOSITION_VARIANTS = [
    "a low horizon with a huge rising sun disk banded by scanlines",
    "layered diagonal mountain silhouettes receding into haze",
    "a vaporwave perspective grid floor vanishing toward the horizon",
    "floating terraced islands with cascading pixel waterfalls",
    "a night starfield with a large ringed planet arcing across the frame",
    "a stepped city skyline of blocky towers with lit windows",
    "rolling desert dunes with a lone monolith and long shadows",
    "an ocean of chunky pixel waves under drifting square clouds"
  ].freeze

  # System prompt for Claude's ART-DIRECTOR role (prompt_engine: claude): read
  # the article, then write the brief a raster image model will render. NOTE:
  # "no text" matches the long-standing prompt rule of this feature — image
  # models garble lettering.
  #
  # `.chomp` because Python's triple-quoted literal ends right after "kind." —
  # a heredoc would otherwise append a newline the oracle never sends.
  ART_DIRECTOR_SYSTEM = <<~PROMPT.chomp
    You are an art director for a technical blog. You will be given an article
    (title, description, tags, an excerpt) plus mandatory style directions. Your
    job is to design ONE preview banner image and describe it to an AI image
    model.

    Respond with ONLY the image-generation prompt — no preamble, no quotes, no
    markdown. One vivid paragraph of at most 130 words that:
    - captures the article's actual SUBJECT as a concrete visual metaphor or
      scene (specific objects, actions and spatial arrangement — never a generic
      'technology background');
    - specifies composition for a wide banner (what sits left/center/right,
      foreground/background, focal point);
    - weaves in the given art style and palette directions verbatim in spirit;
    - states that the image must contain NO text, letters, words, numbers, logos
      or UI copy of any kind.
  PROMPT

  # System prompt for Claude's REVIEWER role (review_engine: claude): look at
  # the rendered image and decide whether it represents the article.
  REVIEWER_SYSTEM = <<~PROMPT.chomp
    You are reviewing an AI-generated blog preview banner against the article it
    illustrates. Judge three things: (1) does the image clearly evoke the
    article's actual subject, (2) does it follow the requested art style, and
    (3) is it free of text/lettering artifacts and visual glitches.

    Respond with ONLY a JSON object, no markdown fences:
    {"verdict": "approve" | "revise",
     "critique": "<one or two sentences on what is wrong or right>",
     "revised_prompt": "<empty when approving; otherwise a complete replacement
    image-generation prompt (max 130 words) that fixes the problems while keeping
    the required style and the no-text rule>"}

    Approve unless the image genuinely misrepresents the subject, breaks the
    style, or contains text/glitches — minor taste differences are not grounds
    for revision.
  PROMPT

  PNG_SIGNATURE = "\x89PNG\r\n\x1a\n".b.freeze

  # Pause after each successful non-dry generation (Bash parity: polite pacing
  # between paid API calls).
  POST_GENERATION_SLEEP = 2.0

  # Settings fields an override block (author preview: / collection_styles:)
  # may replace per file.
  OVERRIDE_KEYS = %w[style style_modifiers size quality model].freeze

  class << self
    # The Python module-global POST_GENERATION_SLEEP is rebindable and the test
    # suite sets it to 0; a Ruby constant is not, so the *runtime* value lives
    # here and the constant stays the immutable published default.
    attr_accessor :post_generation_sleep
  end
  self.post_generation_sleep = POST_GENERATION_SLEEP
end
