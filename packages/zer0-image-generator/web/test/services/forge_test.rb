# frozen_string_literal: true

require "test_helper"

class ForgeTest < ActiveSupport::TestCase
  # Exercises the pipeline with the deterministic local renderer (no network),
  # which is the same path the Claude/OpenAI providers take minus the API calls.

  def composition(**attrs)
    Composition.create!({
      title: "Test scene", brief: "A calm mountain lake at dusk.",
      provider: "local", prompt_engine: "template", review_engine: "none",
      style: "retro pixel art"
    }.merge(attrs))
  end

  test "compose renders an image and records a version" do
    c = composition
    images = Forge.new.compose(c)
    assert_equal 1, images.size
    img = images.first
    assert_equal "render", img.stage
    assert_equal "local", img.vendor
    assert img.exists?, "the rendered file should be on disk"
    assert_operator img.byte_size, :>, 0
  ensure
    c&.destroy
  end

  test "a local render is never tagged claude-directed" do
    # Even with prompt_engine=claude, local is deterministic and skips Claude,
    # so the version must not claim Claude wrote its brief.
    c = composition(prompt_engine: "claude")
    img = Forge.new(env: {}).compose(c).first
    refute img.claude_directed?, "local render must not be claude-directed"
  ensure
    c&.destroy
  end

  test "the local provider ignores Claude even when the pipeline asks for it" do
    # local is deterministic, so orchestration is skipped — no credential needed.
    c = composition(prompt_engine: "claude", review_engine: "claude")
    lines = []
    images = Forge.new(env: {}, logger: ->(m) { lines << m }).compose(c)
    assert_equal 1, images.size
    assert(lines.any? { |l| l.include?("template prompt") }, "expected a template-prompt log line, got: #{lines.inspect}")
  ensure
    c&.destroy
  end

  test "enhance without an OpenAI key fails cleanly, not with a 500" do
    c = composition
    img = Forge.new.compose(c).first
    error = assert_raises(Forge::Error) { Forge.new(env: {}).enhance(img) }
    assert_match(/OpenAI is not configured/, error.message)
  ensure
    c&.destroy
  end

  test "each version gets a distinct, ordered file" do
    c = composition
    Forge.new.compose(c)
    Forge.new.compose(c)
    paths = c.images.ordered.map(&:path)
    assert_equal paths.uniq, paths, "versions must not clobber each other"
  ensure
    c&.destroy
  end
end
