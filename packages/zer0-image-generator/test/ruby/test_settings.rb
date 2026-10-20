# frozen_string_literal: true

# Differential + unit tests for the settings layer port.
#
#     ruby -Ilib test/ruby/test_settings.rb
#
# The differential half shells out to python3, feeds the SAME (args, config,
# env) to the real preview_generator.resolve_settings, and asserts every
# resolved Settings field is identical. It skips cleanly when python3 is
# unavailable, but here (python3 3.14.3) it must actually run and pass.

require "minitest/autorun"
require "json"
require "open3"
require_relative "../../lib/zer0_image_generator/settings"

module SettingsTestHelpers
  ORACLE = File.expand_path("resolve_oracle.py", __dir__)

  # Every environment variable resolve_settings consults. Cleared before each
  # case on BOTH sides so a stray host var can't skew the differential.
  RESOLVE_ENV_KEYS = %w[
    AI_PROVIDER IMAGE_MODEL IMAGE_SIZE IMAGE_QUALITY IMAGE_STYLE
    IMAGE_STYLE_MODIFIERS OUTPUT_DIR PROMPT_ENGINE REVIEW_ENGINE IMAGE_RASTERIZER MAX_PARALLEL
    DRY_RUN VERBOSE FORCE LIST_ONLY ENHANCE ENHANCE_MODEL ENHANCE_QUALITY
    ENHANCE_FIDELITY ENHANCE_FORMAT
  ].freeze

  def python_available?
    return @python_available unless @python_available.nil?

    out, status = Open3.capture2e("python3", "--version")
    @python_available = status.success? && !out.strip.empty?
  rescue StandardError
    @python_available = false
  end

  # Run the SAME resolution on both engines under an identical environment and
  # return [python_hash, ruby_hash] normalized through JSON for comparison.
  def resolve_both(args, config, env)
    payload = JSON.generate(args: args, config: config)

    child_env = {}
    RESOLVE_ENV_KEYS.each { |k| child_env[k] = nil } # unset in the child
    env.each { |k, v| child_env[k] = v }
    py_out, status = Open3.capture2(child_env, "python3", ORACLE, stdin_data: payload)
    raise "oracle failed: #{py_out}" unless status.success?

    python_hash = JSON.parse(py_out)

    ruby_hash = with_env(env) do
      settings = Zer0ImageGenerator.resolve_settings(args, config)
      JSON.parse(JSON.generate(settings.to_h))
    end
    [python_hash, ruby_hash]
  end

  # Snapshot the resolve-relevant env, clear it, apply `env`, run, then restore.
  def with_env(env)
    saved = RESOLVE_ENV_KEYS.to_h { |k| [k, ENV[k]] }
    RESOLVE_ENV_KEYS.each { |k| ENV.delete(k) }
    env.each { |k, v| ENV[k] = v }
    yield
  ensure
    RESOLVE_ENV_KEYS.each { |k| ENV.delete(k) }
    saved.each { |k, v| ENV[k] = v unless v.nil? }
  end
end

class TestResolveSettingsDifferential < Minitest::Test
  include SettingsTestHelpers

  SITE = {
    "provider" => "openai",
    "model" => "gpt-image-2",
    "style" => "config style",
    "output_dir" => "assets/images/previews",
    "enabled" => true,
    "collections" => %w[posts docs]
  }.freeze

  STYLES = {
    "hacks" => { "style" => "circuit-board blueprint", "size" => "1024x1024" },
    "docs" => { "style" => "clean isometric diagram", "style_modifiers" => "matte, technical" },
    "posts" => "not-a-dict"
  }.freeze

  # {name => [args, config, env]}
  CASES = {
    "empty" => [{}, {}, {}],
    "partial_config" => [{}, { "preview_images" => SITE }, {}],
    "config_wins_over_defaults" => [{}, { "preview_images" => SITE }, {}],
    "env_wins_over_config" => [{}, { "preview_images" => SITE },
                               { "AI_PROVIDER" => "xai", "IMAGE_STYLE" => "env style" }],
    "empty_env_does_not_win" => [{}, { "preview_images" => SITE },
                                 { "AI_PROVIDER" => "", "IMAGE_STYLE" => "" }],
    "cli_wins_over_env" => [{ provider: "local", style: "cli style" },
                            { "preview_images" => SITE },
                            { "AI_PROVIDER" => "xai", "IMAGE_STYLE" => "env style" }],
    "review_cli_override" => [{ review: "none" }, {}, {}],
    "collections_auto_map" => [
      {}, { "collections" => { "docs" => { "output" => true }, "notes" => {}, "posts" => {} },
           "preview_images" => { "collections" => "auto" } }, {}
    ],
    "collections_auto_in_list" => [
      {}, { "collections" => { "docs" => {} }, "preview_images" => { "collections" => ["auto"] } }, {}
    ],
    "collections_auto_no_map" => [{}, { "preview_images" => { "collections" => "auto" } }, {}],
    # str(c) over a list of YAML scalars: booleans/nil must stringify the
    # CPython way (True/False/None), not Ruby's (true/false/"").
    "collections_scalar_coercion" => [{}, { "preview_images" => { "collections" => [1, true, false, nil, "posts"] } }, {}],
    "quality_bool_config" => [{}, { "preview_images" => { "quality" => true } }, {}],
    "collections_dir_bool_config" => [{}, { "preview_images" => { "collections_dir" => true } }, {}],
    "collections_dir_jekyll_top_level" => [{}, { "collections_dir" => "pages" }, {}],
    "collections_dir_block_overrides" => [
      {}, { "collections_dir" => "pages", "preview_images" => { "collections_dir" => "content" } }, {}
    ],
    "collections_dir_cli_wins" => [{ collections_dir: "site" }, { "collections_dir" => "pages" }, {}],
    "collections_dir_strips_slashes" => [{ collections_dir: "/nested/dir/" }, {}, {}],
    "front_matter_key_config" => [{}, { "preview_images" => { "front_matter_key" => "image" } }, {}],
    "front_matter_key_cli" => [{ front_matter_key: "thumbnail" },
                               { "preview_images" => { "front_matter_key" => "image" } }, {}],
    "authors_file_config" => [{}, { "preview_images" => { "authors_file" => "team/writers.yml" } }, {}],
    "authors_file_disabled_cli" => [{ authors_file: "" },
                                    { "preview_images" => { "authors_file" => "team/writers.yml" } }, {}],
    "collection_styles_map" => [{}, { "preview_images" => { "collection_styles" => STYLES } }, {}],
    "collection_styles_not_a_map" => [{}, { "preview_images" => { "collection_styles" => ["hacks"] } }, {}],
    "claude_effort_empty" => [{}, { "preview_images" => { "claude_effort" => "" } }, {}],
    "claude_model_config" => [{}, { "preview_images" => { "claude_model" => "claude-opus-4-8" } }, {}],
    "env_parallel_numeric" => [{}, {}, { "MAX_PARALLEL" => "7" }],
    "env_parallel_non_numeric" => [{}, {}, { "MAX_PARALLEL" => "abc" }],
    "cli_parallel_wins" => [{ parallel: 2 }, {}, { "MAX_PARALLEL" => "7" }],
    "env_flags" => [{}, {}, { "DRY_RUN" => "true", "VERBOSE" => "true", "FORCE" => "true",
                             "LIST_ONLY" => "true", "ENHANCE" => "true" }],
    "enhance_env_and_defaults" => [{}, {}, { "ENHANCE_MODEL" => "gpt-image-9",
                                            "ENHANCE_QUALITY" => "high" }],
    "enhance_prompt_implies_enhance" => [{ enhance_prompt: "sharper" }, {}, {}],
    "assets_prefix_cli" => [{ assets_prefix: "/cdn" }, {}, {}],
    "no_auto_prefix" => [{ no_auto_prefix: true }, {}, {}],
    "auto_prefix_config_false" => [{}, { "preview_images" => { "auto_prefix" => false } }, {}],
    "enabled_false" => [{}, { "preview_images" => { "enabled" => false } }, {}],
    "size_quality_env" => [{}, {}, { "IMAGE_SIZE" => "1024x1024", "IMAGE_QUALITY" => "high" }],
    "provider_explicit_via_env" => [{}, {}, { "AI_PROVIDER" => "gemini" }],
    "rasterizer_config_svg_only" => [{}, { "preview_images" => { "rasterizer" => "none" } }, {}],
    "rasterizer_env_beats_config" => [{}, { "preview_images" => { "rasterizer" => "none" } },
                                     { "IMAGE_RASTERIZER" => "rsvg" }],
    "full_cli_surface" => [
      { provider: "stability", model: "sd3-large", style: "cli", output_dir: "out",
        prompt_engine: "template", review: "none", batch: 5, file: "x.md",
        collection: "docs", rasterizer: "rsvg" },
      { "preview_images" => SITE }, {}
    ]
  }.freeze

  def test_differential_matrix
    skip "python3 unavailable" unless python_available?

    CASES.each do |name, (args, config, env)|
      python_hash, ruby_hash = resolve_both(args, config, env)
      assert_equal python_hash, ruby_hash, "case #{name}: fields diverged"
    end
  end
end

# Direct ports of the resolve/override assertions from
# test/test_preview_generator.py — these need no python3.
class TestSettingsPortedAssertions < Minitest::Test
  include SettingsTestHelpers
  M = Zer0ImageGenerator

  SITE = TestResolveSettingsDifferential::SITE
  STYLES = TestResolveSettingsDifferential::STYLES

  def resolve(args, config, env = {})
    with_env(env) { M.resolve_settings(args, config) }
  end

  def test_config_wins_over_defaults
    s = resolve({}, { "preview_images" => SITE })
    assert_equal "openai", s.provider
    assert_equal "config style", s.style
    assert_equal %w[posts docs], s.collections
  end

  def test_env_wins_over_config
    s = resolve({}, { "preview_images" => SITE }, "AI_PROVIDER" => "xai", "IMAGE_STYLE" => "env style")
    assert_equal "xai", s.provider
    assert_equal "env style", s.style
  end

  def test_cli_wins_over_env
    s = resolve({ provider: "local", style: "cli style" }, { "preview_images" => SITE },
                "AI_PROVIDER" => "xai", "IMAGE_STYLE" => "env style")
    assert_equal "local", s.provider
    assert_equal "cli style", s.style
  end

  def test_empty_env_var_does_not_win
    # pick() skips an empty env value and falls to _config.yml.
    s = resolve({}, { "preview_images" => SITE }, "AI_PROVIDER" => "")
    assert_equal "openai", s.provider
  end

  def test_defaults_when_config_empty
    s = resolve({}, {})
    assert_equal "openai", s.provider
    assert_equal "claude", s.prompt_engine
    assert_equal "claude", s.review_engine
    assert_equal ["posts"], s.collections
    assert_equal "", s.collections_dir
    assert_equal "preview", s.front_matter_key
    assert_equal "_data/authors.yml", s.authors_file
    assert_equal "low", s.claude_effort
  end

  def test_review_engine_cli_overrides
    assert_equal "none", resolve({ review: "none" }, {}).review_engine
  end

  def test_rasterizer_defaults_to_auto
    assert_equal "auto", resolve({}, {}).rasterizer
  end

  # A site declares SVG-only once in _config.yml, not per invocation.
  def test_rasterizer_from_config_block
    config = { "preview_images" => { "rasterizer" => "none" } }
    assert_equal "none", resolve({}, config).rasterizer
  end

  def test_rasterizer_cli_beats_config
    config = { "preview_images" => { "rasterizer" => "none" } }
    assert_equal "magick", resolve({ rasterizer: "magick" }, config).rasterizer
  end

  def test_claude_effort_empty_string_disables
    assert_equal "low", resolve({}, {}).claude_effort
    assert_equal "", resolve({}, { "preview_images" => { "claude_effort" => "" } }).claude_effort
  end

  def test_collections_auto_discovers_from_jekyll_map
    config = { "collections" => { "docs" => { "output" => true }, "notes" => {}, "posts" => {} },
               "preview_images" => { "collections" => "auto" } }
    s = resolve({}, config)
    assert_equal "posts", s.collections[0]
    assert_equal %w[docs notes posts], s.collections.sort
    assert_equal 3, s.collections.length
  end

  def test_collections_auto_inside_list
    config = { "collections" => { "docs" => {} }, "preview_images" => { "collections" => ["auto"] } }
    assert_equal %w[posts docs], resolve({}, config).collections
  end

  def test_collections_auto_without_jekyll_map
    assert_equal ["posts"], resolve({}, { "preview_images" => { "collections" => "auto" } }).collections
  end

  def test_collections_dir_defaults_to_site_root
    assert_equal "", resolve({}, {}).collections_dir
  end

  def test_collections_dir_reads_jekyll_top_level
    assert_equal "pages", resolve({}, { "collections_dir" => "pages" }).collections_dir
  end

  def test_collections_dir_block_overrides_top_level
    config = { "collections_dir" => "pages", "preview_images" => { "collections_dir" => "content" } }
    assert_equal "content", resolve({}, config).collections_dir
  end

  def test_collections_dir_cli_wins
    assert_equal "site", resolve({ collections_dir: "site" }, { "collections_dir" => "pages" }).collections_dir
  end

  def test_front_matter_key_from_config_and_cli
    config = { "preview_images" => { "front_matter_key" => "image" } }
    assert_equal "image", resolve({}, config).front_matter_key
    assert_equal "thumbnail", resolve({ front_matter_key: "thumbnail" }, config).front_matter_key
  end

  def test_authors_file_configurable_and_disableable
    config = { "preview_images" => { "authors_file" => "team/writers.yml" } }
    assert_equal "team/writers.yml", resolve({}, config).authors_file
    assert_equal "", resolve({ authors_file: "" }, config).authors_file
  end

  def test_resolve_settings_reads_collection_styles_map
    s = resolve({}, { "preview_images" => { "collection_styles" => STYLES } })
    assert_equal STYLES, s.collection_styles
    dropped = resolve({}, { "preview_images" => { "collection_styles" => ["hacks"] } })
    assert_equal({}, dropped.collection_styles)
  end

  # -- override machinery ----------------------------------------------------

  def test_author_overrides_apply_on_top
    s = resolve({}, { "preview_images" => SITE })
    merged = M.apply_preview_overrides(s, "style" => "noir", "model" => "dall-e-3", "size" => "1024x1024")
    assert_equal "noir", merged.style
    assert_equal "dall-e-3", merged.model
    assert_equal "1024x1024", merged.size
    assert_equal s.output_dir, merged.output_dir
  end

  def test_apply_preview_overrides_empty_returns_same_object
    s = resolve({}, {})
    assert_same s, M.apply_preview_overrides(s)
    assert_same s, M.apply_preview_overrides(s, {}, {})
  end

  def test_author_beats_collection_beats_global
    s = resolve({}, { "preview_images" => {
                    "style" => "global-style",
                    "collection_styles" => { "docs" => { "style" => "docs-style", "size" => "1024x1024" } }
                  } })
    collection = M.collection_preview_overrides(s.collection_styles, "docs")
    author = { "style" => "author-style" }
    merged = M.apply_preview_overrides(s, collection, author)
    assert_equal "author-style", merged.style
    assert_equal "1024x1024", merged.size
    no_author = M.apply_preview_overrides(s, collection, {})
    assert_equal "docs-style", no_author.style
  end

  def test_collection_of_derives_from_path
    assert_equal "docs", M.collection_of("/site/pages/_docs/a.md")
    assert_equal "posts", M.collection_of("/site/pages/_posts/2026/b.md")
    assert_equal "", M.collection_of("/site/index.md")
  end

  def test_collection_overrides_looked_up_by_collection
    assert_equal({ "style" => "circuit-board blueprint", "size" => "1024x1024" },
                 M.collection_preview_overrides(STYLES, "hacks"))
    assert_equal({}, M.collection_preview_overrides(STYLES, "posts"))
    assert_equal({}, M.collection_preview_overrides(STYLES, "news"))
    assert_equal({}, M.collection_preview_overrides(STYLES, ""))
    assert_equal({}, M.collection_preview_overrides("nope", "hacks"))
  end

  def test_unknown_keys_filtered
    styles = { "docs" => { "style" => "x", "output_dir" => "evil", "enabled" => false } }
    assert_equal({ "style" => "x" }, M.collection_preview_overrides(styles, "docs"))
  end

  # -- model family / effective model ----------------------------------------

  StubProvider = Struct.new(:name, :default_model)

  def openai
    StubProvider.new("openai", "gpt-image-2")
  end

  def xai
    StubProvider.new("xai", "grok-2-image")
  end

  def test_model_family_detection
    assert_equal "claude", M.model_family("claude-opus-4-8")
    assert_equal "openai", M.model_family("gpt-image-2")
    assert_equal "openai", M.model_family("dall-e-3")
    assert_equal "xai", M.model_family("grok-2-image")
    assert_equal "gemini", M.model_family("gemini-2.5-flash-image")
    assert_nil M.model_family("mystery-model")
  end

  def test_foreign_family_model_falls_back
    s = Zer0ImageGenerator::Settings.new(model: "claude-opus-4-8")
    assert_equal "gpt-image-2", M.effective_model(s, openai)
  end

  def test_matching_family_kept
    s = Zer0ImageGenerator::Settings.new(model: "dall-e-3")
    assert_equal "dall-e-3", M.effective_model(s, openai)
  end

  def test_empty_model_uses_provider_default
    s = Zer0ImageGenerator::Settings.new(model: "")
    assert_equal "grok-2-image", M.effective_model(s, xai)
  end

  # file_preview_settings layers global → collection_styles[coll] → author,
  # keyed off the file's `_<collection>` ancestor and its `author:` value.
  # `cf` is any object exposing `path` and `author` (the ContentFile Struct).
  Cf = Struct.new(:path, :author)

  def test_file_preview_settings_layers_collection_then_author
    s = resolve({}, { "preview_images" => {
                    "style" => "global",
                    "collection_styles" => { "docs" => { "style" => "docs-style", "size" => "1024x1024" } }
                  } })
    authors = { "vega" => { "preview" => { "style" => "author-style" } } }
    # In a _docs collection, authored by vega: author style wins, collection size kept.
    cf = Cf.new("/site/_docs/a.md", "vega")
    out = capture_io { @result = M.file_preview_settings(s, cf, authors) }
    assert_equal "author-style", @result.style
    assert_equal "1024x1024", @result.size
    # A file outside any collection with no author override keeps globals.
    plain = M.file_preview_settings(s, Cf.new("/site/index.md", nil), authors)
    assert_equal "global", plain.style
    assert_equal s.size, plain.size
  end
end

# Author-override + collection-style behaviors that touch read_authors and the
# YAML folded-scalar parsing (ported from test_preview_generator.py).
class TestAuthorOverrides < Minitest::Test
  M = Zer0ImageGenerator
  require "tmpdir"

  AUTHORS_YAML = <<~YAML
    cassandra:
      name: Cassandra
      preview:
        style: >-
          noir graphic-novel,
          high-contrast ink
    vega:
      preview:
        style: isometric 3D infographic
  YAML

  def test_authors_yaml_folded_scalars
    Dir.mktmpdir do |tmp|
      Dir.mkdir(File.join(tmp, "team"))
      File.write(File.join(tmp, "team", "writers.yml"), AUTHORS_YAML)
      authors = M.read_authors(tmp, "team/writers.yml")
      overrides = M.author_preview_overrides(authors, "cassandra")
      assert_includes overrides["style"], "noir graphic-novel"
      refute_includes overrides["style"], "\n"
      vega = M.author_preview_overrides(authors, "vega")
      assert_includes vega["style"], "isometric 3D infographic"
    end
  end

  def test_authors_file_empty_disables
    Dir.mktmpdir do |tmp|
      assert_equal({}, M.read_authors(tmp, ""))
      assert_equal({}, M.read_authors(tmp, "  "))
    end
  end

  def test_authors_file_missing_is_graceful
    Dir.mktmpdir do |tmp|
      assert_equal({}, M.read_authors(tmp, "_data/authors.yml"))
    end
  end

  def test_non_string_author_keys
    authors = { "a" => { "preview" => { "style" => "s" } } }
    assert_equal({}, M.author_preview_overrides(authors, %w[a b]))
    assert_equal({}, M.author_preview_overrides(authors, { "name" => "x" }))
    assert_equal({}, M.author_preview_overrides(authors, nil))
    assert_equal({}, M.author_preview_overrides(authors, "missing"))
  end
end
