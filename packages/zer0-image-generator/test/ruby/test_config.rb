# frozen_string_literal: true

# Tests for the config layer: apply_source_root, _load_dotenv, load_yaml_file,
# read_authors, find_project_root. Differential against the oracle where a
# python3 comparison adds signal; otherwise direct assertions ported from
# test/test_preview_generator.py.
#
#     ruby -Ilib test/ruby/test_config.rb

require "minitest/autorun"
require "json"
require "open3"
require "tmpdir"
require "fileutils"
require "pathname"
require_relative "../../lib/zer0_image_generator/config"

class TestApplySourceRoot < Minitest::Test
  M = Zer0ImageGenerator

  def test_source_reroots_content
    root = Pathname.new("/site")
    assert_equal root + "pages", M.apply_source_root(root, { "source" => "pages" })
  end

  def test_source_absent_or_dot_keeps_root
    root = Pathname.new("/site")
    assert_equal root, M.apply_source_root(root, {})
    assert_equal root, M.apply_source_root(root, { "source" => "" })
    assert_equal root, M.apply_source_root(root, { "source" => "." })
    assert_equal root, M.apply_source_root(root, { "source" => nil })
  end

  def test_source_strips_surrounding_slashes
    root = Pathname.new("/site")
    assert_equal root + "pages", M.apply_source_root(root, { "source" => "/pages/" })
  end
end

# Port of TestDotenv from test/test_preview_generator.py.
class TestDotenv < Minitest::Test
  M = Zer0ImageGenerator
  KEYS = %w[PG_TEST_A PG_TEST_B PG_TEST_C].freeze

  def load(content, pre_env)
    saved = KEYS.to_h { |k| [k, ENV[k]] }
    Dir.mktmpdir do |tmp|
      File.write(File.join(tmp, ".env"), content)
      KEYS.each { |k| ENV.delete(k) }
      pre_env.each { |k, v| ENV[k] = v }
      M._load_dotenv(tmp)
      KEYS.to_h { |k| [k, ENV[k]] }
    end
  ensure
    KEYS.each { |k| ENV.delete(k) }
    saved.each { |k, v| ENV[k] = v unless v.nil? }
  end

  def test_empty_env_var_does_not_shadow_dotenv
    result = load("PG_TEST_A=real-value\n", "PG_TEST_A" => "")
    assert_equal "real-value", result["PG_TEST_A"]
  end

  def test_nonempty_env_var_wins
    result = load("PG_TEST_A=file-value\n", "PG_TEST_A" => "env-value")
    assert_equal "env-value", result["PG_TEST_A"]
  end

  def test_inline_comment_and_quotes
    result = load(
      %(PG_TEST_A=sk-token  # prod key\nPG_TEST_B="quoted # not comment"\nPG_TEST_C='single'\n),
      {}
    )
    assert_equal "sk-token", result["PG_TEST_A"]
    assert_equal "quoted # not comment", result["PG_TEST_B"]
    assert_equal "single", result["PG_TEST_C"]
  end
end

class TestLoadYamlFile < Minitest::Test
  M = Zer0ImageGenerator

  def test_missing_file_is_empty_hash
    Dir.mktmpdir do |tmp|
      assert_equal({}, M.load_yaml_file(File.join(tmp, "nope.yml")))
    end
  end

  def test_non_mapping_yaml_is_empty_hash
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "list.yml")
      File.write(path, "- a\n- b\n")
      assert_equal({}, M.load_yaml_file(path))
    end
  end

  def test_reads_mapping
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "c.yml")
      File.write(path, "provider: openai\ncollections:\n  - posts\n  - docs\n")
      assert_equal({ "provider" => "openai", "collections" => %w[posts docs] },
                   M.load_yaml_file(path))
    end
  end

  def test_malformed_yaml_warns_and_returns_empty
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "bad.yml")
      File.write(path, "key: : : nope\n  bad indent\n")
      _out, err = capture_subprocess_io { assert_equal({}, M.load_yaml_file(path)) }
      assert_includes err, "Could not parse bad.yml"
    end
  end
end

# read_authors resolves relative to the project root and disables on empty.
class TestReadAuthors < Minitest::Test
  M = Zer0ImageGenerator

  def test_custom_path_and_disable
    Dir.mktmpdir do |tmp|
      Dir.mkdir(File.join(tmp, "team"))
      File.write(File.join(tmp, "team", "writers.yml"), "vega:\n  name: Vega\n")
      assert_equal({ "vega" => { "name" => "Vega" } }, M.read_authors(tmp, "team/writers.yml"))
      assert_equal({}, M.read_authors(tmp, ""))
      assert_equal({}, M.read_authors(tmp, "  "))
      # leading slash is stripped so the path stays root-relative
      assert_equal({ "vega" => { "name" => "Vega" } }, M.read_authors(tmp, "/team/writers.yml"))
    end
  end
end

class TestFindProjectRoot < Minitest::Test
  M = Zer0ImageGenerator

  def test_walks_up_from_cwd_to_config
    Dir.mktmpdir do |tmp|
      real = File.realpath(tmp)
      File.write(File.join(real, "_config.yml"), "title: T\n")
      nested = File.join(real, "a", "b")
      FileUtils.mkdir_p(nested)
      Dir.chdir(nested) do
        assert_equal Pathname.new(real), M.find_project_root
      end
    end
  end
end

# Differential: apply_source_root must agree with the oracle across shapes.
class TestApplySourceRootDifferential < Minitest::Test
  M = Zer0ImageGenerator

  def python_available?
    out, status = Open3.capture2e("python3", "--version")
    status.success? && !out.strip.empty?
  rescue StandardError
    false
  end

  ORACLE = File.expand_path("../../lib/zer0_image_generator/preview_generator.py", __dir__)

  # Reads the oracle path from argv[1] and the cases from stdin, so the probe
  # can live in a scratch dir without any relative-path assumptions.
  ORACLE_SNIPPET = <<~PY
    import importlib.util, json, sys
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("pg", sys.argv[1])
    pg = importlib.util.module_from_spec(spec); spec.loader.exec_module(pg)
    payload = json.load(sys.stdin)
    json.dump([str(pg.apply_source_root(Path(root), cfg)) for root, cfg in payload], sys.stdout)
  PY

  CASES = [
    ["/site", { "source" => "pages" }],
    ["/site", {}],
    ["/site", { "source" => "" }],
    ["/site", { "source" => "." }],
    ["/site", { "source" => nil }],
    ["/site", { "source" => "/pages/" }],
    ["/site/root", { "source" => "content/sub" }]
  ].freeze

  def test_matches_oracle
    skip "python3 unavailable" unless python_available?

    Dir.mktmpdir do |tmp|
      script = File.join(tmp, "probe.py")
      File.write(script, ORACLE_SNIPPET)
      out, status = Open3.capture2("python3", script, ORACLE, stdin_data: JSON.generate(CASES))
      assert status.success?, out
      python = JSON.parse(out)
      ruby = CASES.map { |root, cfg| M.apply_source_root(Pathname.new(root), cfg).to_s }
      assert_equal python, ruby
    end
  end
end
