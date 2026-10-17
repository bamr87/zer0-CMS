# frozen_string_literal: true

# Unit + differential tests for lib/zer0_image_generator/content.rb and
# lib/zer0_image_generator/prompt.rb (the front-matter / prompt layer).
#
#     ruby -Ilib test/ruby/test_content.rb
#
# No bundler, no network. The differential half shells out to the Python oracle
# (lib/zer0_image_generator/preview_generator.py) and asserts byte-identical
# results; it skips cleanly when python3 is unavailable but otherwise MUST pass.

require "minitest/autorun"
require "tmpdir"
require "json"
require "base64"
require "open3"

require_relative "../../lib/zer0_image_generator/content"
require_relative "../../lib/zer0_image_generator/prompt"

C = Zer0ImageGenerator::Content
P = Zer0ImageGenerator::Prompt

REPO_ROOT = File.expand_path("../..", __dir__)
ORACLE_DIR = File.join(REPO_ROOT, "lib", "zer0_image_generator")

# The oracle's DEFAULTS, mirrored so the ported unit assertions use the same
# resolved values the Python tests' make_settings() does.
DEFAULT_STYLE =
  "retro pixel art, 8-bit video game aesthetic, vibrant colors, " \
  "nostalgic, clean pixel graphics"
DEFAULT_STYLE_MODIFIERS =
  "pixelated, retro gaming style, CRT screen glow effect, limited color palette"

# A Settings stand-in exposing exactly the fields content.rb / prompt.rb read.
# The real Zer0ImageGenerator::Settings is a separate slice (see INTEGRATION
# NEEDS); this double keeps these tests runnable without it.
Settings = Struct.new(
  :style, :style_modifiers, :assets_prefix, :auto_prefix,
  :output_dir, :enhance_prompt, keyword_init: true
)

def make_settings(**over)
  Settings.new(
    style: over.fetch(:style, DEFAULT_STYLE),
    style_modifiers: over.fetch(:style_modifiers, DEFAULT_STYLE_MODIFIERS),
    assets_prefix: over.fetch(:assets_prefix, "/assets"),
    auto_prefix: over.fetch(:auto_prefix, true),
    output_dir: over.fetch(:output_dir, "assets/images/previews"),
    enhance_prompt: over.fetch(:enhance_prompt, "")
  )
end

# --- Python oracle bridge ----------------------------------------------------

PY_DRIVER = <<~'PYSRC'
  import sys, json, base64, glob, os, tempfile
  from pathlib import Path
  sys.path.insert(0, sys.argv[3])
  import preview_generator as pg

  req = json.load(open(sys.argv[1], encoding="utf-8"))
  op = req["op"]
  res = None
  if op == "generate_filename":
      res = [pg.generate_filename(t) for t in req["titles"]]
  elif op == "normalize_preview_path":
      res = []
      for c in req["cases"]:
          s = pg.Settings(auto_prefix=c["auto_prefix"], assets_prefix=c["assets_prefix"])
          res.append(pg.normalize_preview_path(c["preview"], s))
  elif op == "preview_front_matter_path":
      res = []
      for c in req["cases"]:
          s = pg.Settings(output_dir=c["output_dir"], assets_prefix=c["assets_prefix"])
          res.append(pg.preview_front_matter_path(s, c["filename"]))
  elif op == "build_prompt":
      res = []
      for c in req["cases"]:
          cf = pg.ContentFile(path=Path("x"), title=c["title"], description=c["description"],
                              categories=c["categories"], preview=None, author=None,
                              content=c["content"], front_matter={})
          s = pg.Settings(style=c["style"], style_modifiers=c["style_modifiers"])
          res.append(pg.build_prompt(cf, s))
  elif op == "build_enhance_prompt":
      res = []
      for c in req["cases"]:
          cf = pg.ContentFile(path=Path("x"), title=c["title"], description=c["description"],
                              categories="", preview=None, author=None, content="", front_matter={})
          s = pg.Settings(style=c["style"], enhance_prompt=c["enhance_prompt"])
          res.append(pg.build_enhance_prompt(cf, s))
  elif op == "parse_front_matter":
      res = []
      for c in req["cases"]:
          d = tempfile.mkdtemp()
          p = Path(d) / "p.md"
          p.write_bytes(base64.b64decode(c["bytes_b64"]))
          cf = pg.parse_front_matter(p, c["key"])
          if cf is None:
              res.append(None)
          else:
              res.append({"title": cf.title, "description": cf.description,
                          "categories": cf.categories, "preview": cf.preview,
                          "content": base64.b64encode(cf.content.encode()).decode()})
  elif op == "update_front_matter":
      res = []
      for c in req["cases"]:
          d = tempfile.mkdtemp()
          p = Path(d) / "post.md"
          p.write_bytes(base64.b64decode(c["bytes_b64"]))
          ok = pg.update_front_matter(p, c["preview_path"], dry_run=c["dry_run"], key=c["key"])
          out = p.read_bytes()
          leftovers = sorted(os.path.basename(x)
                             for x in glob.glob(str(Path(d) / "*.bak")) + glob.glob(str(Path(d) / "*~")))
          res.append({"ok": ok, "bytes_b64": base64.b64encode(out).decode(), "leftovers": leftovers})
  else:
      raise SystemExit("unknown op " + op)

  # Result goes to a file, NOT stdout: the oracle's info/success logs print to
  # stdout and would corrupt a stdout-delivered payload.
  with open(sys.argv[2], "w", encoding="utf-8") as fh:
      json.dump(res, fh)
PYSRC

def python3?
  return @python3 if defined?(@python3)

  _out, status = Open3.capture2e("python3", "-c",
                                 "import sys, yaml; sys.exit(0 if sys.version_info[0] == 3 else 1)")
  @python3 = status.success?
rescue StandardError
  @python3 = false
end

# Run one oracle op; returns the parsed JSON result (Array).
def oracle(op, payload)
  Dir.mktmpdir do |dir|
    req = File.join(dir, "req.json")
    outp = File.join(dir, "out.json")
    drv = File.join(dir, "driver.py")
    File.write(drv, PY_DRIVER)
    File.write(req, JSON.generate(payload.merge("op" => op)))
    _stdout, stderr, status = Open3.capture3("python3", drv, req, outp, ORACLE_DIR)
    raise "oracle #{op} failed: #{stderr}" unless status.success?

    JSON.parse(File.read(outp))
  end
end


class TestSlugParity < Minitest::Test
  # Ported verbatim from test_preview_generator.py::TestSlugAndPaths.
  def test_slug_parity_vectors
    {
      "Auto-hide Navigation" => "auto-hide-navigation",
      "Hello, World! 123" => "hello-world-123",
      "  Spaces  Around  " => "spaces-around",
      "Café Déjà Vu" => "caf-d-j-vu",
      "UPPER lower" => "upper-lower",
    }.each { |title, expected| assert_equal expected, C.generate_filename(title) }
  end

  def test_slug_50_char_cut_after_trim
    title = ("x" * 49) + "-" + ("y" * 30)
    slug = C.generate_filename(title)
    assert_equal 50, slug.length
    assert slug.start_with?("x" * 49)
  end

  # A corpus spanning the risk classes the slice calls out: unicode that folds
  # to ASCII (Kelvin/Angstrom/Ohm signs), the İ two-char lower-expansion, final
  # sigma, full-width forms, non-ASCII digits, emoji, punctuation runs, leading
  # digits, empty, and very long titles — differentially checked against the
  # oracle's generate_filename.
  SLUG_CORPUS = [
    "", " ", "   ", "-", "---", "----leading", "trailing----",
    "Hello, World! 123", "Auto-hide Navigation", "  Spaces  Around  ",
    "UPPER lower", "MixedCase123", "123 leading digits", "007",
    "Café Déjà Vu", "naïve façade", "Straße", "İstanbul", "ﬀ ligature",
    "K elvin", "Å ngstrom", "Ω hm", # Kelvin, Angstrom, Ohm
    "final Σ sigma ΟΔΟΣ", "ς already final", "ＦＵＬＬＷＩＤＴＨ", "全角１２３",
    "Ⅳ roman numeral", "٤٢ arabic digits", "café   sep",
    "emoji 🎨 art 🚀", "tabs\tand\nnewlines\r\nhere", "non break space",
    "a" * 60, ("word-" * 20), "!!!@@@###$$$", "under_score dot.dot",
    "CRLF\r\ninside", "trailing space and dash - ", "  -mixed- edges-  ",
    "ЯЗЫК кириллица", "日本語のタイトル", "emoji-only🎉🎊",
  ].freeze

  def test_slug_corpus_matches_oracle
    skip "python3+PyYAML unavailable" unless python3?

    want = oracle("generate_filename", "titles" => SLUG_CORPUS)
    got = SLUG_CORPUS.map { |t| C.generate_filename(t) }
    SLUG_CORPUS.each_with_index do |title, i|
      assert_equal want[i], got[i], "slug mismatch for #{title.inspect}"
    end
  end
end


class TestPathHelpers < Minitest::Test
  # Ported from test_preview_generator.py::TestSlugAndPaths.
  def test_front_matter_path_strips_assets_prefix
    s = make_settings(output_dir: "assets/images/previews")
    assert_equal "/images/previews/slug.png", C.preview_front_matter_path(s, "slug.png")
  end

  def test_front_matter_path_custom_dir
    s = make_settings(output_dir: "static/previews")
    assert_equal "/static/previews/slug.svg", C.preview_front_matter_path(s, "slug.svg")
  end

  def test_check_preview_exists
    Dir.mktmpdir do |tmp|
      root = tmp
      FileUtils.mkdir_p(File.join(root, "assets", "images"))
      File.binwrite(File.join(root, "assets", "images", "x.png"), "png")
      s = make_settings
      assert C.check_preview_exists("/images/x.png", s, root)
      assert C.check_preview_exists("https://cdn.example/x.png", s, root)
      refute C.check_preview_exists("/images/missing.png", s, root)
      refute C.check_preview_exists(nil, s, root)
    end
  end

  def test_find_preview_image_locates_by_output_dir_basename
    Dir.mktmpdir do |tmp|
      s = make_settings(output_dir: "assets/images/previews")
      FileUtils.mkdir_p(File.join(tmp, "assets", "images", "previews"))
      target = File.join(tmp, "assets", "images", "previews", "slug.png")
      File.binwrite(target, "x")
      found = C.find_preview_image("/images/previews/slug.png", s, tmp)
      assert_equal target, found
      assert_nil C.find_preview_image("https://x/y.png", s, tmp)
      assert_nil C.find_preview_image(nil, s, tmp)
    end
  end

  NORMALIZE_CORPUS = [
    { preview: nil, auto_prefix: true, assets_prefix: "/assets" },
    { preview: "", auto_prefix: true, assets_prefix: "/assets" },
    { preview: "/images/x.png", auto_prefix: true, assets_prefix: "/assets" },
    { preview: "/assets/images/x.png", auto_prefix: true, assets_prefix: "/assets" },
    { preview: "/images/x.png", auto_prefix: false, assets_prefix: "/assets" },
    { preview: "http://cdn/x.png", auto_prefix: true, assets_prefix: "/assets" },
    { preview: "https://cdn/x.png", auto_prefix: true, assets_prefix: "/assets" },
    { preview: "/images/x.png", auto_prefix: true, assets_prefix: "" },
    { preview: "assets-lookalike", auto_prefix: true, assets_prefix: "/assets" },
    { preview: "/x/assets/y.png", auto_prefix: true, assets_prefix: "/assets" },
    { preview: "/deep/path.png", auto_prefix: true, assets_prefix: "/static" },
    { preview: "relative/no/slash.png", auto_prefix: true, assets_prefix: "/assets" },
  ].freeze

  def test_normalize_corpus_matches_oracle
    skip "python3+PyYAML unavailable" unless python3?

    want = oracle("normalize_preview_path", "cases" => NORMALIZE_CORPUS.map { |c|
      { "preview" => c[:preview], "auto_prefix" => c[:auto_prefix], "assets_prefix" => c[:assets_prefix] }
    })
    NORMALIZE_CORPUS.each_with_index do |c, i|
      got = C.normalize_preview_path(c[:preview], make_settings(auto_prefix: c[:auto_prefix], assets_prefix: c[:assets_prefix]))
      # want[i] may be JSON null (the None/"" passthrough cases); assert_equal
      # rejects a nil expectation, so compare structurally instead.
      assert want[i] == got, "normalize mismatch for #{c.inspect}: oracle=#{want[i].inspect} ruby=#{got.inspect}"
    end
  end

  FRONT_MATTER_PATH_CORPUS = [
    { output_dir: "assets/images/previews", assets_prefix: "/assets" },
    { output_dir: "static/previews", assets_prefix: "/assets" },
    { output_dir: "assets", assets_prefix: "/assets" },
    { output_dir: "assets/", assets_prefix: "/assets" },
    { output_dir: "/assets/x/", assets_prefix: "assets" },
    { output_dir: "assetsfoo/bar", assets_prefix: "/assets" }, # prefix-lookalike, must NOT strip
    { output_dir: "", assets_prefix: "/assets" },
    { output_dir: "images/previews", assets_prefix: "" },
    { output_dir: "a/b/c", assets_prefix: "/a" },
    { output_dir: "a", assets_prefix: "/a" },
  ].freeze

  def test_front_matter_path_corpus_matches_oracle
    skip "python3+PyYAML unavailable" unless python3?

    want = oracle("preview_front_matter_path", "cases" => FRONT_MATTER_PATH_CORPUS.map { |c|
      { "output_dir" => c[:output_dir], "assets_prefix" => c[:assets_prefix], "filename" => "slug.png" }
    })
    FRONT_MATTER_PATH_CORPUS.each_with_index do |c, i|
      got = C.preview_front_matter_path(make_settings(output_dir: c[:output_dir], assets_prefix: c[:assets_prefix]), "slug.png")
      assert_equal want[i], got, "fm-path mismatch for #{c.inspect}"
    end
  end
end


class TestFrontMatterEditor < Minitest::Test
  # Each `edit` mirrors test_preview_generator.py::TestFrontMatterEditor.edit:
  # write bytes, run update_front_matter, read bytes, collect *.bak / *~ leftovers.
  def edit(text, value = "/images/previews/new.png")
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "post.md")
      File.binwrite(path, text)
      ok = C.update_front_matter(path, value)
      result = File.binread(path)
      leftovers = (Dir.glob(File.join(tmp, "*.bak")) + Dir.glob(File.join(tmp, "*~"))).sort
      return [ok, result, leftovers]
    end
  end

  def test_replaces_existing_preview
    ok, out, leftovers = edit("---\ntitle: T\npreview: /images/previews/old.png\n---\nBody\n")
    assert ok
    assert_includes out, "preview: /images/previews/new.png\n"
    refute_includes out, "old.png"
    assert_equal [], leftovers
  end

  def test_inserts_after_description
    ok, out, = edit("---\ntitle: T\ndescription: D\nlayout: default\n---\nBody\n")
    assert ok
    assert_includes out, "description: D\npreview: /images/previews/new.png\nlayout: default\n"
  end

  def test_inserts_after_folded_description
    text = "---\ntitle: T\ndescription: >-\n  line one\n  line two\nlayout: default\n---\nBody\n"
    ok, out, = edit(text)
    assert ok
    assert_includes out,
                    "description: >-\n  line one\n  line two\npreview: /images/previews/new.png\nlayout: default\n"
  end

  def test_inserts_after_title_without_description
    ok, out, = edit("---\ntitle: T\nlayout: default\n---\nBody\n")
    assert ok
    assert_includes out, "title: T\npreview: /images/previews/new.png\nlayout: default\n"
  end

  def test_body_preview_line_untouched
    text = "---\ntitle: T\npreview: /images/previews/old.png\n---\nBody text.\npreview: not-front-matter\nMore body.\n"
    ok, out, = edit(text)
    assert ok
    assert_includes out, "preview: not-front-matter\n"
    assert_equal 1, out.scan("new.png").length
  end

  def test_preserves_missing_trailing_newline
    ok, out, = edit("---\ntitle: T\n---\nBody without newline")
    assert ok
    assert out.end_with?("Body without newline")
  end

  def test_crlf_preserved
    text = "---\r\ntitle: T\r\ndescription: D\r\n---\r\nBody\r\n"
    ok, out, = edit(text)
    assert ok
    assert_includes out, "description: D\r\npreview: /images/previews/new.png\r\n"
    refute_includes out.gsub("\r\n", ""), "\n\n"
  end

  def test_no_front_matter_refused
    ok, out, = edit("Just a plain file\n")
    refute ok
    assert_equal "Just a plain file\n", out
  end

  def test_dry_run_writes_nothing
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "post.md")
      File.binwrite(path, "---\ntitle: T\n---\n")
      assert C.update_front_matter(path, "/x.png", dry_run: true)
      assert_equal "---\ntitle: T\n---\n", File.binread(path)
    end
  end

  def test_configured_key_replace_and_insert
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "p.md")
      File.binwrite(path, "---\ntitle: T\ndescription: D\nimage: /old.png\n---\nBody\n")
      assert C.update_front_matter(path, "/new.png", key: "image")
      body = File.binread(path)
      assert_includes body, "image: /new.png\n"
      refute_includes body, "/old.png"

      File.binwrite(path, "---\ntitle: T\ndescription: D\n---\nBody\n")
      assert C.update_front_matter(path, "/new.png", key: "image")
      body = File.binread(path)
      assert_includes body, "description: D\nimage: /new.png\n"
      refute_includes body, "preview:"
    end
  end

  # The full byte-identity gauntlet: every fixture run through BOTH engines,
  # asserting identical output bytes AND identical leftover sets.
  UPDATE_CORPUS = [
    ["---\ntitle: T\npreview: /images/previews/old.png\n---\nBody\n", "/images/previews/new.png", "preview", false],
    ["---\ntitle: T\ndescription: D\nlayout: default\n---\nBody\n", "/images/previews/new.png", "preview", false],
    ["---\ntitle: T\ndescription: >-\n  line one\n  line two\nlayout: default\n---\nBody\n", "/p.png", "preview", false],
    ["---\ntitle: T\nlayout: default\n---\nBody\n", "/p.png", "preview", false],
    ["---\ntitle: T\npreview: /images/previews/old.png\n---\nBody text.\npreview: not-front-matter\nMore body.\n", "/p.png", "preview", false],
    ["---\ntitle: T\n---\nBody without newline", "/p.png", "preview", false],
    ["---\r\ntitle: T\r\ndescription: D\r\n---\r\nBody\r\n", "/images/previews/new.png", "preview", false],
    ["Just a plain file\n", "/p.png", "preview", false],
    ["---\ntitle: T\n---\n", "/x.png", "preview", true], # dry run
    ["---\ntitle: T\ndescription: D\nimage: /old.png\n---\nBody\n", "/new.png", "image", false],
    ["---\ntitle: T\ndescription: D\n---\nBody\n", "/new.png", "image", false],
    # No trailing newline on the anchor line (final unterminated line → eol added).
    ["---\ntitle: T", "/p.png", "preview", false],
    # Literal block scalar continuation must not be split.
    ["---\ntitle: T\ndescription: |\n  para one\n  para two\nlayout: x\n---\nB\n", "/p.png", "preview", false],
    # Blank line inside the block between description and an indented line.
    ["---\ntitle: T\ndescription: D\n\n  continued\nlayout: x\n---\nB\n", "/p.png", "preview", false],
    # Unicode body + unicode values.
    ["---\ntitle: Café\ndescription: naïve\n---\nBödy with Ünïcode 🎨 and Δ\n", "/imäges/p.png", "preview", false],
    # CRLF with existing key.
    ["---\r\ntitle: T\r\npreview: /old.png\r\n---\r\nBody\r\n", "/new.png", "preview", false],
    # Trailing whitespace on fence + key lines must survive outside the edit.
    ["---  \ntitle: T   \ndescription: D\t\n---  \nBody\n", "/p.png", "preview", false],
    # description present but preview also present: replace preview, keep desc.
    ["---\ntitle: T\ndescription: D\npreview: /old.png\nlayout: x\n---\nB\n", "/new.png", "preview", false],
    # Custom key that does not exist and no description → insert after title.
    ["---\ntitle: T\nlayout: x\n---\nB\n", "/new.png", "image", false],
    # Empty front matter body (opener immediately followed by closer): no anchor.
    ["---\n---\nBody\n", "/p.png", "preview", false],
    # Nested map under description.
    ["---\ntitle: T\ndescription:\n  nested: yes\n  more: 1\nlayout: x\n---\nB\n", "/p.png", "preview", false],
  ].freeze

  def run_ruby_update(text, value, key, dry_run)
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "post.md")
      File.binwrite(path, text)
      ok = C.update_front_matter(path, value, dry_run: dry_run, key: key)
      out = File.binread(path)
      leftovers = (Dir.glob(File.join(tmp, "*.bak")) + Dir.glob(File.join(tmp, "*~"))).map { |p| File.basename(p) }.sort
      [ok, out, leftovers]
    end
  end

  def test_update_byte_identity_vs_oracle
    skip "python3+PyYAML unavailable" unless python3?

    cases = UPDATE_CORPUS.map do |text, value, key, dry|
      { "bytes_b64" => Base64.strict_encode64(text.dup.force_encoding(Encoding::BINARY)),
        "preview_path" => value, "key" => key, "dry_run" => dry }
    end
    want = oracle("update_front_matter", "cases" => cases)

    UPDATE_CORPUS.each_with_index do |(text, value, key, dry), i|
      r_ok, r_out, r_left = run_ruby_update(text, value, key, dry)
      w = want[i]
      w_out = Base64.decode64(w["bytes_b64"])
      assert_equal w["ok"], r_ok, "ok mismatch for case #{i}: #{text.inspect}"
      assert_equal w_out.b, r_out.b, "byte mismatch for case #{i}: #{text.inspect}"
      assert_equal w["leftovers"], r_left, "leftover mismatch for case #{i}"
    end
  end
end


class TestParseFrontMatter < Minitest::Test
  # Ported from test_preview_generator.py::TestOptionSurface parse tests.
  def test_reads_configured_key
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "p.md")
      File.binwrite(path, "---\ntitle: T\nimage: /img/x.png\n---\nBody\n")
      cf = C.parse_front_matter(path, "image")
      assert_equal "/img/x.png", cf.preview
      cf_default = C.parse_front_matter(path)
      assert_nil cf_default.preview
    end
  end

  def test_categories_joined_and_body_extracted
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "p.md")
      File.binwrite(path, "---\ntitle: Hello\ndescription: Desc\ncategories:\n  - a\n  - b\n---\nThe body\nline two\n")
      cf = C.parse_front_matter(path)
      assert_equal "Hello", cf.title
      assert_equal "Desc", cf.description
      assert_equal "a, b", cf.categories
      assert_equal "The body\nline two\n", cf.content
    end
  end

  def test_string_category_wrapped
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "p.md")
      File.binwrite(path, "---\ntitle: T\ncategories: solo\n---\nB\n")
      assert_equal "solo", C.parse_front_matter(path).categories
    end
  end

  def test_falsey_title_becomes_empty_string
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "p.md")
      File.binwrite(path, "---\ntitle: false\n---\nB\n")
      assert_equal "", C.parse_front_matter(path).title
    end
  end

  def test_no_front_matter_returns_nil
    Dir.mktmpdir do |tmp|
      path = File.join(tmp, "p.md")
      File.binwrite(path, "no front matter here\n")
      assert_nil C.parse_front_matter(path)
    end
  end

  # Differential parity for the extracted fields across the YAML shapes real
  # Jekyll front matter takes: numeric/boolean/null scalars, list vs string
  # categories, folded scalars, CRLF, unicode, quoted colons, non-string key.
  PARSE_CORPUS = [
    ["---\ntitle: Hello World\ndescription: A post\ncategories:\n  - ruby\n  - jekyll\npreview: /images/x.png\n---\nBody here\n", "preview"],
    ["---\ntitle: T\nimage: /img/x.png\n---\nBody\n", "image"],
    ["---\ntitle: T\ncategories: solo\n---\nB\n", "preview"],
    ["No front matter\nplain\n", "preview"],
    ["---\r\ntitle: CRLF\r\ndescription: D\r\ncategories: [a, b, c]\r\n---\r\nBody line\r\nmore\r\n", "preview"],
    ["---\ntitle: Café Δ\ndescription: naïve façade 🎨\n---\nBödy\n", "preview"],
    ["---\ntitle: 42\ndescription: 3.14\ncategories:\n  - 1\n  - 2\n---\nB\n", "preview"],
    ["---\ntitle: false\ndescription: true\n---\nB\n", "preview"],
    ["---\ntitle:\ndescription:\n---\nB\n", "preview"],
    ["---\ntitle: 'Quoted: colon'\ndescription: \"dq\"\n---\nB\n", "preview"],
    ["---\ntitle: T\npreview: 12345\n---\nB\n", "preview"],
    ["---\ntitle: T\ndescription: >-\n  folded one\n  folded two\n---\nBody\n", "preview"],
    ["---\ntitle: T\n---\n", "preview"],
    ["---\ntitle: T\ncategories:\n---\nB\n", "preview"],
  ].freeze

  def test_parse_corpus_matches_oracle
    skip "python3+PyYAML unavailable" unless python3?

    cases = PARSE_CORPUS.map do |text, key|
      { "bytes_b64" => Base64.strict_encode64(text.dup.force_encoding(Encoding::BINARY)), "key" => key }
    end
    want = oracle("parse_front_matter", "cases" => cases)

    PARSE_CORPUS.each_with_index do |(text, key), i|
      cf = Dir.mktmpdir do |tmp|
        path = File.join(tmp, "p.md")
        File.binwrite(path, text)
        C.parse_front_matter(path, key)
      end
      w = want[i]
      if w.nil?
        assert_nil cf, "expected nil parse for case #{i}"
        next
      end
      refute_nil cf, "expected non-nil parse for case #{i}"
      assert_equal w["title"], cf.title, "title mismatch case #{i}"
      assert_equal w["description"], cf.description, "description mismatch case #{i}"
      assert_equal w["categories"], cf.categories, "categories mismatch case #{i}"
      assert w["preview"] == cf.preview, "preview mismatch case #{i}: #{w["preview"].inspect} vs #{cf.preview.inspect}"
      assert_equal Base64.decode64(w["content"]).b, cf.content.b, "content mismatch case #{i}"
    end
  end
end


class TestPromptLayer < Minitest::Test
  def cf_for(**over)
    Zer0ImageGenerator::ContentFile.new(
      over.fetch(:path, "p.md"),
      over.fetch(:title, "Auto-hide Navigation"),
      over.fetch(:description, "Smart nav bar that hides on scroll"),
      over.fetch(:categories, "docs, features"),
      nil, nil,
      over.fetch(:content, "The top navigation bar gets out of the way while you read."),
      {}
    )
  end

  def test_build_prompt_shape
    prompt = P.build_prompt(cf_for, make_settings)
    assert_includes prompt, "titled 'Auto-hide Navigation'."
    assert_includes prompt, "The article is about: Smart nav bar that hides on scroll."
    assert_includes prompt, "Categories: docs, features."
    assert_includes prompt, "No text or words in the image."
  end

  def test_build_prompt_omits_empty_sections
    prompt = P.build_prompt(cf_for(description: "", categories: "", content: ""),
                            make_settings(style_modifiers: ""))
    refute_includes prompt, "The article is about"
    refute_includes prompt, "Categories:"
    refute_includes prompt, "Key themes"
    refute_includes prompt, "Additional style"
  end

  def test_build_enhance_prompt_default
    prompt = P.build_enhance_prompt(cf_for, make_settings)
    assert prompt.start_with?(Zer0ImageGenerator::Prompt::DEFAULT_ENHANCE_PROMPT)
    assert_includes prompt, "Context: This is a preview banner for an article titled 'Auto-hide Navigation'."
    assert_includes prompt, "Maintain the #{DEFAULT_STYLE} artistic style."
  end

  PROMPT_CORPUS = [
    { title: "Hello World", description: "A desc", categories: "a, b",
      content: "Some body content here.", style: "flat", style_modifiers: "neon" },
    { title: "No desc", description: "", categories: "", content: "", style: "s", style_modifiers: "" },
    { title: "Ünïcode Δ", description: "naïve façade", categories: "café, thé",
      content: "Whitespace\t\ncollapse   test\r\nwith nbsp and   sep.",
      style: "retro", style_modifiers: "glow" },
    { title: "Quote's", description: "it's fine", categories: "x", content: "y", style: "z", style_modifiers: "w" },
    { title: "Long", description: "d", categories: "c",
      content: ("word " * 200), style: "s", style_modifiers: "m" }, # >500 chars → truncation
    { title: "Exactly500", description: "d", categories: "c",
      content: ("x" * 499) + " tail that should be cut", style: "s", style_modifiers: "m" },
    { title: "Trailing ws body", description: "d", categories: "c",
      content: "   leading and trailing   ", style: "s", style_modifiers: "m" },
  ].freeze

  def test_build_prompt_corpus_matches_oracle
    skip "python3+PyYAML unavailable" unless python3?

    want = oracle("build_prompt", "cases" => PROMPT_CORPUS.map { |c|
      { "title" => c[:title], "description" => c[:description], "categories" => c[:categories],
        "content" => c[:content], "style" => c[:style], "style_modifiers" => c[:style_modifiers] }
    })
    PROMPT_CORPUS.each_with_index do |c, i|
      got = P.build_prompt(
        cf_for(title: c[:title], description: c[:description], categories: c[:categories], content: c[:content]),
        make_settings(style: c[:style], style_modifiers: c[:style_modifiers])
      )
      assert_equal want[i], got, "build_prompt mismatch for #{c[:title].inspect}"
    end
  end

  ENHANCE_CORPUS = [
    { title: "T", description: "D", style: "flat", enhance_prompt: "" },
    { title: "", description: "", style: "s", enhance_prompt: "" },
    { title: "Only title", description: "", style: "s", enhance_prompt: "custom prompt" },
    { title: "", description: "Only desc", style: "s", enhance_prompt: "custom" },
    { title: "Ünï", description: "Δ", style: "retro", enhance_prompt: "" },
  ].freeze

  def test_build_enhance_prompt_corpus_matches_oracle
    skip "python3+PyYAML unavailable" unless python3?

    want = oracle("build_enhance_prompt", "cases" => ENHANCE_CORPUS.map { |c|
      { "title" => c[:title], "description" => c[:description],
        "style" => c[:style], "enhance_prompt" => c[:enhance_prompt] }
    })
    ENHANCE_CORPUS.each_with_index do |c, i|
      got = P.build_enhance_prompt(
        cf_for(title: c[:title], description: c[:description], categories: "", content: ""),
        make_settings(style: c[:style], enhance_prompt: c[:enhance_prompt])
      )
      assert_equal want[i], got, "build_enhance_prompt mismatch for #{c[:title].inspect}"
    end
  end
end
