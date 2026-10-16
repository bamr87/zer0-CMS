# frozen_string_literal: true

# Differential + golden test for the low-poly generator.
#
#     ruby -Ilib test/ruby/test_svg_lowpoly.rb
#
# The Python original (tools/svg/examples/lowpoly.py) is the ORACLE: for a
# matrix of seed x palette x grid, its build() output must equal the Ruby
# port's byte-for-byte. This is the sharpest float test of the three: a 1-ULP
# miss in math.hypot or a wrong round() would flip a colour channel and the
# assert would catch it. Guarded to skip cleanly without python3. A second test
# pins the committed artwork under docs/samples exactly.

require "json"
require "open3"
require "minitest/autorun"
require_relative "../../lib/zer0_image_generator/svg/generators/lowpoly"

class TestSvgLowpoly < Minitest::Test
  REPO_ROOT = File.expand_path("../..", __dir__)
  GEN = Zer0ImageGenerator::Svg::Generators::Lowpoly

  DRIVER = <<~PYTHON
    import sys, os, json, importlib.util
    repo = sys.argv[1]
    path = os.path.join(repo, "tools", "svg", "examples", "lowpoly.py")
    spec = importlib.util.spec_from_file_location("lowpoly", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = []
    for seed, palette, cols, rows in json.load(sys.stdin):
        out.append(mod.build(seed, palette, cols, rows))
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
    raise "lowpoly oracle failed:\n#{stderr}" unless status.success?

    JSON.parse(stdout)
  end

  # [seed, palette, cols, rows]
  def matrix
    combos = []
    (0..11).each do |seed|
      %w[dusk cyanic moss ember].each do |palette|
        combos << [seed, palette, 16, 11]
      end
    end
    # grid-density variety (still hits the interior-jitter and diagonal split)
    combos << [5, "dusk", 10, 8]
    combos << [5, "cyanic", 24, 16]
    combos << [7, "moss", 8, 6]
    combos << [3, "ember", 20, 12]
    combos << [42, "dusk", 16, 11]
    combos << [100, "moss", 12, 9]
    combos
  end

  def test_differential_matrix_byte_identical
    skip "python3 unavailable" unless python3

    combos = matrix
    expected = oracle(combos)
    combos.each_with_index do |(seed, palette, cols, rows), i|
      got = GEN.build(seed, palette, cols, rows)
      assert_equal expected[i], got,
                   "lowpoly diverged at seed=#{seed} palette=#{palette} " \
                   "cols=#{cols} rows=#{rows}"
    end
    assert_operator combos.length, :>=, 40
  end

  GOLDENS = {
    "docs/samples/lowpoly-cyanic-5.svg" => [5, "cyanic"],
    "docs/samples/lowpoly-dusk-5.svg" => [5, "dusk"],
  }.freeze

  def test_committed_artwork_exact
    GOLDENS.each do |rel, (seed, palette)|
      want = File.binread(File.join(REPO_ROOT, rel))
      got = GEN.build(seed, palette, 16, 11)
      assert_equal want, got, "lowpoly #{rel} not reproduced byte-for-byte"
    end
  end
end
