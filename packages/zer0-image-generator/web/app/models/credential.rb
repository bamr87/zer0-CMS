# frozen_string_literal: true

# An API key (or OAuth token) for one provider, encrypted at rest.
#
# The engine reads credentials from the environment, so these rows are not a
# second source of truth: they are materialized into a run's environment when a
# job starts and never written to disk.
class Credential < ApplicationRecord
  # Renderers bill per image. xai_oauth is the second way into the SAME xAI
  # renderer — a Grok OAuth access token, which the engine tries before the
  # xai API key and falls back from when it is expired or rejected.
  #
  # The two claude_* entries feed the engine's Claude credential chain (which
  # drives the analyze/review art-direction stages) — claude_oauth is the
  # Pro/Max token from `claude setup-token` and is tried first; anthropic is a
  # console.anthropic.com API key, tried after it.
  RENDERERS = %w[openai xai xai_oauth stability gemini].freeze
  CLAUDE_PROVIDERS = %w[claude_oauth anthropic].freeze
  PROVIDERS = (RENDERERS + CLAUDE_PROVIDERS).freeze

  # Credential slots that are an alternative AUTH MODE for a renderer rather
  # than a renderer of their own — mapped to the engine provider they log into.
  RENDERER_AUTH = { "xai_oauth" => "xai" }.freeze

  # The environment variable each entry is exported as. These names are the
  # engine's contract — changing one silently disables that credential.
  ENV_VARS = {
    "openai" => "OPENAI_API_KEY",
    "xai" => "XAI_API_KEY",
    "xai_oauth" => "XAI_OAUTH_TOKEN",
    "stability" => "STABILITY_API_KEY",
    "gemini" => "GEMINI_API_KEY",
    "anthropic" => "ANTHROPIC_API_KEY",
    "claude_oauth" => "CLAUDE_CODE_OAUTH_TOKEN",
  }.freeze

  # Human labels for the credential slots.
  LABELS = {
    "openai" => "OpenAI (renderer)",
    "xai" => "xAI Grok API key (renderer)",
    "xai_oauth" => "xAI Grok OAuth token (renderer + art direction)",
    "stability" => "Stability (renderer)",
    "gemini" => "Gemini (renderer)",
    "anthropic" => "Anthropic API key (Claude art direction)",
    "claude_oauth" => "Claude Code OAuth token (Claude art direction)",
  }.freeze

  encrypts :api_key

  validates :provider, presence: true, inclusion: { in: PROVIDERS }, uniqueness: true
  validates :api_key, presence: true

  scope :usable, -> { where.not(api_key: nil) }

  def env_var
    ENV_VARS.fetch(provider)
  end

  def renderer?
    RENDERERS.include?(provider)
  end

  # The engine provider this credential authenticates, which is the slot itself
  # for a plain renderer key and the renderer it logs into for an auth mode.
  def renders_as
    RENDERER_AUTH.fetch(provider, provider)
  end

  def claude?
    CLAUDE_PROVIDERS.include?(provider)
  end

  # Never render a key in full; the UI only needs enough to tell two keys apart.
  def masked
    return "" if api_key.blank?
    return "…" if api_key.length < 8

    "#{api_key[0, 3]}…#{api_key[-4, 4]}"
  end

  # Environment fragment for a run. Built fresh per job so a revoked key stops
  # working immediately rather than lingering in a cached process environment.
  def self.environment
    usable.each_with_object({}) { |credential, env| env[credential.env_var] = credential.api_key }
  end

  # Is Claude art direction available at all — either a stored claude_* entry or
  # one of the chain's env vars set on the process? Mirrors the order the
  # engine's AnthropicClient checks: OAuth token, auth token, API key.
  def self.claude_available?(env = ENV)
    return true if usable.where(provider: CLAUDE_PROVIDERS).exists?

    %w[CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY].any? { |v| env[v].present? }
  end

  # What a slot does, for the credentials table.
  def self.role_label(provider)
    return "Claude art direction" if CLAUDE_PROVIDERS.include?(provider)
    return "xAI renderer + Grok art direction" if provider == "xai_oauth"
    return "#{RENDERER_AUTH[provider]} renderer login" if RENDERER_AUTH.key?(provider)

    "renderer"
  end

  def self.xai_available?(env = ENV)
    return true if usable.where(provider: %w[xai xai_oauth]).exists?

    %w[XAI_OAUTH_TOKEN GROK_OAUTH_TOKEN XAI_API_KEY].any? { |name| env[name].present? }
  end

  # A short description of how the xAI renderer will authenticate, for the UI.
  # Mirrors the engine's own ladder: OAuth token first (stored, then env, then
  # a Grok credentials file the engine finds on disk), API key as the fallback.
  def self.xai_source(env = ENV)
    return "Grok OAuth token (stored)" if usable.exists?(provider: "xai_oauth")
    return "XAI_OAUTH_TOKEN (environment)" if env["XAI_OAUTH_TOKEN"].present?
    return "GROK_OAUTH_TOKEN (environment)" if env["GROK_OAUTH_TOKEN"].present?
    return "xAI API key (stored)" if usable.exists?(provider: "xai")
    return "XAI_API_KEY (environment)" if env["XAI_API_KEY"].present?

    nil
  end

  # A short description of how Claude will authenticate, for the UI.
  def self.claude_source(env = ENV)
    return "Claude Code OAuth token (stored)" if usable.exists?(provider: "claude_oauth")
    return "Anthropic API key (stored)" if usable.exists?(provider: "anthropic")
    return "CLAUDE_CODE_OAUTH_TOKEN (environment)" if env["CLAUDE_CODE_OAUTH_TOKEN"].present?
    return "ANTHROPIC_AUTH_TOKEN (environment)" if env["ANTHROPIC_AUTH_TOKEN"].present?
    return "ANTHROPIC_API_KEY (environment)" if env["ANTHROPIC_API_KEY"].present?

    nil
  end
end
