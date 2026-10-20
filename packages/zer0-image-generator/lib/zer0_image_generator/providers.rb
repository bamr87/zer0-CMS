# frozen_string_literal: true

require_relative "providers/base"
require_relative "providers/openai"
require_relative "providers/xai"
require_relative "providers/stability"
require_relative "providers/gemini"
require_relative "providers/local"

module Zer0ImageGenerator
  # Renderers only — Claude is the orchestration layer (article brief + image
  # review) that sits in front of ANY of these, not a provider itself. Keyed by
  # provider name so the runner can look one up by the resolved `provider`
  # setting.
  PROVIDERS = [
    OpenAIProvider.new,
    XAIProvider.new,
    StabilityProvider.new,
    GeminiProvider.new,
    LocalProvider.new,
  ].each_with_object({}) { |provider, registry| registry[provider.name] = provider }.freeze
end
