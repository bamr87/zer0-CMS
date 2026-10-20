# frozen_string_literal: true

# Unit tests for the ABC style-pack plugin.
#
#     ruby -Ilib test/ruby/test_abc_style_pack.rb
#
# Pure-Ruby, zero network: the plugin never touches the byte-identity engine
# port, so these run standalone and guard the shared art-style contract.

require "minitest/autorun"
require "tmpdir"
require "fileutils"
require_relative "../../lib/zer0_image_generator/abc"

class TestAbcStylePack < Minitest::Test
  def setup
    @pack = Zer0ImageGenerator::Abc::StylePack.default
  end

  def test_catalog_loads_the_default_styles
    assert_includes @pack.style_ids, "isometric-tech-toy"
    assert_operator @pack.style_ids.length, :>=, 6
    # ids come back sorted for stable menus
    assert_equal @pack.style_ids.sort, @pack.style_ids
  end

  def test_unknown_style_raises_with_a_helpful_message
    err = assert_raises(Zer0ImageGenerator::Abc::UnknownStyle) do
      @pack.render_prompt(letter: "A", word: "Automation",
                          subject: "a robot arm", style: "does-not-exist")
    end
    assert_match(/unknown ABC art style/, err.message)
  end

  def test_render_prompt_is_single_line_text_free_and_mentions_the_word
    prompt = @pack.render_prompt(
      letter: "A", word: "Automation",
      subject: "a friendly robot arm stacking blocks",
      style: "isometric-tech-toy"
    )
    refute_includes prompt, "\n"
    assert_match(/isometric toy-technology/, prompt)
    assert_match(/AUTOMATION/, prompt)
    assert_match(/no text/i, prompt) # the safety contract
    # the style's default palette (cool-tech) is applied when none is given
    assert_match(/sky blue/, prompt)
  end

  def test_render_prompt_is_deterministic
    args = { letter: "C", word: "Cloud", subject: "a smiling cloud",
             style: "chalkboard-doodle", palette: "bright-primary", mood: "calm" }
    assert_equal @pack.render_prompt(**args), @pack.render_prompt(**args)
  end

  def test_palette_override_beats_the_style_default
    prompt = @pack.render_prompt(
      letter: "S", word: "Server", subject: "a tower of blinking lights",
      style: "isometric-tech-toy", palette: "warm-earth"
    )
    assert_match(/terracotta/, prompt)
    refute_match(/sky blue/, prompt)
  end

  def test_to_menu_exposes_styles_and_options
    menu = @pack.to_menu
    assert_equal @pack.style_ids.length, menu["styles"].length
    assert(menu["palettes"].any? { |p| p["id"] == "cool-tech" })
    assert(menu["moods"].any? { |m| m["id"] == "playful" })
  end

  def test_compose_prompts_fills_only_missing_prompts
    book = {
      "art_style" => "crayon-primary",
      "alphabet" => [
        { "letter" => "A", "word" => "Apple", "subject" => "a red apple" },
        { "letter" => "B", "word" => "Ball", "subject" => "a bouncy ball",
          "prompt" => "HAND AUTHORED — keep me" }
      ]
    }
    out = Zer0ImageGenerator::Abc::Plugin.compose_prompts(book)
    assert_match(/crayon drawing/, out["alphabet"][0]["prompt"])
    assert_equal "HAND AUTHORED — keep me", out["alphabet"][1]["prompt"]
    # original is not mutated
    assert_nil book["alphabet"][0]["prompt"]
  end

  def test_build_plan_skips_existing_images_and_resolves_paths
    Dir.mktmpdir do |root|
      FileUtils.mkdir_p(File.join(root, "assets/images/books/x"))
      # A already rendered; B still missing.
      File.write(File.join(root, "assets/images/books/x/a.png"), "png")
      book = {
        "art_style" => "isometric-tech-toy",
        "alphabet" => [
          { "letter" => "A", "word" => "Automation", "subject" => "robot",
            "image" => "/assets/images/books/x/a.png" },
          { "letter" => "B", "word" => "Backup", "subject" => "two copies",
            "image" => "/assets/images/books/x/b.png" }
        ]
      }
      plan = Zer0ImageGenerator::Abc::Plugin.build_plan(book, root: root)
      assert_equal 1, plan.length
      assert_equal "B", plan.first.letter
      assert_equal File.join(root, "assets/images/books/x/b.png"), plan.first.out_path
      assert_match(/BACKUP/, plan.first.prompt)
    end
  end
end
