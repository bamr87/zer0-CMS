# frozen_string_literal: true

# Single snapshot of credentials for every AI-using service (generation runs,
# the image forge, enhance, availability checks in the UI).
#
# Process ENV is the base; stored Credential rows fill empty slots. Grok OAuth
# aliases are normalized so XAI_OAUTH_TOKEN is always the name the engine reads.
module AiEnv
  def self.snapshot(base = ENV)
    env = base.to_h.merge(Credential.environment)
    grok = env["GROK_OAUTH_TOKEN"].to_s
    env["XAI_OAUTH_TOKEN"] = grok if env["XAI_OAUTH_TOKEN"].to_s.empty? && !grok.empty?
    env
  end
end
