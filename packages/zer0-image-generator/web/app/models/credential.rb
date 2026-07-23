# frozen_string_literal: true

# An API key (or OAuth token) for one provider, encrypted at rest.
#
# The engine reads credentials from the environment, so these rows are not a
# second source of truth: they are materialized into a run's environment when a
# job starts and never written to disk.
class Credential < ApplicationRecord
  # Renderers bill per image. The two claude_* entries feed the engine's Claude
  # credential chain (which drives the analyze/review art-direction stages) —
  # claude_oauth is the Pro/Max token from `claude setup-token` and is tried
  # first; anthropic is a console.anthropic.com API key, tried after it.
  RENDERERS = %w[openai xai stability gemini].freeze
  CLAUDE_PROVIDERS = %w[claude_oauth anthropic].freeze
  PROVIDERS = (RENDERERS + CLAUDE_PROVIDERS).freeze

  # The environment variable each entry is exported as. These names are the
  # engine's contract — changing one silently disables that credential.
  ENV_VARS = {
    "openai" => "OPENAI_API_KEY",
    "xai" => "XAI_API_KEY",
    "stability" => "STABILITY_API_KEY",
    "gemini" => "GEMINI_API_KEY",
    "anthropic" => "ANTHROPIC_API_KEY",
    "claude_oauth" => "CLAUDE_CODE_OAUTH_TOKEN",
  }.freeze

  # Human labels for the credential slots.
  LABELS = {
    "openai" => "OpenAI (renderer)",
    "xai" => "xAI Grok (renderer)",
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
