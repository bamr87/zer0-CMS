# frozen_string_literal: true

require "minitest/autorun"
require "json"
require_relative "../../lib/zer0_cms/events"

# The event contracts from the experience plane's side (schemas/events/,
# M8): every example validates, the events this plane builds validate, a
# malformed one is refused, and the validator knows every keyword the shared
# schemas use — so it can never silently skip a rule. The content plane's
# side is content/tests/outbox/test_contracts.py.
class TestEventContracts < Minitest::Test
  E = Zer0Cms::Events
  DIR = E.schema_dir
  TYPES = %w[content.page.published content.suggestion.created agent.run.completed app.user.interaction].freeze

  def example(type)
    JSON.parse(File.read(File.join(DIR, "examples", "#{type}.json"), encoding: "UTF-8"))
  end

  def test_the_shared_schemas_are_where_this_plane_looks_for_them
    assert File.file?(File.join(DIR, "cloudevent.v1.json")), "no schemas at #{DIR}"
    TYPES.each { |t| assert File.file?(File.join(DIR, "#{t}.v1.json")), "no schema for #{t}" }
  end

  def test_every_example_validates
    TYPES.each { |t| assert_equal [], E.validate(example(t)), t }
  end

  def test_the_validator_knows_every_keyword_the_schemas_use
    Dir.glob(File.join(DIR, "*.json")).each do |path|
      used = E::Schema.keywords(JSON.parse(File.read(path, encoding: "UTF-8")))
      assert_empty used - E::Schema::KEYWORDS, "#{File.basename(path)} uses a keyword Events::Schema does not check"
    end
  end

  def test_an_interaction_this_plane_builds_validates_and_carries_the_trace
    trace = "4bf92f3577b34da6a3ce929d0e0e4736"
    env = E.interaction(anon_id: "a7c9e1f3b5d7", page_id: 42, session_page_ids: [17], trace_id: trace)
    assert_equal [], E.validate(env)
    assert_equal "zer0-cms/app", env["source"]
    assert_equal trace, E.trace_id(env)
  end

  def test_a_malformed_event_is_refused_with_the_reason
    env = E.interaction(anon_id: "short", page_id: 0, kind: "stare")
    errors = E.validate(env).join("; ")
    assert_match(/anon_id: is shorter than 8/, errors)
    assert_match(/page_id: is less than 1/, errors)
    assert_match(/kind: "stare" is not one of/, errors)
    bad = E.interaction(anon_id: "a7c9e1f3b5d7", page_id: 1).merge("source" => "elsewhere")
    assert_match(/source/, E.validate(bad).join)
  end

  def test_a_content_event_reads_back_with_its_trace
    published = example("content.page.published")
    assert_equal 42, published["data"]["page_id"]
    assert_equal "4bf92f3577b34da6a3ce929d0e0e4736", E.trace_id(published)
    published["data"].delete("content_hash")
    assert_match(/content_hash is required/, E.validate(published).join)
  end
end
