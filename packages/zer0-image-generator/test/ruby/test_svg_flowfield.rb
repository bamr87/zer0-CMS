# frozen_string_literal: true

# Differential + golden test for the flow-field generator.
#
#     ruby -Ilib test/ruby/test_svg_flowfield.rb
#
# The Python original (tools/svg/examples/flowfield.py) is the ORACLE: for a
# matrix of seed x palette x knobs, its build() output must equal the Ruby
# port's byte-for-byte. Guarded to skip cleanly without python3, but where
# python3 is present it actually runs. A second test pins the committed
# artwork under docs/ exactly.

require "json"
require "open3"
require "minitest/autorun"
require_relative "../../lib/zer0_image_generator/svg/generators/flowfield"

class TestSvgFlowfield < Minitest::Test
  REPO_ROOT = File.expand_path("../..", __dir__)
  GEN = Zer0ImageGenerator::Svg::Generators::Flowfield

  # Load the oracle by file path (mirrors the CLI import) and emit build()
  # output for each combo as JSON so SVG text survives transport unaltered.
  DRIVER = <<~PYTHON
    import sys, os, json, importlib.util
    repo = sys.argv[1]
    path = os.path.join(repo, "tools", "svg", "examples", "flowfield.py")
    spec = importlib.util.spec_from_file_location("flowfield", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = []
    for seed, palette, w, h, lines, steps, scale in json.load(sys.stdin):
        out.append(mod.build(seed, w, h, lines, steps, scale, palette))
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
    raise "flowfield oracle failed:\n#{stderr}" unless status.success?

    JSON.parse(stdout)
  end

  # [seed, palette, width, height, lines, steps, scale]
  def matrix
    combos = []
    (0..15).each do |seed|
      %w[ember cyanic moss].each do |palette|
        combos << [seed, palette, 800, 800, 240, 70, 180.0]
      end
    end
    # exercise the knobs, not just seed/palette
    combos << [3, "cyanic", 600, 900, 120, 40, 90.0]
    combos << [4, "moss", 1000, 500, 300, 100, 240.0]
    combos << [8, "ember", 800, 800, 50, 20, 60.0]
    combos << [11, "moss", 400, 400, 180, 55, 120.0]
    combos << [21, "cyanic", 1200, 400, 400, 80, 300.0]
    combos << [99, "ember", 800, 800, 240, 70, 180.0]
    combos
  end

  def test_differential_matrix_byte_identical
    skip "python3 unavailable" unless python3

    combos = matrix
    expected = oracle(combos)
    combos.each_with_index do |(seed, palette, w, h, lines, steps, scale), i|
      got = GEN.build(seed, w, h, lines, steps, scale, palette)
      assert_equal expected[i], got,
                   "flowfield diverged at seed=#{seed} palette=#{palette} " \
                   "w=#{w} h=#{h} lines=#{lines} steps=#{steps} scale=#{scale}"
    end
    assert_operator combos.length, :>=, 40
  end

  # Regenerate the committed pieces from the args encoded in their filenames
  # (default knobs) and assert exact bytes.
  GOLDENS = {
    "docs/samples/flowfield-moss-5.svg" => [5, "moss"],
    "docs/showcase/variants/flowfield-moss-2.svg" => [2, "moss"],
    "docs/showcase/variants/flowfield-moss-9.svg" => [9, "moss"],
  }.freeze

  def test_committed_artwork_exact
    GOLDENS.each do |rel, (seed, palette)|
      want = File.binread(File.join(REPO_ROOT, rel))
      got = GEN.build(seed, 800, 800, 240, 70, 180.0, palette)
      assert_equal want, got, "flowfield #{rel} not reproduced byte-for-byte"
    end
  end
end
