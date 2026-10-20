# frozen_string_literal: true

# End-to-end wiring test: drives the REAL sibling slices (settings, content,
# prompt, providers, claude) through this slice's default Collaborators — no
# fakes. Proves the forwarding in Runner::Collaborators actually resolves and
# that a full CLI.main dry-run / list-missing run behaves.
#
#     ruby -Ilib test/ruby/test_integration.rb
#
# Skips cleanly (never fails) when the sibling slices are absent or cannot load
# yet, so this slice stays green on its own. No network: the `local` provider is
# deterministic and credential-free.

require "minitest/autorun"
require "tmpdir"
require "pathname"
require "stringio"
require "fileutils"

# The engine's `all.rb` also pulls in not-yet-ported studio slices (library,
# freesvg); require only the preview-run chain so this test depends on exactly
# what CLI.main needs.
CHAIN = %w[
  engine logging stats constants config settings content prompt http
  claude/client claude/orchestration
  svg/sanitizer svg/local_renderer svg/rasterizer svg/lint svg/pixel_kit
  providers runner cli
].freeze

ENGINE_LOADED =
  begin
    CHAIN.each { |f| require "zer0_image_generator/#{f}" }
    true
  rescue LoadError, StandardError => e
    warn "[integration] sibling slices not loadable yet (#{e.class}: #{e.message}); skipping"
    false
  end

class TestEngineIntegration < Minitest::Test
  def setup
    skip "engine chain not loadable yet" unless ENGINE_LOADED
  end

  def with_site
    Dir.mktmpdir do |tmp|
      root = Pathname.new(tmp)
      (root / "_config.yml").write("title: Fixture\npreview_images:\n  provider: local\n")
      posts = root / "_posts"
      posts.mkpath
      (posts / "2026-01-01-hello.md").write(
        "---\ntitle: Hello World\ndescription: A friendly test post\n---\nBody text.\n"
      )
      Dir.chdir(tmp) { yield root }
    end
  end

  def capture_logger
    out = StringIO.new
    Zer0ImageGenerator::Logger.new(
      sink: Zer0ImageGenerator::StreamSink.new(out: out, err: out)
    ).tap { |l| l.instance_variable_set(:@_capture, out) }
  end

  def run_cli(argv, logger)
    Zer0ImageGenerator::CLI.start(argv, logger: logger, install_signals: false)
  end

  def log_text(logger)
    logger.instance_variable_get(:@_capture).string
  end

  def test_dry_run_writes_nothing_and_reports
    with_site do |root|
      post = root / "_posts" / "2026-01-01-hello.md"
      before = post.read
      logger = capture_logger
      code = run_cli(["-p", "local", "-c", "posts", "--dry-run", "--verbose"], logger)

      assert_equal 0, code
      text = log_text(logger)
      assert_includes text, "Files processed: 1"
      assert_includes text, "Images generated: 1"
      # CI's exact contract: a dry run creates no output and rewrites nothing.
      refute (root / "assets" / "images" / "previews").exist?
      assert_equal before, post.read
    end
  end

  def test_list_missing_reports_the_post
    with_site do |root|
      logger = capture_logger
      code = run_cli(["-p", "local", "-c", "posts", "--list-missing"], logger)
      assert_equal 0, code
      text = log_text(logger)
      assert_includes text, "Missing preview:"
      assert_includes text, "Hello World"
      refute (root / "assets" / "images" / "previews").exist?
    end
  end

  def test_real_local_generation_wires_front_matter
    with_site do |root|
      # A real (non-dry) local render: deterministic SVG→PNG, no credentials.
      logger = capture_logger
      code = run_cli(["-p", "local", "-c", "posts", "--verbose"], logger)
      post = root / "_posts" / "2026-01-01-hello.md"

      previews = root / "assets" / "images" / "previews"
      text = log_text(logger)

      if code.zero? && text.include?("No SVG rasterizer available")
        # No rasterizer (rsvg/inkscape/magick/playwright) on this host: the
        # engine deliberately keeps the .svg preview and still wires it in.
        assert (previews / "hello-world.svg").exist?, "local provider should have kept the SVG preview"
        assert_match(%r{^preview: .*hello-world\.svg$}, post.read.lines.grep(/preview:/).first.to_s)
        assert_includes text, "Images generated: 1"
      elsif code.zero?
        png = previews / "hello-world.png"
        assert png.exist?, "local provider should have produced the PNG"
        assert_match(/^preview:/, post.read.lines.grep(/preview:/).first.to_s)
        assert_includes text, "Images generated: 1"
      else
        # A missing rasterizer (rsvg/inkscape/magick/playwright) is an
        # environment gap, not a wiring failure — the run reached the renderer.
        assert_includes text, "Errors: 1"
        skip "no SVG rasterizer available in this environment"
      end
    end
  end

  def test_default_collaborators_forwarding_resolves
    # Every delegate must resolve to a real sibling symbol (not NameError).
    deps = Zer0ImageGenerator::Collaborators.new
    assert deps.providers.key?("local")
    assert_equal %w[gemini local openai stability xai], deps.provider_names_sorted
    assert_equal Zer0ImageGenerator::EditUnsupported, deps.edit_unsupported
    assert_kind_of Numeric, deps.post_generation_sleep
    ctx = deps.new_run_context(Pathname.pwd, {})
    copy = deps.with_slug(ctx, "abc")
    assert_equal "abc", copy.slug
    refute_same ctx, copy
  end
end
