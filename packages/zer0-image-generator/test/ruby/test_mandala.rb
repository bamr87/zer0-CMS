# frozen_string_literal: true

# Byte-identity tests for the mandala generator port.
#
#     ruby -Ilib test/ruby/test_mandala.rb
#
# Differential half shells out to the Python oracle (skipped if python3 is
# absent); the golden half pins the committed sample SVGs and needs no python.

require "minitest/autorun"
require_relative "svg_oracle"
require_relative "../../lib/zer0_image_generator/svg/generators/mandala"

class TestMandala < Minitest::Test
  GEN = Zer0ImageGenerator::Svg::Generators::Mandala
  REPO = File.expand_path("../..", __dir__)
  PALETTES = %w[jewel solar ocean rose].freeze
  SEEDS = (0..14).to_a.freeze

  def combos
    SEEDS.product(PALETTES).map { |seed, palette| [seed, palette] }
  end

  def test_differential_matrix_matches_python
    skip "python3 unavailable" unless SvgOracle.available?

    cases = combos
    oracle = SvgOracle.run("mandala", cases)
    assert_equal cases.length, oracle.length
    cases.each_with_index do |(seed, palette), idx|
      assert_equal oracle[idx], GEN.build(seed, palette),
                   "mandala diverged from oracle at seed=#{seed} palette=#{palette}"
    end
    assert_operator cases.length, :>=, 40
  end

  def test_committed_samples_are_byte_identical
    {
      "docs/samples/mandala-jewel-11.svg" => [11, "jewel"],
      "docs/samples/mandala-ocean-11.svg" => [11, "ocean"],
    }.each do |rel, (seed, palette)|
      assert_equal File.read(File.join(REPO, rel)), GEN.build(seed, palette),
                   "#{rel} not reproduced"
    end
  end
end
