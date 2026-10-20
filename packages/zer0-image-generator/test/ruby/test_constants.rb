# frozen_string_literal: true

# Byte-identity test for the ported constants. The palettes, composition
# variants and geometry feed the deterministic `local` provider whose output
# is committed under docs/samples and docs/showcase — a single changed literal
# silently re-skins every committed piece, so every value is diffed against the
# Python oracle.
#
#     ruby -Ilib test/ruby/test_constants.rb

require "minitest/autorun"
require "json"
require "open3"
require_relative "../../lib/zer0_image_generator/constants"

class TestConstants < Minitest::Test
  M = Zer0ImageGenerator
  ORACLE = File.expand_path("constants_oracle.py", __dir__)

  def python_available?
    out, status = Open3.capture2e("python3", "--version")
    status.success? && !out.strip.empty?
  rescue StandardError
    false
  end

  # The Ruby side of the table, shaped to match constants_oracle.py's JSON.
  def ruby_table
    {
      "DEFAULTS" => M::DEFAULTS.transform_values { |v| v.is_a?(Array) ? v.dup : v },
      "ENHANCE_DEFAULTS" => M::ENHANCE_DEFAULTS,
      "DEFAULT_ENHANCE_PROMPT" => M::DEFAULT_ENHANCE_PROMPT,
      "ANTHROPIC_API_URL" => M::ANTHROPIC_API_URL,
      "ANTHROPIC_VERSION" => M::ANTHROPIC_VERSION,
      "OAUTH_BETA" => M::OAUTH_BETA,
      "CLAUDE_CODE_SYSTEM_PROMPT" => M::CLAUDE_CODE_SYSTEM_PROMPT,
      "DEFAULT_CLAUDE_MODEL" => M::DEFAULT_CLAUDE_MODEL,
      "CLAUDE_MAX_TOKENS" => M::CLAUDE_MAX_TOKENS,
      "MODEL_FAMILIES" => M::MODEL_FAMILIES,
      "SVG_WIDTH" => M::SVG_WIDTH,
      "SVG_HEIGHT" => M::SVG_HEIGHT,
      "RETRO_PALETTES" => M::RETRO_PALETTES.map(&:dup),
      "COMPOSITION_VARIANTS" => M::COMPOSITION_VARIANTS,
      "ART_DIRECTOR_SYSTEM" => M::ART_DIRECTOR_SYSTEM,
      "REVIEWER_SYSTEM" => M::REVIEWER_SYSTEM,
      "PNG_SIGNATURE" => M::PNG_SIGNATURE.bytes,
      "POST_GENERATION_SLEEP" => M::POST_GENERATION_SLEEP,
      "OVERRIDE_KEYS" => M::OVERRIDE_KEYS
    }
  end

  def test_constants_match_oracle_byte_for_byte
    skip "python3 unavailable" unless python_available?

    out, status = Open3.capture2("python3", ORACLE)
    assert status.success?, "oracle dump failed: #{out}"
    python_table = JSON.parse(out)
    # Round-trip Ruby through JSON so the comparison is structural and encoding
    # is identical to what the oracle emitted (UTF-8, em-dashes and all).
    ruby_json = JSON.parse(JSON.generate(ruby_table))

    python_table.each do |key, value|
      assert_equal value, ruby_json[key], "constant #{key} diverged from oracle"
    end
    assert_equal python_table.keys.sort, ruby_json.keys.sort
  end

  # MODEL_FAMILIES iteration order is part of the contract (model_family returns
  # the FIRST matching prefix) — JSON object comparison above is order-blind, so
  # pin the order explicitly here.
  def test_model_families_order_preserved
    assert_equal %w[claude- gpt-image- dall-e- grok- stable- sd3 gemini- imagen-],
                 M::MODEL_FAMILIES.keys
  end

  def test_png_signature_bytes
    assert_equal [137, 80, 78, 71, 13, 10, 26, 10], M::PNG_SIGNATURE.bytes
    assert_equal Encoding::ASCII_8BIT, M::PNG_SIGNATURE.encoding
  end

  def test_post_generation_sleep_runtime_override
    # The oracle's POST_GENERATION_SLEEP is a rebindable module global the test
    # suite sets to 0; the constant stays immutable, the runtime value flexes.
    assert_in_delta 2.0, M.post_generation_sleep, 0.0
    M.post_generation_sleep = 0
    assert_equal 0, M.post_generation_sleep
  ensure
    M.post_generation_sleep = M::POST_GENERATION_SLEEP
  end
end
