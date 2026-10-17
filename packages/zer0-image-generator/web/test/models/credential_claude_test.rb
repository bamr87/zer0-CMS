# frozen_string_literal: true

require "test_helper"

class CredentialClaudeTest < ActiveSupport::TestCase
  test "claude_oauth maps to the CLAUDE_CODE_OAUTH_TOKEN env var" do
    c = Credential.create!(provider: "claude_oauth", api_key: "oauth-token-xxxx")
    assert_equal "CLAUDE_CODE_OAUTH_TOKEN", c.env_var
    assert c.claude?
    refute c.renderer?
    assert_equal "oauth-token-xxxx", Credential.environment["CLAUDE_CODE_OAUTH_TOKEN"]
  end

  test "claude_available? sees a stored OAuth token" do
    refute Credential.claude_available?({})
    Credential.create!(provider: "claude_oauth", api_key: "t" * 12)
    assert Credential.claude_available?({})
  end

  test "claude_available? sees an env token when nothing is stored" do
    assert Credential.claude_available?("CLAUDE_CODE_OAUTH_TOKEN" => "x")
    assert Credential.claude_available?("ANTHROPIC_API_KEY" => "x")
    refute Credential.claude_available?("OPENAI_API_KEY" => "x")
  end

  test "claude_source names the stored token over the environment" do
    Credential.create!(provider: "claude_oauth", api_key: "t" * 12)
    assert_equal "Claude Code OAuth token (stored)",
                 Credential.claude_source("ANTHROPIC_API_KEY" => "env-key")
  end

  test "the renderer providers are still valid credentials" do
    assert Credential.new(provider: "openai", api_key: "k" * 12).valid?
    refute Credential.new(provider: "not-a-provider", api_key: "k" * 12).valid?
  end
end
