# frozen_string_literal: true

# Differential byte-identity test for the deterministic local banner renderer.
#
#     ruby -Ilib test/ruby/test_local_renderer.rb
#
# The Python preview_generator.render_local_svg is the ORACLE: for a wide,
# varied set of slugs this shells out to python3 and asserts the Ruby output
# is BYTE-IDENTICAL. render_local_svg is a HARD determinism contract — same
# slug must produce the same banner in either language, or committed artwork
# drifts. The seed -> palette/composition scheme is checked the same way over
# a wide integer range. Skips cleanly (never fails) when python3 is absent;
# runs for real here (python3 3.14 + PyYAML installed).

require "minitest/autorun"
require "json"
require "tempfile"
require "zlib"

require_relative "../../lib/zer0_image_generator/svg/local_renderer"

class TestLocalRenderer < Minitest::Test
  LR = Zer0ImageGenerator::Svg::LocalRenderer

  REPO_ROOT = File.expand_path("../..", __dir__)
  ENGINE_DIR = File.join(REPO_ROOT, "lib", "zer0_image_generator")

  # Python driver: reads {"slugs":[...],"seeds":[...]} and emits the oracle's
  # render_local_svg / seed_for / palette_for / composition_for results.
  PY_DRIVER = <<~PYTHON
    import sys, json
    sys.path.insert(0, #{ENGINE_DIR.inspect})
    import preview_generator as pg
    req = json.load(open(sys.argv[1]))
    out = {
        "renders": [pg.render_local_svg(s, pg.seed_for(s)) for s in req["slugs"]],
        "seeds_for": [pg.seed_for(s) for s in req["slugs"]],
        "palettes": [pg.palette_for(n) for n in req["seeds"]],
        "compositions": [pg.composition_for(n) for n in req["seeds"]],
        "article_renders": [
            pg.render_local_svg(a["slug"], pg.seed_for(a["slug"]), a)
            for a in req.get("articles", [])
        ],
        "article_themes": [
            list(pg.banner_theme_for(a)) for a in req.get("articles", [])
        ],
    }
    json.dump(out, open(sys.argv[2], "w"))
  PYTHON

  def python3?
    @python3 ||= system("python3", "--version",
                        out: File::NULL, err: File::NULL) ? :yes : :no
    @python3 == :yes
  end

  # Curated edge slugs + a broad generated spread. >= 200 varied slugs, hitting
  # empty-ish, unicode, very long, whitespace/escaped, and the sample slug.
  def slugs
    curated = [
      "hello-world",                 # the committed banner-hello-world.svg slug
      "getting-started",             # the docs fixture slug
      "", " ", "  ", "\t", "\n", "a", "z", "0", "-", "_", "..", "/", "//",
      "a b", "a/b/c", "a&b", "a<b>c", "&<>&<>",
      "café", "über-café", "naïve", "façade", "Москва", "日本語のタイトル",
      "emoji-🚀-banner", "🎮🕹️👾", "mixed 日本 & <x> café",
      "UPPER", "MiXeD-CaSe", "trailing-space ", " leading",
      "tab\tinside", "new\nline", "amp&only", "lt<only",
      "x" * 2000,                    # very long
      "y" * 511, "z" * 3,
      "constellation", "starmap-5", "ridgeline", "dawn-badge",
      "invaders-magma-5", "lowpoly-dusk-5", "mandala-ocean-11",
      "pixel-quest-dusk-7", "lsystem-tree-sakura-7", "flowfield-moss-5",
    ]
    generated = []
    (0...260).each do |i|
      # Vary shape so seeds scatter across palette (%10) and variant (>>8 %8).
      generated << "post-#{i}"
      generated << "2026-#{format('%02d', (i % 12) + 1)}-#{format('%02d', (i % 28) + 1)}-entry-#{i}"
    end
    curated + generated
  end

  def seeds
    wide = (0...3000).to_a
    edges = [
      0, 1, 255, 256, 257, 65_535, 65_536,
      2**31 - 1, 2**31, 2**32 - 1, 2**32 - 256,
      0xFFFF_FF00, 0x0000_0100, 0xDEAD_BEEF, 0xCAFE_BABE, 1_103_515_245,
    ]
    wide + edges
  end

  # Articles spanning every composition, the tie-break fallback, and the
  # substring trap ("decision"/"efficiency" must NOT read as the "ci" of a CLI
  # post) — plus unicode and an empty-ish record.
  def articles
    [
      { "slug" => "order-your-dockerfile", "section" => "hacks",
        "categories" => "docker ci-cd", "title" => "Order your Dockerfile",
        "description" => "layer cache", "body" => "docker build cache layers" },
      { "slug" => "grep-the-honest-review", "section" => "tools",
        "categories" => "search files", "title" => "grep: the honest review",
        "description" => "a tool review", "body" => "editor plugin install" },
      { "slug" => "two-posts-one-face", "section" => "field-notes",
        "categories" => "ai automation", "title" => "The robot wrote a loop",
        "description" => "a narrative", "body" => "agent automation process" },
      { "slug" => "prove-it-moved", "section" => "docs",
        "categories" => "reference", "title" => "Architecture overview",
        "description" => "a guide", "body" => "system structure diagram" },
      { "slug" => "threat-model", "section" => "posts",
        "categories" => "security", "title" => "Threat model your rollback",
        "description" => "risk", "body" => "token secret audit permission" },
      # No keyword anywhere -> falls through to the seed-chosen composition.
      { "slug" => "untagged", "section" => "", "categories" => "",
        "title" => "A quiet piece", "description" => "",
        "body" => "prose with nothing distinctive in it whatsoever" },
      # The substring trap: these words contain 'ci' and 'ai' as SUBSTRINGS.
      { "slug" => "decisions", "section" => "", "categories" => "",
        "title" => "Decisions and efficiency in a specific domain",
        "description" => "certain", "body" => "decision efficiency specific" },
      { "slug" => "café-notes", "section" => "field-notes",
        "categories" => "café", "title" => "Über naïve 日本語",
        "description" => "unicode", "body" => "note essay story" },
      { "slug" => "", "section" => "", "categories" => "", "title" => "",
        "description" => "", "body" => "" },
    ]
  end

  def run_oracle(slug_list, seed_list)
    req = Tempfile.new(["req", ".json"])
    res = Tempfile.new(["res", ".json"])
    drv = Tempfile.new(["driver", ".py"])
    begin
      req.write(JSON.generate(slugs: slug_list, seeds: seed_list,
                              articles: articles))
      req.flush
      drv.write(PY_DRIVER)
      drv.flush
      ok = system("python3", drv.path, req.path, res.path,
                  out: File::NULL, err: File::NULL)
      assert ok, "python3 oracle driver failed"
      JSON.parse(File.read(res.path))
    ensure
      [req, res, drv].each { |f| f.close; f.unlink }
    end
  end

  # The content-aware path: the article record, not just the slug, chooses the
  # composition and palette — so this asserts BOTH engines pick the same theme
  # and emit the same bytes for the same page.
  def test_article_banners_byte_identical_and_themed
    skip "python3 not available" unless python3?
    oracle = run_oracle(["hello-world"], [])
    py_renders = oracle["article_renders"]
    py_themes = oracle["article_themes"]

    diverged = []
    articles.each_with_index do |article, i|
      ruby_theme = LR.banner_theme_for(article)
      assert_equal py_themes[i], ruby_theme,
                   "banner_theme_for diverged for #{article["slug"].inspect}"
      ruby_svg = LR.render_local_svg(article["slug"],
                                     LR.seed_for(article["slug"]), article)
      diverged << article["slug"] unless ruby_svg == py_renders[i]
    end
    assert_empty diverged, "article render diverged for: #{diverged.inspect}"

    themes = articles.map { |a| LR.banner_theme_for(a) }
    by_slug = articles.map { |a| a["slug"] }.zip(themes).to_h

    # Section is the strongest signal, and each section gets its own look.
    assert_equal "circuit",    by_slug["order-your-dockerfile"][0]
    assert_equal "pixelscene", by_slug["grep-the-honest-review"][0]
    assert_equal "flowfield",  by_slug["two-posts-one-face"][0]
    assert_equal "lowpoly",    by_slug["prove-it-moved"][0]
    assert_equal "starfield",  by_slug["threat-model"][0]

    # Whole-word matching. 'decision'/'efficiency'/'specific' contain "ci" and
    # 'certain' contains "ai", but none of them is a CLI or an AI post. Assert
    # on the TOKENS rather than the chosen composition: with no keyword hits at
    # all the article falls through to the seed, which is free to land on any
    # composition including circuit — so the outcome alone cannot tell a
    # substring bug apart from a legitimate fallback.
    tokens = LR.banner_words("Decisions and efficiency in a specific certain domain")
    %w[ci cd ai].each do |fragment|
      refute_includes tokens, fragment,
                      "#{fragment.inspect} must not be tokenized out of a longer word"
    end
    # And the converse: adding one real keyword DOES move the art.
    quiet = articles.find { |a| a["slug"] == "untagged" }
    assert_equal "circuit", LR.banner_theme_for(quiet.merge("section" => "hacks"))[0],
                 "a real section keyword must decide the composition"

    # All five compositions were actually rendered by the identity comparison.
    assert_equal LR::BANNER_COMPOSITION_ORDER.sort,
                 themes.map(&:first).uniq.sort - [],
                 "fixtures must exercise every composition"
  end

  # Same article in, same bytes out; changed content, changed art.
  def test_article_art_is_deterministic_and_content_sensitive
    article = articles.first
    first = LR.render_local_svg(article["slug"], 0, article)
    assert_equal first, LR.render_local_svg(article["slug"], 0, article),
                 "same article must render byte-identically"

    retitled = article.merge("title" => "A completely different headline")
    refute_equal first, LR.render_local_svg(article["slug"], 0, retitled),
                 "retitling a piece must re-roll its art"
  end

  def test_render_local_svg_byte_identical_across_slugs
    skip "python3 not available" unless python3?
    all = slugs
    assert_operator all.length, :>=, 200, "need >= 200 varied slugs"

    oracle = run_oracle(all, [])
    py_renders = oracle["renders"]
    py_seeds = oracle["seeds_for"]

    diverged = []
    variant_parities = []
    palette_indices = []
    all.each_with_index do |slug, i|
      ruby_seed = LR.seed_for(slug)
      assert_equal py_seeds[i], ruby_seed, "seed_for diverged for #{slug.inspect}"
      ruby_svg = LR.render_local_svg(slug, ruby_seed)
      diverged << slug unless ruby_svg == py_renders[i]
      variant_parities << ((ruby_seed >> 8) % 8).even?
      palette_indices << (ruby_seed % 10)
    end

    assert_empty diverged,
                 "render_local_svg diverged for #{diverged.length} slug(s): " \
                 "#{diverged.first(5).map(&:inspect).join(', ')}"

    # Prove both variant branches (grid floor vs starfield) and a spread of
    # palettes were actually exercised by the byte-identity comparison.
    assert_includes variant_parities, true, "no even-variant slug exercised"
    assert_includes variant_parities, false, "no odd-variant slug exercised"
    assert_operator palette_indices.uniq.length, :>=, 8,
                    "palette coverage too narrow to be meaningful"

    # Report the exact count proved identical (visible with -v / on failure).
    proved = all.length - diverged.length
    assert_equal all.length, proved
  end

  def test_seed_palette_composition_agree_over_wide_range
    skip "python3 not available" unless python3?
    seed_list = seeds
    oracle = run_oracle([], seed_list)
    py_palettes = oracle["palettes"]
    py_comps = oracle["compositions"]

    seed_list.each_with_index do |seed, i|
      assert_equal py_palettes[i], LR.palette_for(seed),
                   "palette_for diverged at seed=#{seed}"
      assert_equal py_comps[i], LR.composition_for(seed),
                   "composition_for diverged at seed=#{seed}"
    end
  end

  # seed_for is zlib.crc32 of the UTF-8 bytes — independent of python.
  def test_seed_for_matches_zlib_crc32
    assert_equal Zlib.crc32("hello-world"), LR.seed_for("hello-world")
    assert_equal 0, LR.seed_for(""), "crc32 of the empty string is 0 (unsigned)"
    assert_operator LR.seed_for("café"), :>=, 0, "crc32 must be a non-negative unsigned int"
  end

  # Zero seed (crc32 of the empty slug is not 0, but guard the documented
  # `seed or 1` path directly) must not freeze the LCG into an all-zero banner.
  def test_zero_seed_uses_one
    svg = LR.render_local_svg("anything", 0)
    assert svg.start_with?("<svg ")
    # A frozen LCG emits the SAME number over and over, so the tell is a
    # collapsed coordinate set — not any one magic coordinate. (The old
    # assertion pinned `cx="1216"`, an artifact of the retired skyline
    # template; on the circuit grid that value is a legitimate 32px junction.)
    coords = svg.scan(/(?:cx|x)="(\d+)"/).flatten.uniq
    assert_operator coords.length, :>, 20,
                    "zero seed should still advance the LCG, not repeat one value"
    refute_equal svg, LR.render_local_svg("anything", 1),
                 "a different seed must give different art"
  end
end
