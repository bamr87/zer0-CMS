# frozen_string_literal: true

# Integration tests for the image-provider layer.
#
# These run the REAL sibling slices (logging, constants, settings, http, svg)
# and fake ONLY the network boundary — Http.json/multipart/download_to/
# with_retries are overridden with an in-memory transport, so the request
# shapes, response parsing, error surfacing, and the LocalProvider SVG pipeline
# are all exercised against production code with zero network and no bundler:
#
#     ruby -Ilib test/ruby/test_providers.rb
#
# Additionally:
#   - adapt_openai_size_quality is DIFFERENTIAL-tested against the Python oracle
#     across its full model x size x quality matrix (it is pure), and
#   - LocalProvider is run for real end-to-end (render -> sanitize -> rasterize)
#     and asserted to yield a signature-valid PNG.

require "minitest/autorun"
require "base64"
require "zlib"
require "json"
require "pathname"
require "tmpdir"
require "fileutils"
require "open3"

# Real sibling slices (dependency order). Not all.rb — that also pulls in slices
# still landing (library, freesvg); the provider layer needs only these.
%w[
  logging constants settings http
  svg/sanitizer svg/local_renderer svg/rasterizer
  providers
].each { |mod| require "zer0_image_generator/#{mod}" }

Z = Zer0ImageGenerator

# --- Faked network transport -------------------------------------------------
# An in-memory recorder that stands in for the real HTTP calls. The real
# HttpStatusError class and Http module are otherwise untouched, so error
# surfacing is tested against production behavior.
module FakeHttp
  class << self
    attr_accessor :calls, :next_response, :error_to_raise, :downloads

    def reset!
      @calls = []
      @next_response = nil
      @error_to_raise = nil
      @downloads = []
    end

    def last
      @calls.last
    end
  end
end
FakeHttp.reset!

Z::Http.define_singleton_method(:with_retries) do |_what, **_opts, &block|
  # The real one retries + sleeps on transient failures; the fake yields once so
  # error surfacing is observed immediately and deterministically.
  block.call
end

Z::Http.define_singleton_method(:json) do |url, payload, headers, timeout:|
  FakeHttp.calls << { kind: :json, url: url, payload: payload,
                      headers: headers, timeout: timeout }
  raise FakeHttp.error_to_raise if FakeHttp.error_to_raise

  FakeHttp.next_response
end

Z::Http.define_singleton_method(:multipart) do |url, fields, files, headers, timeout:|
  FakeHttp.calls << { kind: :multipart, url: url, fields: fields, files: files,
                      headers: headers, timeout: timeout }
  raise FakeHttp.error_to_raise if FakeHttp.error_to_raise

  FakeHttp.next_response
end

Z::Http.define_singleton_method(:download_to) do |url, dest, **_opts|
  FakeHttp.downloads << { url: url, dest: dest.to_s }
  File.binwrite(dest.to_s, "DOWNLOADED-BYTES")
end

# Silence the real logger (route both streams to /dev/null) so provider debug/
# warn/info side effects don't spam the test output.
_null = File.open(File::NULL, "w")
Z::Logging.logger = Z::Logger.new(
  sink: Z::StreamSink.new(out: _null, err: _null)
)

module ProviderTestHelpers
  def setup
    FakeHttp.reset!
    @tmp = Dir.mktmpdir("zer0-providers")
    @out_base = Pathname.new(@tmp).join("my-slug")
  end

  def teardown
    FileUtils.remove_entry(@tmp) if @tmp && File.directory?(@tmp)
  end

  def b64(str)
    Base64.strict_encode64(str)
  end

  def status_error(status, message)
    # Real HttpStatusError parses the JSON body for error.message — build a body
    # that error_message() will surface exactly.
    Z::HttpStatusError.new(status, JSON.dump("error" => { "message" => message }),
                           "https://example.test")
  end

  def ctx(env)
    Z::RunContext.new(project_root: Pathname.new(@tmp), env: env, slug: "my-slug")
  end
end

class TestAdaptOpenAISizeQuality < Minitest::Test
  ORACLE_DIR = File.expand_path("../../lib/zer0_image_generator", __dir__)

  MODELS = [
    "gpt-image-2", "gpt-image-1", "gpt-image-0", "dall-e-3", "dall-e-2",
    "grok-2-image", "stable-diffusion-xl-1024-v1-0", "gemini-2.5-flash-image", ""
  ].freeze
  SIZES = [
    "1792x1024", "1536x1024", "1024x1024", "1024x1792", "1024x1536", "auto", "512x512"
  ].freeze
  QUALITIES = ["auto", "standard", "hd", "low", "medium", "high", ""].freeze

  def combos
    MODELS.product(SIZES, QUALITIES)
  end

  def test_documented_remaps
    assert_equal ["1536x1024", "auto"],
                 Z.adapt_openai_size_quality("gpt-image-2", "1792x1024", "auto")
    assert_equal ["1024x1024", "standard"],
                 Z.adapt_openai_size_quality("dall-e-3", "1024x1024", "auto")
    # gpt-image only remaps the 1792x1024 size; dall-e only remaps auto quality.
    assert_equal ["1024x1024", "auto"],
                 Z.adapt_openai_size_quality("gpt-image-2", "1024x1024", "auto")
    assert_equal ["1792x1024", "hd"],
                 Z.adapt_openai_size_quality("dall-e-3", "1792x1024", "hd")
    # A non-openai model passes through untouched.
    assert_equal ["1792x1024", "auto"],
                 Z.adapt_openai_size_quality("grok-2-image", "1792x1024", "auto")
  end

  def test_differential_against_python_oracle
    skip "python3 not available" unless system("python3", "--version",
                                               out: File::NULL, err: File::NULL)

    all = combos
    ruby_results = all.map { |m, s, q| Z.adapt_openai_size_quality(m, s, q) }

    code = <<~PY
      import sys, os, json
      sys.path.insert(0, os.environ["ORACLE_DIR"])
      import preview_generator as pg
      combos = json.load(sys.stdin)
      print(json.dumps([list(pg.adapt_openai_size_quality(*c)) for c in combos]))
    PY
    out, status = Open3.capture2(
      { "ORACLE_DIR" => ORACLE_DIR }, "python3", "-c", code,
      stdin_data: JSON.dump(all)
    )
    assert status.success?, "oracle invocation failed"

    assert_equal JSON.parse(out), ruby_results,
                 "adapt_openai_size_quality diverged from the Python oracle"
    assert_equal 441, ruby_results.length
  end
end

class TestOpenAIProvider < Minitest::Test
  include ProviderTestHelpers

  def provider
    Z::PROVIDERS["openai"]
  end

  def gen_settings
    Z::Settings.new(size: "1792x1024", quality: "auto", model: "")
  end

  def test_is_configured
    assert provider.is_configured("OPENAI_API_KEY" => "x")
    refute provider.is_configured("OPENAI_API_KEY" => "")
    refute provider.is_configured({})
  end

  def test_generate_request_shape_and_b64_response
    FakeHttp.next_response = { "data" => [{ "b64_json" => b64("PNGPAYLOAD") }] }
    result = provider.generate("a prompt", gen_settings, @out_base,
                               ctx("OPENAI_API_KEY" => "sk-test"))

    call = FakeHttp.last
    assert_equal :json, call[:kind]
    assert_equal "https://api.openai.com/v1/images/generations", call[:url]
    assert_equal 900, call[:timeout]
    assert_equal({ "Authorization" => "Bearer sk-test" }, call[:headers])
    # effective_model -> default gpt-image-2; adapt remaps 1792x1024 -> 1536x1024.
    assert_equal(
      { "model" => "gpt-image-2", "prompt" => "a prompt", "n" => 1,
        "size" => "1536x1024", "quality" => "auto" },
      call[:payload]
    )

    assert result.ok
    assert_equal "png", result.kind
    assert_equal @out_base.sub_ext(".png"), result.path
    assert_equal "PNGPAYLOAD", File.binread(result.path.to_s)
  end

  def test_generate_url_response_downloads
    FakeHttp.next_response = { "data" => [{ "url" => "https://img.example/x.png" }] }
    result = provider.generate("p", gen_settings, @out_base,
                               ctx("OPENAI_API_KEY" => "sk-test"))

    assert result.ok
    assert_equal 1, FakeHttp.downloads.length
    assert_equal "https://img.example/x.png", FakeHttp.downloads.first[:url]
    assert_equal "DOWNLOADED-BYTES", File.binread(result.path.to_s)
  end

  def test_generate_empty_data_is_error
    FakeHttp.next_response = { "data" => [] }
    result = provider.generate("p", gen_settings, @out_base,
                               ctx("OPENAI_API_KEY" => "sk-test"))
    refute result.ok
    assert_equal "No image data in OpenAI response", result.error
  end

  def test_generate_entry_without_payload_is_error
    FakeHttp.next_response = { "data" => [{ "revised_prompt" => "x" }] }
    result = provider.generate("p", gen_settings, @out_base,
                               ctx("OPENAI_API_KEY" => "sk-test"))
    refute result.ok
    assert_equal "No image data in OpenAI response", result.error
  end

  def test_generate_http_status_error_surfaced
    FakeHttp.error_to_raise = status_error(429, "rate limited")
    result = provider.generate("p", gen_settings, @out_base,
                               ctx("OPENAI_API_KEY" => "sk-test"))
    refute result.ok
    assert_equal "OpenAI API error: rate limited", result.error
  end

  def test_generate_generic_error_surfaced
    FakeHttp.error_to_raise = RuntimeError.new("boom")
    result = provider.generate("p", gen_settings, @out_base,
                               ctx("OPENAI_API_KEY" => "sk-test"))
    refute result.ok
    assert_equal "boom", result.error
  end

  def test_edit_gpt_image_2_omits_input_fidelity
    src = Pathname.new(@tmp).join("orig.png")
    File.binwrite(src.to_s, "ORIGINAL")
    FakeHttp.next_response = {
      "data" => [{ "b64_json" => b64("EDITED") }],
      "usage" => { "total_tokens" => 5 },
    }
    settings = Z::Settings.new(
      enhance_model: "gpt-image-2", enhance_quality: "high",
      enhance_fidelity: "high", enhance_format: "png"
    )
    result = provider.edit(src, "enhance please", settings,
                           ctx("OPENAI_API_KEY" => "sk-test"))

    call = FakeHttp.last
    assert_equal :multipart, call[:kind]
    assert_equal "https://api.openai.com/v1/images/edits", call[:url]
    assert_equal 900, call[:timeout]
    assert_equal({ "Authorization" => "Bearer sk-test" }, call[:headers])
    assert_equal(
      { "prompt" => "enhance please", "model" => "gpt-image-2", "n" => "1",
        "size" => "auto", "quality" => "high", "output_format" => "png" },
      call[:fields]
    )
    refute call[:fields].key?("input_fidelity")
    assert_equal [["image[]", "orig.png", "ORIGINAL", "image/png"]], call[:files]

    assert result.ok
    # out_path defaults to the source image (in-place enhance).
    assert_equal src, result.path
    assert_equal "EDITED", File.binread(src.to_s)
  end

  def test_edit_non_gpt_image_2_includes_input_fidelity_and_honors_out_path
    src = Pathname.new(@tmp).join("orig.png")
    File.binwrite(src.to_s, "ORIGINAL")
    FakeHttp.next_response = { "data" => [{ "b64_json" => b64("E2") }] }
    settings = Z::Settings.new(
      enhance_model: "gpt-image-1", enhance_quality: "auto",
      enhance_fidelity: "low", enhance_format: "webp"
    )
    dest = Pathname.new(@tmp).join("out.webp")
    result = provider.edit(src, "p", settings,
                           ctx("OPENAI_API_KEY" => "sk-test"), dest)

    fields = FakeHttp.last[:fields]
    assert_equal "low", fields["input_fidelity"]
    assert_equal "webp", fields["output_format"]
    assert_equal "gpt-image-1", fields["model"]
    assert_equal dest, result.path
    assert_equal "E2", File.binread(dest.to_s)
  end

  def test_edit_status_error_uses_enhance_message
    src = Pathname.new(@tmp).join("orig.png")
    File.binwrite(src.to_s, "ORIGINAL")
    FakeHttp.error_to_raise = status_error(400, "bad request")
    settings = Z::Settings.new(
      enhance_model: "gpt-image-2", enhance_quality: "high",
      enhance_fidelity: "high", enhance_format: "png"
    )
    result = provider.edit(src, "p", settings, ctx("OPENAI_API_KEY" => "sk-test"))
    refute result.ok
    assert_equal "OpenAI enhance API error: bad request", result.error
  end
end

class TestXAIProvider < Minitest::Test
  include ProviderTestHelpers

  def provider
    Z::PROVIDERS["xai"]
  end

  def test_generate_request_shape_and_prompt_cap
    long_prompt = "x" * 1500
    FakeHttp.next_response = { "data" => [{ "b64_json" => b64("GROK") }] }
    result = provider.generate(long_prompt, Z::Settings.new(model: ""),
                               @out_base, ctx("XAI_API_KEY" => "xai-key"))

    call = FakeHttp.last
    assert_equal "https://api.x.ai/v1/images/generations", call[:url]
    assert_equal({ "Authorization" => "Bearer xai-key" }, call[:headers])
    assert_equal "grok-2-image", call[:payload]["model"]
    assert_equal 1, call[:payload]["n"]
    # Prompt is sliced to the first 1000 characters.
    assert_equal 1000, call[:payload]["prompt"].length
    assert_equal "x" * 1000, call[:payload]["prompt"]

    assert result.ok
    assert_equal "GROK", File.binread(result.path.to_s)
  end

  def test_generate_error_prefix
    FakeHttp.error_to_raise = status_error(500, "upstream down")
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx("XAI_API_KEY" => "k"))
    refute result.ok
    assert_equal "xAI API error: upstream down", result.error
  end

  def test_edit_unsupported
    err = assert_raises(Z::EditUnsupported) do
      provider.edit(Pathname.new("x.png"), "p", Z::Settings.new, ctx({}))
    end
    assert_equal "xai", err.provider
  end
end

class TestStabilityProvider < Minitest::Test
  include ProviderTestHelpers

  def provider
    Z::PROVIDERS["stability"]
  end

  def test_generate_request_shape_and_artifacts
    FakeHttp.next_response = { "artifacts" => [{ "base64" => b64("STABLE") }] }
    result = provider.generate("a prompt", Z::Settings.new, @out_base,
                               ctx("STABILITY_API_KEY" => "st-key"))

    call = FakeHttp.last
    assert_equal(
      "https://api.stability.ai/v1/generation/" \
      "stable-diffusion-xl-1024-v1-0/text-to-image",
      call[:url]
    )
    assert_equal({ "Authorization" => "Bearer st-key" }, call[:headers])
    assert_equal(
      { "text_prompts" => [{ "text" => "a prompt" }], "cfg_scale" => 7,
        "height" => 1024, "width" => 1024, "samples" => 1, "steps" => 30 },
      call[:payload]
    )

    assert result.ok
    assert_equal "png", result.kind
    assert_equal "STABLE", File.binread(result.path.to_s)
  end

  def test_generate_no_artifacts_is_error
    FakeHttp.next_response = { "artifacts" => [] }
    result = provider.generate("p", Z::Settings.new, @out_base,
                               ctx("STABILITY_API_KEY" => "k"))
    refute result.ok
    assert_equal "No image data in Stability response", result.error
  end

  def test_generate_error_prefix
    FakeHttp.error_to_raise = status_error(401, "unauthorized")
    result = provider.generate("p", Z::Settings.new, @out_base,
                               ctx("STABILITY_API_KEY" => "k"))
    refute result.ok
    assert_equal "Stability API error: unauthorized", result.error
  end
end

class TestGeminiProvider < Minitest::Test
  include ProviderTestHelpers

  def provider
    Z::PROVIDERS["gemini"]
  end

  def inline_response(key)
    { "candidates" => [
      { "content" => { "parts" => [{ key => { "data" => b64("GEMINI") } }] } },
    ] }
  end

  def test_generate_request_shape_and_inlineData
    FakeHttp.next_response = inline_response("inlineData")
    result = provider.generate("a prompt", Z::Settings.new(model: ""),
                               @out_base, ctx("GEMINI_API_KEY" => "g-key"))

    call = FakeHttp.last
    assert_equal(
      "https://generativelanguage.googleapis.com/v1beta/models/" \
      "gemini-2.5-flash-image:generateContent",
      call[:url]
    )
    assert_equal({ "x-goog-api-key" => "g-key" }, call[:headers])
    assert_equal(
      { "contents" => [{ "parts" => [{ "text" => "a prompt" }] }] },
      call[:payload]
    )

    assert result.ok
    assert_equal "GEMINI", File.binread(result.path.to_s)
  end

  def test_generate_accepts_snake_case_inline_data
    FakeHttp.next_response = inline_response("inline_data")
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx("GEMINI_API_KEY" => "g"))
    assert result.ok
    assert_equal "GEMINI", File.binread(result.path.to_s)
  end

  def test_generate_no_inline_data_is_error
    FakeHttp.next_response = { "candidates" => [{ "content" => { "parts" => [{ "text" => "hi" }] } }] }
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx("GEMINI_API_KEY" => "g"))
    refute result.ok
    assert_equal "No inline image data in Gemini response", result.error
  end

  def test_generate_error_prefix
    FakeHttp.error_to_raise = status_error(503, "overloaded")
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx("GEMINI_API_KEY" => "g"))
    refute result.ok
    assert_equal "Gemini API error: overloaded", result.error
  end
end

# LocalProvider is exercised against the REAL svg slice (LocalRenderer ->
# Sanitizer -> Rasterizer); no network and no fakes on that path.
class TestLocalProvider < Minitest::Test
  include ProviderTestHelpers

  PNG_SIGNATURE = "\x89PNG\r\n\x1a\n".b

  def provider
    Z::PROVIDERS["local"]
  end

  def project_ctx(slug)
    Z::RunContext.new(project_root: Pathname.new(File.expand_path("../..", __dir__)),
                      env: {}, slug: slug)
  end

  def test_is_configured_always_true
    assert provider.is_configured({})
    assert_equal "template-svg", provider.default_model
    assert_equal "", provider.missing_hint({})
  end

  def test_generate_end_to_end_produces_valid_png
    result = provider.generate("ignored", Z::Settings.new(rasterizer: "auto"),
                               @out_base, project_ctx("hello-world"))

    if result.kind == "png"
      assert result.ok
      assert_equal @out_base.sub_ext(".png"), result.path
      bytes = File.binread(result.path.to_s)
      assert_equal PNG_SIGNATURE, bytes[0, 8], "output must be a signature-valid PNG"
      refute File.exist?(@out_base.sub_ext(".svg").to_s), "svg is removed once rasterized"
    else
      # No rasterizer on this host: the .svg preview is kept (still a success).
      skip "no SVG rasterizer available — png branch not exercisable here"
    end
  end

  def test_generate_keeps_svg_when_rasterizer_disabled
    result = provider.generate("ignored", Z::Settings.new(rasterizer: "none"),
                               @out_base, project_ctx("hello-world"))
    assert result.ok
    assert_equal "svg", result.kind
    assert_equal @out_base.sub_ext(".svg"), result.path
    assert_match(/<svg/, File.read(result.path.to_s))
  end

  def test_seed_and_title_wiring_non_empty_slug
    # rasterizer none keeps the .svg so we can compare it byte-for-byte against a
    # direct render+sanitize: this pins title = slug and seed = crc32(slug).
    expected, = Z::Svg::Sanitizer.sanitize_svg(
      Z::Svg::LocalRenderer.render_local_svg(
        "abc", Z::Svg::LocalRenderer.seed_for("abc")
      )
    )
    result = provider.generate("ignored", Z::Settings.new(rasterizer: "none"),
                               @out_base, project_ctx("abc"))
    assert_equal expected, File.read(result.path.to_s)
  end

  def test_empty_slug_seeds_from_stem_and_titles_with_empty_string
    # out_base stem is "my-slug"; an empty slug titles the banner with "" but
    # derives the seed from the stem.
    expected, = Z::Svg::Sanitizer.sanitize_svg(
      Z::Svg::LocalRenderer.render_local_svg(
        "", Z::Svg::LocalRenderer.seed_for("my-slug")
      )
    )
    result = provider.generate("ignored", Z::Settings.new(rasterizer: "none"),
                               @out_base, project_ctx(""))
    assert_equal expected, File.read(result.path.to_s)
  end

  def test_finish_svg_surfaces_sanitize_error
    # Directly drive the mixin tail with unusable SVG: the real Sanitizer raises
    # SvgError, which finish_svg converts to a failed ImageResult.
    result = provider.finish_svg("<html></html>", @out_base,
                                 Z::Settings.new(rasterizer: "none"),
                                 project_ctx("x"))
    refute result.ok
    refute_nil result.error
    assert_match(/not <svg>/, result.error)
  end

  def test_edit_is_a_no_op_success
    src = Pathname.new(@tmp).join("orig.png")
    File.binwrite(src.to_s, "ORIGINAL")
    result = provider.edit(src, "long prompt", Z::Settings.new, ctx({}))
    assert result.ok
    assert_equal "png", result.kind
    assert_equal src, result.path
    # Source is untouched — the local provider does no real work.
    assert_equal "ORIGINAL", File.binread(src.to_s)
  end
end

class TestRunContext < Minitest::Test
  def test_with_slug_isolates_slug_but_shares_services
    env = { "OPENAI_API_KEY" => "k" }
    root = Pathname.new("/repo")
    client = Object.new
    base = Z::RunContext.new(project_root: root, env: env, anthropic: client, slug: "a")

    copy = base.with_slug("b")

    assert_equal "a", base.slug
    assert_equal "b", copy.slug
    # env / project_root / anthropic are shared by reference (thread-safe: env is
    # read-only, the client is stateless post-init) — only slug is per-file.
    assert_same env, copy.env
    assert_same root, copy.project_root
    assert_same client, copy.anthropic
    refute_same base, copy
  end

  def test_claude_is_lazily_memoized
    client = Object.new
    ctx = Z::RunContext.new(project_root: Pathname.new("/r"), env: {}, anthropic: client)
    assert_same client, ctx.claude
  end
end
