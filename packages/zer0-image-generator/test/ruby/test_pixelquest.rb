# frozen_string_literal: true

# Byte-identity tests for the pixelquest generator port.
#
#     ruby -Ilib test/ruby/test_pixelquest.rb
#
# See test_invaders.rb for the PixelKit real-vs-stub selection rationale.

require "minitest/autorun"

SHARED_PIXEL_KIT = File.expand_path("../../lib/zer0_image_generator/svg/pixel_kit.rb", __dir__)
if File.exist?(SHARED_PIXEL_KIT)
  require SHARED_PIXEL_KIT
else
  require_relative "pixel_kit_stub"
end

require_relative "svg_oracle"
require_relative "../../lib/zer0_image_generator/svg/generators/pixelquest"

class TestPixelQuest < Minitest::Test
  GEN = Zer0ImageGenerator::Svg::Generators::PixelQuest
  REPO = File.expand_path("../..", __dir__)
  PALETTES = %w[cyanic magma moss dusk].freeze
  SEEDS = (0..12).to_a.freeze

  def combos
    SEEDS.product(PALETTES).map { |seed, palette| [seed, palette] }
  end

  def test_differential_matrix_matches_python
    skip "python3 unavailable" unless SvgOracle.available?

    cases = combos
    oracle = SvgOracle.run("pixelquest", cases)
    assert_equal cases.length, oracle.length
    cases.each_with_index do |(seed, palette), idx|
      assert_equal oracle[idx], GEN.build(seed, palette),
                   "pixelquest diverged from oracle at seed=#{seed} palette=#{palette}"
    end
    assert_operator cases.length, :>=, 40
  end

  def test_committed_samples_are_byte_identical
    {
      "docs/samples/pixel-quest-dusk-7.svg" => [7, "dusk"],
      "docs/showcase/variants/pixel-quest-moss-7.svg" => [7, "moss"],
      "docs/showcase/variants/pixel-quest-cyanic-7.svg" => [7, "cyanic"],
    }.each do |rel, (seed, palette)|
      assert_equal File.read(File.join(REPO, rel)), GEN.build(seed, palette),
                   "#{rel} not reproduced"
    end
  end
end
