# frozen_string_literal: true

# The zer0-ui-tokens kit (web/app/assets/stylesheets/zer0-tokens.css) was split
# out of application.css, which still carries its own copy until the owner's
# in-flight edit to it lands. This pins the split: every custom property the
# kit declares must be declared with the same value in application.css, in the
# same context (the dark-first :root, or the prefers-color-scheme light :root),
# and the kit must stay a token layer — no component rules.
#
#     ruby -Ilib test/ruby/test_zer0_tokens.rb
#
# Stdlib only; no Rails, no browser.

require "minitest/autorun"

module CssBlocks
  module_function

  def strip_comments(css)
    css.gsub(%r{/\*.*?\*/}m, "")
  end

  # Top-level rules of one nesting level as [prelude, body] pairs.
  def rules(css)
    out = []
    depth = 0
    prelude_start = 0
    body_start = nil
    prelude = nil
    css.each_char.with_index do |char, index|
      case char
      when "{"
        if depth.zero?
          prelude = css[prelude_start...index].strip
          body_start = index + 1
        end
        depth += 1
      when "}"
        depth -= 1
        if depth.zero?
          out << [prelude, css[body_start...index]]
          prelude_start = index + 1
        end
      when ";"
        prelude_start = index + 1 if depth.zero? # a bare statement (@import ...;)
      end
    end
    raise "unbalanced braces" unless depth.zero?

    out
  end

  def declarations(body)
    body.split(";").each_with_object({}) do |decl, acc|
      name, value = decl.split(":", 2)
      next if value.nil?

      acc[name.strip] = value.strip.gsub(/\s+/, " ")
    end
  end

  # { [media_or_nil, selector] => { property => value } }, looking through
  # @layer blocks (a layer changes precedence, not what is declared).
  def contexts(css, media: nil, acc: {}, at_rules: [])
    rules(css).each do |prelude, body|
      if prelude.start_with?("@layer")
        at_rules << prelude
        contexts(body, media: media, acc: acc, at_rules: at_rules)
      elsif prelude.start_with?("@media")
        at_rules << prelude
        contexts(body, media: prelude, acc: acc, at_rules: at_rules)
      else
        (acc[[media, prelude]] ||= {}).update(declarations(body))
      end
    end
    acc
  end
end

class TestZer0Tokens < Minitest::Test
  STYLES = File.expand_path("../../web/app/assets/stylesheets", __dir__)
  TOKENS = File.join(STYLES, "zer0-tokens.css")
  APP = File.join(STYLES, "application.css")
  LIGHT = "@media (prefers-color-scheme: light)"

  def setup
    @tokens_raw = File.read(TOKENS)
    @at_rules = []
    @tokens = CssBlocks.contexts(CssBlocks.strip_comments(@tokens_raw), at_rules: @at_rules)
    @app = CssBlocks.contexts(CssBlocks.strip_comments(File.read(APP)))
  end

  def test_kit_stamp
    assert_match(/^ \* kit: zer0-ui-tokens \d+\.\d+\.\d+ — source of truth for every zer0 Rails panel; consumers vendor this file byte-identically$/,
                 @tokens_raw)
  end

  def test_kit_is_a_token_layer_only
    assert_equal [[nil, ":root"], [LIGHT, ":root"], [nil, "*"]].sort_by(&:to_s),
                 @tokens.keys.sort_by(&:to_s),
                 "zer0-tokens.css may hold only :root tokens, the light :root, and the * reset"
    assert_equal ["@layer zer0-tokens", LIGHT], @at_rules
    assert_equal({ "box-sizing" => "border-box" }, @tokens[[nil, "*"]])
  end

  def test_every_dark_token_matches_application_css
    assert_context_matches([nil, ":root"])
  end

  def test_every_light_token_matches_application_css
    assert_context_matches([LIGHT, ":root"])
  end

  def test_color_scheme_and_reset_match_application_css
    assert_equal @app.fetch([nil, ":root"])["color-scheme"], @tokens.fetch([nil, ":root"])["color-scheme"]
    assert_equal @app.fetch([nil, "*"]), @tokens.fetch([nil, "*"])
  end

  private

  def assert_context_matches(key)
    kit = @tokens.fetch(key).select { |name, _| name.start_with?("--") }
    app = @app.fetch(key) { flunk "application.css has no #{key.compact.join(' ')} block" }
    refute_empty kit
    kit.each do |name, value|
      assert app.key?(name), "#{name} (#{key.compact.join(' ')}) is not declared in application.css"
      assert_equal app[name], value,
                   "#{name} (#{key.compact.join(' ')}) drifted: application.css has #{app[name].inspect}, " \
                   "zer0-tokens.css has #{value.inspect} — update the kit (and bump its version) or finish the consolidation"
    end
  end
end
