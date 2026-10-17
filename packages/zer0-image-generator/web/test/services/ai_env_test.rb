# frozen_string_literal: true

require "test_helper"

class AiEnvTest < ActiveSupport::TestCase
  test "stored credentials fill empty env slots" do
    Credential.create!(provider: "xai_oauth", api_key: "grok-oauth-xxxx")
    env = AiEnv.snapshot("OPENAI_API_KEY" => "sk-test")
    assert_equal "sk-test", env["OPENAI_API_KEY"]
    assert_equal "grok-oauth-xxxx", env["XAI_OAUTH_TOKEN"]
  end

  test "GROK_OAUTH_TOKEN aliases into XAI_OAUTH_TOKEN when that slot is empty" do
    env = AiEnv.snapshot("GROK_OAUTH_TOKEN" => "from-grok")
    assert_equal "from-grok", env["XAI_OAUTH_TOKEN"]
  end

  test "XAI_OAUTH_TOKEN wins over the GROK alias" do
    env = AiEnv.snapshot("XAI_OAUTH_TOKEN" => "xai", "GROK_OAUTH_TOKEN" => "grok")
    assert_equal "xai", env["XAI_OAUTH_TOKEN"]
  end
end
