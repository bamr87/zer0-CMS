# frozen_string_literal: true

require "test_helper"

class StudioRendererTest < ActiveSupport::TestCase
  test "every catalogued generator renders sanitized, linted SVG" do
    StudioCatalog.generators.each do |gen|
      seed = gen.knobs.find { |k| k.key == "seed" }&.default || 1
      result = StudioRenderer.new(generator: gen.key, seed: seed).render
      assert result.svg.start_with?("<svg"), "#{gen.key} produced non-SVG"
      assert_includes result.svg, "viewBox", "#{gen.key} missing viewBox (sanitizer contract)"
      assert result.meta[:seed].is_a?(Integer)
      assert result.lint.key?("clean")
    end
  end

  test "a banner slug derives its seed deterministically" do
    a = StudioRenderer.new(generator: "banner", slug: "hello-world").render
    b = StudioRenderer.new(generator: "banner", slug: "hello-world").render
    assert_equal a.svg, b.svg, "same slug must reproduce the same banner"
  end

  test "an unknown palette falls back rather than crashing the generator" do
    result = StudioRenderer.new(generator: "mandala", seed: 3, knobs: { "palette" => "not-a-palette" }).render
    assert result.svg.start_with?("<svg")
  end

  test "a non-integer seed is a clean error, not a 500" do
    assert_raises(StudioRenderer::Error) do
      StudioRenderer.new(generator: "mandala", seed: "abc").render
    end
  end

  test "unknown generator raises a handled error" do
    assert_raises(StudioRenderer::Error) do
      StudioRenderer.new(generator: "nope", seed: 1).render
    end
  end

  test "a leading-zero seed is decimal, not octal" do
    # Integer('010') is 8 in Ruby (octal); a user typing 010 means seed 10, and
    # the wrong reading would silently render different art.
    decimal = StudioRenderer.new(generator: "mandala", seed: "10").render
    padded  = StudioRenderer.new(generator: "mandala", seed: "010").render
    assert_equal decimal.svg, padded.svg
    assert_equal 10, padded.meta[:seed]
  end
end
