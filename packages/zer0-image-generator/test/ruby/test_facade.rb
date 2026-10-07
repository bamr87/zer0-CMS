# frozen_string_literal: true

# Zer0ImageGenerator::Facade — the stable, Rails-free API zer0-CMS calls.
#
#     ruby -Ilib test/ruby/test_facade.rb
#
# Runs over a scratch copy of test/fixture-site (the same site CI's integration
# job drives with `jekyll preview-images`), with the free deterministic `local`
# provider and `rasterizer: none`, so it needs no network, no API key, no
# Python and no rasterizer binary. The fixture itself is never written.

require "minitest/autorun"
require "tmpdir"
require "fileutils"
require "pathname"
require "stringio"

require "zer0_image_generator/facade"

class TestFacade < Minitest::Test
  F = Zer0ImageGenerator::Facade
  FIXTURE = File.expand_path("../fixture-site", __dir__)
  POST = "_posts/2026-01-01-hello-world.md"
  DOC = "_docs/getting-started.md"

  # Every process env var resolve_settings consults; cleared so a developer's
  # shell (AI_PROVIDER=openai, DRY_RUN=true, ...) cannot change the outcome.
  SETTINGS_ENV = %w[
    AI_PROVIDER IMAGE_MODEL IMAGE_SIZE IMAGE_QUALITY IMAGE_STYLE
    IMAGE_STYLE_MODIFIERS OUTPUT_DIR PROMPT_ENGINE REVIEW_ENGINE
    IMAGE_RASTERIZER MAX_PARALLEL DRY_RUN VERBOSE FORCE LIST_ONLY ENHANCE
    ENHANCE_MODEL ENHANCE_QUALITY ENHANCE_FIDELITY ENHANCE_FORMAT
  ].freeze

  def setup
    @saved_env = SETTINGS_ENV.to_h { |key| [key, ENV.delete(key)] }
    @saved_sleep = Zer0ImageGenerator.post_generation_sleep
    Zer0ImageGenerator.post_generation_sleep = 0
    # Slice-level messages go to the global logger; keep test output clean.
    @saved_logger = Zer0ImageGenerator::Logging.instance_variable_get(:@logger)
    @global_out = StringIO.new
    Zer0ImageGenerator::Logging.logger = Zer0ImageGenerator::Logger.new(
      sink: Zer0ImageGenerator::StreamSink.new(out: @global_out, err: @global_out)
    )
  end

  def teardown
    @saved_env.each { |key, value| value.nil? ? ENV.delete(key) : ENV[key] = value }
    Zer0ImageGenerator.post_generation_sleep = @saved_sleep
    Zer0ImageGenerator::Logging.logger = @saved_logger
  end

  # A scratch copy of the fixture site, SVG-only so no rasterizer is needed.
  def with_site
    Dir.mktmpdir do |tmp|
      site = File.join(tmp, "site")
      FileUtils.cp_r(FIXTURE, site)
      config = File.join(site, "_config.yml")
      text = File.read(config)
      patched = text.sub(/^preview_images:\n/, "preview_images:\n  rasterizer: none\n")
      refute_equal text, patched, "fixture _config.yml lost its preview_images: block"
      File.write(config, patched)
      yield Pathname.new(site)
    end
  end

  def snapshot(site)
    Dir.glob("**/*", File::FNM_DOTMATCH, base: site.to_s).sort.to_h do |rel|
      path = site / rel
      [rel, path.file? ? path.binread : :dir]
    end
  end

  # --- missing_previews --------------------------------------------------------

  def test_missing_previews_lists_the_fixture_in_run_order
    with_site do |site|
      missing = F.missing_previews(site.to_s)

      assert_equal [POST, DOC], missing.map(&:relative)
      assert_equal %w[posts docs], missing.map(&:collection)
      assert_equal ["Hello World", "Getting Started"], missing.map(&:title)
      assert_equal [nil, nil], missing.map(&:preview)
      assert(missing.all? { |entry| Pathname.new(entry.path).absolute? })
    end
  end

  # Parity pin: the facade must list exactly the files the engine's own
  # --list-missing run prints, so "missing" can never mean two things.
  def test_missing_previews_matches_runner_list_missing
    with_site do |site|
      File.write(site / "_docs" / "stale.md",
                 "---\ntitle: Stale\npreview: /images/previews/gone.png\n---\nBody\n")
      (site / "assets" / "images" / "previews").mkpath
      File.binwrite(site / "assets" / "images" / "previews" / "here.png", "\x89PNG\r\n\x1a\n".b)
      File.write(site / "_docs" / "done.md",
                 "---\ntitle: Done\npreview: /images/previews/here.png\n---\nBody\n")

      config = Zer0ImageGenerator.read_config(site)
      root = Zer0ImageGenerator.apply_source_root(site, config)
      settings = Zer0ImageGenerator.resolve_settings(
        Zer0ImageGenerator::Args.build(list_missing: true), config
      )
      out = StringIO.new
      logger = Zer0ImageGenerator::Logger.new(
        sink: Zer0ImageGenerator::StreamSink.new(out: out, err: StringIO.new)
      )
      Zer0ImageGenerator::Runner.new(
        settings, root,
        ctx: Zer0ImageGenerator::RunContext.new(project_root: root, env: {}),
        logger: logger
      ).run
      printed = out.string.gsub(/\e\[[0-9;]*m/, "").scan(/^Missing preview: (.+)$/).flatten

      facade = F.missing_previews(site.to_s)
      assert_equal printed, facade.map(&:path)
      assert_includes facade.map(&:relative), "_docs/stale.md"
      refute_includes facade.map(&:relative), "_docs/done.md"
      assert_equal "/images/previews/gone.png",
                   facade.find { |entry| entry.relative == "_docs/stale.md" }.preview
    end
  end

  def test_missing_previews_on_a_source_site_reports_site_relative_paths
    Dir.mktmpdir do |tmp|
      site = Pathname.new(tmp)
      (site / "_config.yml").write("source: pages\npreview_images:\n  provider: local\n")
      (site / "pages" / "_posts").mkpath
      (site / "pages" / "_posts" / "2026-02-02-x.md").write("---\ntitle: X Marks\n---\nBody\n")

      missing = F.missing_previews(site.to_s)
      assert_equal ["pages/_posts/2026-02-02-x.md"], missing.map(&:relative)
    end
  end

  # --- generate_one ------------------------------------------------------------

  def test_generate_one_dry_run_writes_nothing
    with_site do |site|
      before = snapshot(site)
      result = F.generate_one(site.to_s, POST, dry_run: true)

      assert_equal :would_generate, result.status
      assert result.ok?
      assert_equal "local", result.provider
      assert_equal (site / POST).to_s, result.file
      assert_equal 1, result.stats[:generated]
      assert_equal 0, result.exit_code
      assert_nil result.preview
      assert_equal before, snapshot(site), "a dry run must not touch the site"
    end
  end

  def test_generate_one_writes_the_preview_and_wires_front_matter
    with_site do |site|
      result = F.generate_one(site.to_s, POST)

      assert_equal :generated, result.status, result.error
      assert_equal "/images/previews/hello-world.svg", result.preview
      assert_equal (site / "assets/images/previews/hello-world.svg").realpath.to_s,
                   Pathname.new(result.image).realpath.to_s
      assert_includes (site / POST).read, "\npreview: /images/previews/hello-world.svg\n"
      assert_empty Dir.glob("**/*.bak", base: site.to_s), "no .bak may survive a write"
      assert(result.log.any? { |level, _| level == :success })

      # The file is no longer missing; the doc still is.
      assert_equal [DOC], F.missing_previews(site.to_s).map(&:relative)

      # Idempotent, exactly like a second `jekyll preview-images` run.
      again = F.generate_one(site.to_s, (site / POST).to_s)
      assert_equal :skipped, again.status
      assert_equal 1, again.stats[:skipped]
      assert_equal "/images/previews/hello-world.svg", again.preview
    end
  end

  def test_generate_one_resolves_source_relative_then_site_relative
    Dir.mktmpdir do |tmp|
      site = Pathname.new(tmp)
      (site / "_config.yml").write("source: pages\npreview_images:\n  provider: local\n")
      (site / "pages" / "_posts").mkpath
      post = site / "pages" / "_posts" / "2026-02-02-x.md"
      post.write("---\ntitle: X Marks\n---\nBody\n")

      %w[_posts/2026-02-02-x.md pages/_posts/2026-02-02-x.md].each do |given|
        result = F.generate_one(site.to_s, given, dry_run: true)
        assert_equal :would_generate, result.status, given
        assert_equal post.to_s, result.file, given
      end
    end
  end

  def test_missing_credential_is_an_error_result_not_a_raise
    with_site do |site|
      before = snapshot(site)
      result = F.generate_one(site.to_s, POST, provider: "openai", env: {})

      assert_equal :error, result.status
      refute result.ok?
      assert_equal 1, result.exit_code
      assert_includes result.error, "OPENAI_API_KEY"
      assert_equal before, snapshot(site), "a refused run must not touch the site"
    end
  end

  def test_unknown_provider_is_an_error_result
    with_site do |site|
      result = F.generate_one(site.to_s, POST, provider: "no-such-renderer")
      assert_equal :error, result.status
      assert_includes result.error, "Unknown AI provider: no-such-renderer"
    end
  end

  # --- confinement -------------------------------------------------------------

  def test_caller_errors_raise_facade_error
    assert_operator F::Error, :<, Zer0ImageGenerator::Error

    with_site do |site|
      outside = site.dirname / "outside.md"
      outside.write("---\ntitle: Outside\n---\n")

      assert_raises(F::Error) { F.missing_previews((site / "nope").to_s) }
      assert_raises(F::Error) { F.generate_one((site / "nope").to_s, POST) }
      assert_raises(F::Error) { F.generate_one(site.to_s, "_posts/absent.md") }
      assert_raises(F::Error) { F.generate_one(site.to_s, "") }
      assert_raises(F::Error) { F.generate_one(site.to_s, outside.to_s) }
      assert_raises(F::Error) { F.generate_one(site.to_s, "../outside.md") }

      File.symlink(outside.to_s, (site / "_posts" / "linked.md").to_s)
      assert_raises(F::Error) { F.generate_one(site.to_s, "_posts/linked.md") }
      refute_includes F.missing_previews(site.to_s).map(&:relative), "_posts/linked.md"
    end
  end

  def test_config_paths_that_escape_the_site_raise
    with_site do |site|
      config = site / "_config.yml"
      original = config.read

      config.write("source: ..\n#{original}")
      assert_raises(F::Error) { F.missing_previews(site.to_s) }
      assert_raises(F::Error) { F.generate_one(site.to_s, (site / POST).to_s, dry_run: true) }

      config.write("collections_dir: ../elsewhere\n#{original}")
      (site.dirname / "elsewhere" / "_posts").mkpath
      assert_raises(F::Error) { F.missing_previews(site.to_s) }

      config.write(original.sub("preview_images:\n", "preview_images:\n  output_dir: ../../escaped\n"))
      assert_raises(F::Error) { F.generate_one(site.to_s, POST, dry_run: true) }
      refute (site.dirname.dirname / "escaped").exist?
    end
  end
end
