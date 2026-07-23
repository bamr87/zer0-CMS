# frozen_string_literal: true

# Byte-identity tests for the invaders generator port.
#
#     ruby -Ilib test/ruby/test_invaders.rb
#
# invaders depends on the shared PixelKit slice. The test prefers the real
# lib/zer0_image_generator/svg/pixel_kit.rb when it is on disk (a true
# integration check); until that lands it falls back to the faithful in-tree
# stub so byte-identity can still be pinned. Either way the generator's own
# `require_relative "../pixel_kit"` is skipped because the constant is defined.

require "minitest/autorun"

SHARED_PIXEL_KIT = File.expand_path("../../lib/zer0_image_generator/svg/pixel_kit.rb", __dir__)
if File.exist?(SHARED_PIXEL_KIT)
  require SHARED_PIXEL_KIT
else
  require_relative "pixel_kit_stub"
end

require_relative "svg_oracle"
require_relative "../../lib/zer0_image_generator/svg/generators/invaders"

class TestInvaders < Minitest::Test
  GEN = Zer0ImageGenerator::Svg::Generators::Invaders
  REPO = File.expand_path("../..", __dir__)
  PALETTES = %w[cyanic magma moss dusk].freeze
  SEEDS = (0..12).to_a.freeze

  def combos
    SEEDS.product(PALETTES).map { |seed, palette| [seed, palette] }
  end

  def test_differential_matrix_matches_python
    skip "python3 unavailable" unless SvgOracle.available?

    cases = combos
    oracle = SvgOracle.run("invaders", cases)
    assert_equal cases.length, oracle.length
    cases.each_with_index do |(seed, palette), idx|
      assert_equal oracle[idx], GEN.build(seed, palette),
                   "invaders diverged from oracle at seed=#{seed} palette=#{palette}"
    end
    assert_operator cases.length, :>=, 40
  end

  def test_committed_samples_are_byte_identical
    {
      "docs/samples/invaders-magma-5.svg" => [5, "magma"],
      "docs/samples/invaders-cyanic-3.svg" => [3, "cyanic"],
      "docs/showcase/variants/invaders-dusk-3.svg" => [3, "dusk"],
    }.each do |rel, (seed, palette)|
      assert_equal File.read(File.join(REPO, rel)), GEN.build(seed, palette),
                   "#{rel} not reproduced"
    end
  end
end
