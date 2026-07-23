# frozen_string_literal: true

# Argument-parsing + validate_credentials tests for the ported CLI.
#
#     ruby -Ilib test/ruby/test_cli.rb
#
# The TestArgparseDifferential group shells out to python3 to prove the Ruby
# parse_args produces the exact same namespace as the oracle's argparse; it
# skips cleanly when python3/PyYAML is unavailable.

require "minitest/autorun"
require "json"
require "stringio"
require "tempfile"

require "zer0_image_generator/cli"
require_relative "fakes"

include Zer0ImageGenerator

REPO_ROOT = File.expand_path("../..", __dir__)

def silent_logger
  Zer0ImageGenerator::Logger.new(
    sink: Zer0ImageGenerator::StreamSink.new(out: StringIO.new, err: StringIO.new)
  )
end

class TestFlagSurface < Minitest::Test
  # Golden test: every invocation used by the Rakefile and VS Code tasks must
  # keep parsing. Breaking any of these breaks rake preview:* / tasks.
  GOLDEN = [
    ["--list-missing"],
    ["--dry-run", "--verbose"],
    ["--verbose"],
    ["--collection", "posts", "--verbose"],
    ["--collection", "docs", "--verbose"],
    ["--force", "--verbose"],
    ["--file", "pages/_posts/example.md", "--verbose"],
    ["--collection", "posts"],
    ["--collection", "all"],
    ["-d"], ["-v"], ["-f", "x.md"], ["-c", "posts"], ["-p", "openai"],
    ["--output-dir", "assets/images/previews"],
    ["-j", "4"], ["-e"],
    ["--enhance-prompt", "fix it"],
    ["--enhance-model", "gpt-image-2"],
    ["--enhance-fidelity", "high"],
    ["--enhance-format", "png"],
    ["-p", "local"], ["-p", "gemini"],
    ["--prompt-engine", "claude"], ["--prompt-engine", "template"],
    ["--review", "claude"], ["--review", "none"],
    ["--rasterizer", "none"],
    ["-w", "2"],
    ["--rate-limit", "5"],
    ["--collections-dir", "pages"],
    ["--front-matter-key", "image"],
    ["--authors-file", "_data/people.yml"],
    ["--authors-file", ""]
  ].freeze

  def test_golden_invocations_parse
    GOLDEN.each do |argv|
      CLI.parse_args(argv) # must not raise
    end
  end

  def test_enhance_implication_rules
    # --enhance-prompt / -fidelity / -format imply --enhance…
    assert CLI.parse_args(["--enhance-prompt", "x"]).enhance
    assert CLI.parse_args(["--enhance-fidelity", "low"]).enhance
    assert CLI.parse_args(["--enhance-format", "webp"]).enhance
    # …but --enhance-model does NOT (historical behavior).
    refute CLI.parse_args(["--enhance-model", "gpt-image-2"]).enhance
  end

  def test_defaults
    a = CLI.parse_args([])
    assert_nil a.parallel        # → resolve_settings falls back to 4
    assert_equal 0, a.batch
    refute a.dry_run
    assert_nil a.provider
    assert_nil a.authors_file
  end

  def test_empty_authors_file_is_distinct_from_nil
    # resolve_settings distinguishes '' (disable) from absent; keep them apart.
    assert_equal "", CLI.parse_args(["--authors-file", ""]).authors_file
    assert_nil CLI.parse_args([]).authors_file
  end
end

class TestExitCodes < Minitest::Test
  def assert_exit(status, argv)
    err = assert_raises(Zer0ImageGenerator::ExitError) { CLI.parse_args(argv) }
    assert_equal status, err.status
  end

  def capture_stderr
    orig = $stderr
    $stderr = StringIO.new
    yield
  ensure
    $stderr = orig
  end

  def test_invalid_choice_exits_2
    capture_stderr { assert_exit(2, ["-p", "bogus"]) }
    capture_stderr { assert_exit(2, ["--review", "maybe"]) }
    capture_stderr { assert_exit(2, ["--enhance-format", "gif"]) }
  end

  def test_unknown_flag_exits_2
    capture_stderr { assert_exit(2, ["--nope"]) }
  end

  def test_positional_args_exit_2
    capture_stderr { assert_exit(2, ["extra"]) }
  end

  def test_bad_integer_exits_2
    capture_stderr { assert_exit(2, ["--batch", "abc"]) }
    capture_stderr { assert_exit(2, ["-j", "x"]) }
  end

  def test_help_exits_0
    out = StringIO.new
    orig = $stdout
    $stdout = out
    begin
      err = assert_raises(Zer0ImageGenerator::ExitError) { CLI.parse_args(["--help"]) }
      assert_equal 0, err.status
    ensure
      $stdout = orig
    end
    assert_match(/usage:/, out.string)
  end

  def test_provider_value_not_prefix_matched
    # argparse never abbreviates a choice value; 'open' is NOT 'openai'.
    capture_stderr { assert_exit(2, ["-p", "open"]) }
  end
end

class TestValidateCredentials < Minitest::Test
  def deps_with(providers)
    d = Fakes::Deps.new(providers: providers)
    d
  end

  def test_unknown_provider_errors_even_in_dry_run
    settings = Fakes.settings(provider: "bogus", dry_run: true)
    ctx = Fakes::Ctx.new(env: {})
    err = assert_raises(Zer0ImageGenerator::ExitError) do
      CLI.validate_credentials(settings, ctx, deps: deps_with({}), logger: silent_logger)
    end
    assert_equal 1, err.status
  end

  def test_known_provider_skips_credential_check_in_dry_run
    prov = Fakes::Provider.new(name: "openai", configured: false)
    settings = Fakes.settings(provider: "openai", dry_run: true)
    ctx = Fakes::Ctx.new(env: {})
    # Must not raise despite the provider being unconfigured.
    CLI.validate_credentials(settings, ctx,
                             deps: deps_with("openai" => prov), logger: silent_logger)
  end

  def test_local_provider_needs_no_key
    prov = Fakes::Provider.new(name: "local", configured: false)
    settings = Fakes.settings(provider: "local", dry_run: false, list_only: false)
    ctx = Fakes::Ctx.new(env: {})
    CLI.validate_credentials(settings, ctx,
                             deps: deps_with("local" => prov), logger: silent_logger)
  end

  def test_unconfigured_provider_errors_in_generate_mode
    prov = Fakes::Provider.new(name: "openai", configured: false,
                               missing_hint: "need OPENAI_API_KEY")
    settings = Fakes.settings(provider: "openai", dry_run: false, list_only: false)
    ctx = Fakes::Ctx.new(env: {})
    err = assert_raises(Zer0ImageGenerator::ExitError) do
      CLI.validate_credentials(settings, ctx,
                               deps: deps_with("openai" => prov), logger: silent_logger)
    end
    assert_equal 1, err.status
  end
end

class TestArgparseDifferential < Minitest::Test
  ORACLE = File.join(REPO_ROOT, "lib", "zer0_image_generator", "preview_generator.py")

  def python_available?
    system("python3", "-c", "import yaml", out: File::NULL, err: File::NULL)
  end

  def setup
    skip "python3 + PyYAML not available" unless python_available?

    @helper = Tempfile.new(["pyparse", ".py"])
    @helper.write(<<~PY)
      import sys, json
      sys.path.insert(0, #{File.dirname(ORACLE).inspect})
      import preview_generator as pg
      print(json.dumps(vars(pg.parse_args(sys.argv[1:]))))
    PY
    @helper.close
  end

  def teardown
    @helper&.unlink
  end

  def python_parse(argv)
    out = IO.popen(["python3", @helper.path, *argv], &:read)
    return nil unless $?.success?

    JSON.parse(out)
  end

  def test_namespace_matches_oracle_across_golden
    TestFlagSurface::GOLDEN.each do |argv|
      py = python_parse(argv)
      next if py.nil?

      rb = CLI.parse_args(argv).to_h_sorted
      assert_equal py, rb, "namespace differs for #{argv.inspect}"
    end
  end
end
