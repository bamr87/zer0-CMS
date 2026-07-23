# frozen_string_literal: true

# Unit tests for the ABC content engine.
#
#     ruby -Ilib test/zer0_cms/test_abc_engine.rb
#
# Pure stdlib + the deterministic provider — zero network, fully reproducible.

require "minitest/autorun"
require "tmpdir"
require "yaml"
require "json"
require_relative "../../lib/zer0_cms"

class TestAbcLexicon < Minitest::Test
  def test_it_systems_lexicon_covers_every_letter
    lex = Zer0Cms::Abc::Lexicon.for("IT systems")
    ("A".."Z").each do |l|
      entry = lex.entry(l)
      refute_nil entry["word"], "letter #{l} missing word"
      refute_nil entry["subject"], "letter #{l} missing subject"
      assert_match(/#{l} is for/i, entry["tagline"], "tagline should read '#{l} is for …'")
    end
  end

  def test_theme_lookup_is_slug_insensitive
    a = Zer0Cms::Abc::Lexicon.for("IT systems")
    b = Zer0Cms::Abc::Lexicon.for("it_systems")
    assert_equal a.theme, b.theme
  end

  def test_unknown_theme_raises
    assert_raises(Zer0Cms::Abc::Lexicon::UnknownTheme) do
      Zer0Cms::Abc::Lexicon.for("underwater basket weaving")
    end
  end
end

class TestDeterministicProvider < Minitest::Test
  def test_plan_is_complete_and_offline
    provider = Zer0Cms::Abc::ContentProvider.build(:deterministic)
    plan = provider.plan(theme: "IT systems")
    assert_equal 26, plan["letters"].length
    assert_equal "Automation", plan["letters"]["A"]["word"]
    assert_equal "isometric-tech-toy", plan["default_art_style"]
  end

  def test_registry_knows_both_providers
    assert_includes Zer0Cms::Abc::ContentProvider.names, "deterministic"
    assert_includes Zer0Cms::Abc::ContentProvider.names, "anthropic"
  end
end

class TestArtStyles < Minitest::Test
  def setup
    @styles = Zer0Cms::Abc::ArtStyles.default
  end

  def test_catalog_matches_the_image_generator_source
    # The catalog is a vendored copy; these ids are the cross-repo contract.
    %w[isometric-tech-toy chalkboard-doodle soft-plush crayon-primary
       paper-cutout watercolor-storybook].each do |id|
      assert @styles.style?(id), "missing art style #{id}"
    end
  end

  def test_render_prompt_is_text_free_and_deterministic
    args = { letter: "A", word: "Automation", subject: "a robot arm",
             style: "isometric-tech-toy" }
    p1 = @styles.render_prompt(**args)
    p2 = @styles.render_prompt(**args)
    assert_equal p1, p2
    assert_match(/no text/i, p1)
    assert_match(/AUTOMATION/, p1)
  end
end

class TestWizard < Minitest::Test
  def build
    Zer0Cms::Abc::Wizard.new(
      theme: "IT systems", slug: "it-alphabet",
      art_style: "isometric-tech-toy", provider: :deterministic
    ).run
  end

  def test_produces_a_valid_26_letter_spec
    spec = build
    assert_instance_of Zer0Cms::Abc::Spec, spec
    assert_equal 26, spec.alphabet.length
    assert_equal "abc-language", spec.series
    assert_equal "it-alphabet", spec.slug
    assert_equal "isometric-tech-toy", spec.art_style
  end

  def test_every_letter_gets_a_composed_prompt_and_planned_image
    build.alphabet.each do |e|
      refute_empty e["prompt"]
      assert_match %r{^/assets/images/books/it-alphabet/#{e['letter'].downcase}-}, e["image"]
      assert_equal "planned", e["status"]
    end
  end

  def test_cover_is_built
    cover = build.cover
    refute_nil cover
    assert_equal "/assets/images/books/it-alphabet/cover.png", cover["image"]
    refute_empty cover["prompt"]
  end

  def test_unknown_art_style_falls_back_with_a_warning
    wizard = Zer0Cms::Abc::Wizard.new(
      theme: "IT systems", art_style: "does-not-exist", provider: :deterministic
    )
    spec = wizard.run
    assert_equal "isometric-tech-toy", spec.art_style
    assert(wizard.warnings.any? { |w| w.include?("does-not-exist") })
  end

  def test_auto_provider_uses_the_lexicon_for_a_known_theme
    # No API key needed: a bundled theme resolves to the deterministic provider.
    spec = Zer0Cms::Abc::Wizard.new(theme: "IT systems", provider: :auto).run
    assert_equal 26, spec.alphabet.length
  end
end

class TestSpecValidation < Minitest::Test
  def test_rejects_a_bad_slug
    spec = Zer0Cms::Abc::Spec.new(
      "slug" => "Not A Slug", "title" => "x", "art_style" => "crayon-primary",
      "alphabet" => [{ "letter" => "A", "word" => "Apple", "subject" => "s", "tagline" => "t" }]
    )
    assert_raises(Zer0Cms::Abc::Spec::InvalidSpec) { spec.validate! }
  end

  def test_round_trips_through_json
    spec = Zer0Cms::Abc::Wizard.new(theme: "IT systems", provider: :deterministic).run
    restored = Zer0Cms::Abc::Spec.from_json(spec.to_json)
    assert_equal spec.slug, restored.slug
    assert_equal spec.alphabet.length, restored.alphabet.length
  end
end

class TestJekyllExporter < Minitest::Test
  def test_writes_a_parseable_book_and_sidecar
    spec = Zer0Cms::Abc::Wizard.new(
      theme: "IT systems", slug: "it-alphabet", provider: :deterministic
    ).run
    Dir.mktmpdir do |root|
      result = Zer0Cms::Abc::JekyllExporter.new(spec, site_root: root).export

      assert File.file?(result.book_path)
      assert File.file?(result.spec_path)
      assert_equal 27, result.planned_images.length # 26 letters + cover

      md = File.read(result.book_path, encoding: "utf-8")
      fm = md.split(/^---\s*$/, 3)[1]
      data = YAML.safe_load(fm)
      assert_equal "book-abc", data["layout"]
      assert_equal "abc-language", data["series"]
      assert_equal 26, data["alphabet"].length
      # prompts must be text-free by contract
      data["alphabet"].each { |e| assert_match(/no text/i, e["prompt"]) }

      sidecar = JSON.parse(File.read(result.spec_path, encoding: "utf-8"))
      assert_equal 1, sidecar["spec_version"]
    end
  end
end
