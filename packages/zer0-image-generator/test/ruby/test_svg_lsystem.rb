# frozen_string_literal: true

# Differential + golden test for the L-system generator.
#
#     ruby -Ilib test/ruby/test_svg_lsystem.rb
#
# The Python original (tools/svg/examples/lsystem.py) is the ORACLE: for a
# matrix of seed x species x palette x iters, its build() output must equal the
# Ruby port's byte-for-byte. Guarded to skip cleanly without python3. A second
# test pins the committed artwork under docs/samples exactly.

require "json"
require "open3"
require "minitest/autorun"
require_relative "../../lib/zer0_image_generator/svg/generators/lsystem"

class TestSvgLsystem < Minitest::Test
  REPO_ROOT = File.expand_path("../..", __dir__)
  GEN = Zer0ImageGenerator::Svg::Generators::Lsystem

  # `iters` may be null -> the oracle uses its ruleset default (build's
  # optional 4th arg). Framed as JSON so the (large) SVG text transports whole.
  DRIVER = <<~PYTHON
    import sys, os, json, importlib.util
    repo = sys.argv[1]
    path = os.path.join(repo, "tools", "svg", "examples", "lsystem.py")
    spec = importlib.util.spec_from_file_location("lsystem", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = []
    for seed, species, palette, iters in json.load(sys.stdin):
        out.append(mod.build(seed, species, palette, iters))
    sys.stdout.write(json.dumps(out))
  PYTHON

  def python3
    @python3 ||= [ENV["PYTHON3"], "python3", "python"].compact.find do |c|
      system(c, "-c", "import sys", out: File::NULL, err: File::NULL)
    end
  end

  def oracle(combos)
    stdout, stderr, status = Open3.capture3(
      python3, "-c", DRIVER, REPO_ROOT, stdin_data: JSON.dump(combos)
    )
    raise "lsystem oracle failed:\n#{stderr}" unless status.success?

    JSON.parse(stdout)
  end

  # [seed, species, palette, iters-or-nil]
  def matrix
    combos = []
    [1, 2, 3, 7].each do |seed|
      %w[bush fern tree weed].each do |species|
        %w[verdant autumn sakura frost].each do |palette|
          combos << [seed, species, palette, 3]
        end
      end
    end
    # iters variety, including the ruleset default (nil) and a low count
    combos << [7, "tree", "verdant", nil]
    combos << [4, "tree", "autumn", 4]
    combos << [5, "bush", "frost", 2]
    combos << [6, "fern", "sakura", 4]
    combos << [9, "weed", "verdant", 5]
    combos
  end

  def test_differential_matrix_byte_identical
    skip "python3 unavailable" unless python3

    combos = matrix
    expected = oracle(combos)
    combos.each_with_index do |(seed, species, palette, iters), i|
      got = GEN.build(seed, species, palette, iters)
      assert_equal expected[i], got,
                   "lsystem diverged at seed=#{seed} species=#{species} " \
                   "palette=#{palette} iters=#{iters.inspect}"
    end
    assert_operator combos.length, :>=, 40
  end

  # tree ruleset at iters 3 — the exact recipe recorded in docs/samples/README.
  GOLDENS = {
    "docs/samples/lsystem-tree-autumn-4.svg" => [4, "autumn"],
    "docs/samples/lsystem-tree-verdant-7.svg" => [7, "verdant"],
    "docs/samples/lsystem-tree-sakura-7.svg" => [7, "sakura"],
  }.freeze

  def test_committed_artwork_exact
    GOLDENS.each do |rel, (seed, palette)|
      want = File.binread(File.join(REPO_ROOT, rel))
      got = GEN.build(seed, "tree", palette, 3)
      assert_equal want, got, "lsystem #{rel} not reproduced byte-for-byte"
    end
  end
end
