# frozen_string_literal: true

require "test_helper"

class CredentialTest < ActiveSupport::TestCase
  test "api_key is encrypted at rest" do
    cred = Credential.create!(provider: "openai", api_key: "sk-secret-value-123456")
    raw = Credential.connection.select_value(
      "SELECT api_key FROM credentials WHERE id = #{cred.id}"
    )
    refute_includes raw.to_s, "sk-secret-value-123456", "plaintext key must not hit the column"
    assert_equal "sk-secret-value-123456", cred.reload.api_key, "but decrypts on read"
  end

  test "one credential per provider" do
    Credential.create!(provider: "openai", api_key: "a" * 12)
    dup = Credential.new(provider: "openai", api_key: "b" * 12)
    refute dup.valid?
  end

  test "masked never reveals the full key" do
    cred = Credential.new(provider: "xai", api_key: "xai-abcdefghijklmnop")
    assert_equal "xai…mnop", cred.masked
    refute_includes cred.masked, "abcdefghij"
  end

  test "environment maps providers to their engine env vars" do
    Credential.create!(provider: "openai", api_key: "key-openai-xx")
    Credential.create!(provider: "gemini", api_key: "key-gemini-xx")
    env = Credential.environment
    assert_equal "key-openai-xx", env["OPENAI_API_KEY"]
    assert_equal "key-gemini-xx", env["GEMINI_API_KEY"]
    refute env.key?("XAI_API_KEY")
  end

  test "rejects unknown providers" do
    refute Credential.new(provider: "midjourney", api_key: "x" * 12).valid?
  end
end
