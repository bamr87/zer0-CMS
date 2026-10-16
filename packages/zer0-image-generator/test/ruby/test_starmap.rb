# frozen_string_literal: true

# Byte-identity tests for the starmap generator port.
#
#     ruby -Ilib test/ruby/test_starmap.rb
#
# starmap has no palette knob, so the matrix is over seeds alone (50 of them).
# The differential half also transitively proves that the library-icon inlining
# and low-poly facet shading match the oracle for every seed.

require "minitest/autorun"
require_relative "svg_oracle"
require_relative "../../lib/zer0_image_generator/svg/generators/starmap"

class TestStarmap < Minitest::Test
  GEN = Zer0ImageGenerator::Svg::Generators::Starmap
  REPO = File.expand_path("../..", __dir__)
  SEEDS = (0..49).to_a.freeze

  def test_differential_matrix_matches_python
    skip "python3 unavailable" unless SvgOracle.available?

    cases = SEEDS.map { |seed| [seed, nil] }
    oracle = SvgOracle.run("starmap", cases)
    assert_equal cases.length, oracle.length
    cases.each_with_index do |(seed, _), idx|
      assert_equal oracle[idx], GEN.build(seed),
                   "starmap diverged from oracle at seed=#{seed}"
    end
    assert_operator cases.length, :>=, 40
  end

  def test_committed_sample_is_byte_identical
    assert_equal File.read(File.join(REPO, "docs/samples/starmap-5.svg")),
                 GEN.build(5), "docs/samples/starmap-5.svg not reproduced"
  end
end
