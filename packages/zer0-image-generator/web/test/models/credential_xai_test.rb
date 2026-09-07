# frozen_string_literal: true

require "test_helper"

# The xAI renderer has two ways in — a Grok OAuth token and an API key — and the
# engine tries them in that order, falling back to the key when the token is
# expired or rejected. These cover the slot the UI stores the token in.
class CredentialXaiTest < ActiveSupport::TestCase
  test "xai_oauth maps to the XAI_OAUTH_TOKEN env var" do
    c = Credential.create!(provider: "xai_oauth", api_key: "grok-oauth-xxxx")
    assert_equal "XAI_OAUTH_TOKEN", c.env_var
    assert c.renderer?
    refute c.claude?
    assert_equal "grok-oauth-xxxx", Credential.environment["XAI_OAUTH_TOKEN"]
  end

  test "both xAI slots can be stored at once — that IS the fallback" do
    Credential.create!(provider: "xai_oauth", api_key: "grok-oauth-xxxx")
    Credential.create!(provider: "xai", api_key: "xai-key-xxxxxx")
    env = Credential.environment
    assert_equal "grok-oauth-xxxx", env["XAI_OAUTH_TOKEN"]
    assert_equal "xai-key-xxxxxx", env["XAI_API_KEY"]
  end

  test "an auth slot names the renderer it logs into" do
    assert_equal "xai", Credential.new(provider: "xai_oauth").renders_as
    assert_equal "xai", Credential.new(provider: "xai").renders_as
    assert_equal "xai renderer login", Credential.role_label("xai_oauth")
    assert_equal "renderer", Credential.role_label("xai")
    assert_equal "Claude art direction", Credential.role_label("claude_oauth")
  end

  test "xai_source follows the engine's ladder: OAuth token, then API key" do
    assert_nil Credential.xai_source({})
    assert_equal "XAI_API_KEY (environment)", Credential.xai_source("XAI_API_KEY" => "k")
    assert_equal "XAI_OAUTH_TOKEN (environment)",
                 Credential.xai_source("XAI_OAUTH_TOKEN" => "t", "XAI_API_KEY" => "k")
    assert_equal "GROK_OAUTH_TOKEN (environment)",
                 Credential.xai_source("GROK_OAUTH_TOKEN" => "t")
  end

  test "xai_source prefers a stored token over anything in the environment" do
    Credential.create!(provider: "xai_oauth", api_key: "t" * 12)
    assert_equal "Grok OAuth token (stored)", Credential.xai_source("XAI_API_KEY" => "k")
  end

  test "a stored xAI key is named when no OAuth token exists" do
    Credential.create!(provider: "xai", api_key: "k" * 12)
    assert_equal "xAI API key (stored)", Credential.xai_source({})
  end
end
