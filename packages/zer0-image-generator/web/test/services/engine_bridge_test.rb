# frozen_string_literal: true

require "test_helper"

# Availability is the ENGINE's question, not a table of provider -> env var kept
# here: xAI, for one, is reachable through a Grok OAuth token as well as its API
# key, and only the engine knows the full ladder.
class EngineBridgeTest < ActiveSupport::TestCase
  # HOME points at an empty dir so a real ~/.grok/auth.json on the machine
  # running the suite cannot make xAI look configured.
  def env(**overrides)
    { "HOME" => Dir.mktmpdir("engine-bridge-home") }.merge(overrides.transform_keys(&:to_s))
  end

  test "local needs no credential and is always available" do
    assert_includes EngineBridge.available_providers(env), "local"
  end

  test "a renderer shows up once its key is present" do
    refute_includes EngineBridge.available_providers(env), "openai"
    assert_includes EngineBridge.available_providers(env("OPENAI_API_KEY" => "k")), "openai"
  end

  test "xai is available through a Grok OAuth token alone" do
    refute_includes EngineBridge.available_providers(env), "xai"
    assert_includes EngineBridge.available_providers(env("XAI_OAUTH_TOKEN" => "t")), "xai"
    assert_includes EngineBridge.available_providers(env("XAI_API_KEY" => "k")), "xai"
  end

  test "the stored credentials feed the same check" do
    Credential.create!(provider: "xai_oauth", api_key: "t" * 12)
    merged = env.merge(Credential.environment)
    assert_includes EngineBridge.available_providers(merged), "xai"
  end
end
