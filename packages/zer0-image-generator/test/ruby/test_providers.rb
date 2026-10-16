# frozen_string_literal: true

# Integration tests for the image-provider layer.
#
# These run the REAL sibling slices (logging, constants, settings, http, svg)
# and fake ONLY the network boundary — Http.json/multipart/request/download_to/
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
  providers grok/client
].each { |mod| require "zer0_image_generator/#{mod}" }

Z = Zer0ImageGenerator

# --- Faked network transport -------------------------------------------------
# An in-memory recorder that stands in for the real HTTP calls. The real
# HttpStatusError class and Http module are otherwise untouched, so error
# surfacing is tested against production behavior.
module FakeHttp
  class << self
    attr_accessor :calls, :next_response, :error_to_raise, :downloads, :script

    def reset!
      @calls = []
      @next_response = nil
      @error_to_raise = nil
      @downloads = []
      @script = nil
    end

    def last
      @calls.last
    end

    # A scripted sequence (exceptions and/or response hashes, one per call)
    # wins over the single canned response, so a test can make the first
    # attempt fail and the second succeed — the xAI OAuth -> API-key fallback.
    def deliver
      entry = @script && !@script.empty? ? @script.shift : (@error_to_raise || @next_response)
      raise entry if entry.is_a?(Exception)

      entry
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
  FakeHttp.deliver
end

Z::Http.define_singleton_method(:multipart) do |url, fields, files, headers, timeout:|
  FakeHttp.calls << { kind: :multipart, url: url, fields: fields, files: files,
                      headers: headers, timeout: timeout }
  FakeHttp.deliver
end

# The raw request is only reached by the xAI OAuth refresh (a form POST to
# auth.x.ai); scripted entries answer 200 with that hash as JSON.
Z::Http.define_singleton_method(:request) do |url, method: "GET", headers: nil, data: nil, timeout: 120|
  FakeHttp.calls << { kind: :request, url: url, method: method, headers: headers,
                      data: data, timeout: timeout }
  [200, {}, JSON.generate(FakeHttp.deliver).b]
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

  # Every env in this class carries HOME so credential-file discovery stays
  # inside the tmpdir — a real ~/.grok/auth.json on the machine running the
  # suite must never change what these assert.
  def env(**overrides)
    { "HOME" => @tmp }.merge(overrides.transform_keys(&:to_s))
  end

  # Write a Grok OAuth credentials file at the default location under HOME.
  def write_credentials_file(payload, rel = ".grok/auth.json")
    path = File.join(@tmp, rel)
    FileUtils.mkdir_p(File.dirname(path))
    File.write(path, JSON.dump(payload))
    path
  end

  def ok_response
    { "data" => [{ "b64_json" => b64("GROK") }] }
  end

  def test_generate_request_shape_and_prompt_cap
    long_prompt = "x" * 1500
    FakeHttp.next_response = ok_response
    result = provider.generate(long_prompt, Z::Settings.new(model: ""),
                               @out_base, ctx(env("XAI_API_KEY" => "xai-key")))

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

  def test_imagine_model_is_sent_the_banner_aspect_ratio
    FakeHttp.next_response = ok_response
    provider.generate("p", Z::Settings.new(model: "grok-imagine-image-2.0", size: "1536x1024"),
                      @out_base, ctx(env("XAI_API_KEY" => "xai-key")))
    assert_equal "grok-imagine-image-2.0", FakeHttp.last[:payload]["model"]
    assert_equal "3:2", FakeHttp.last[:payload]["aspect_ratio"]

    # grok-2-image predates the parameter: its request shape is unchanged.
    FakeHttp.next_response = ok_response
    provider.generate("p", Z::Settings.new(model: "", size: "1536x1024"),
                      @out_base, ctx(env("XAI_API_KEY" => "xai-key")))
    assert_equal "grok-2-image", FakeHttp.last[:payload]["model"]
    refute FakeHttp.last[:payload].key?("aspect_ratio")
  end

  def test_jpeg_render_is_saved_under_a_jpg_name
    FakeHttp.next_response = { "data" => [{ "b64_json" => b64("\xff\xd8\xff\xe0JFIF".b) }] }
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx(env("XAI_API_KEY" => "k")))

    assert result.ok
    assert_equal ["jpg", "my-slug.jpg"], [result.kind, result.path.basename.to_s]
    assert File.file?(result.path.to_s)
    refute File.exist?(@out_base.sub_ext(".png").to_s)
  end

  def test_image_media_type_reads_the_bytes
    assert_equal "image/jpeg", Z.image_media_type("\xff\xd8\xff\xe0".b)
    assert_equal "image/webp", Z.image_media_type("RIFF\x00\x00\x00\x00WEBPVP8 ".b)
    assert_equal "image/png", Z.image_media_type(Z::PNG_SIGNATURE)
    assert_equal "image/png", Z.image_media_type("")
  end

  def test_grok_review_labels_a_jpeg_as_jpeg
    image = File.join(@tmp, "render.jpg")
    File.binwrite(image, "\xff\xd8\xff\xe0JFIF".b)
    FakeHttp.next_response = { "choices" => [{ "message" => { "content" => "{}" } }] }
    Z::GrokClient.new(env("XAI_API_KEY" => "k")).complete_vision("s", "u", image)

    url = FakeHttp.last[:payload]["messages"][1]["content"][0]["image_url"]["url"]
    assert url.start_with?("data:image/jpeg;base64,")
  end

  def test_aspect_ratio_is_the_nearest_imagine_ratio
    imagine = "grok-imagine-image-2.0"
    assert_equal "16:9", Z::XAIAuth.aspect_ratio(imagine, "1792x1024")
    assert_equal "2:3", Z::XAIAuth.aspect_ratio(imagine, "1024x1536")
    assert_equal "1:1", Z::XAIAuth.aspect_ratio(imagine, "1024x1024")
    assert_nil Z::XAIAuth.aspect_ratio(imagine, "auto")
    assert_nil Z::XAIAuth.aspect_ratio(imagine, "0x1024")
    assert_nil Z::XAIAuth.aspect_ratio("grok-2-image", "1536x1024")
  end

  def test_generate_error_prefix
    FakeHttp.error_to_raise = status_error(500, "upstream down")
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx(env("XAI_API_KEY" => "k")))
    refute result.ok
    assert_equal "xAI API error: upstream down", result.error
  end

  def test_edit_unsupported
    err = assert_raises(Z::EditUnsupported) do
      provider.edit(Pathname.new("x.png"), "p", Z::Settings.new, ctx({}))
    end
    assert_equal "xai", err.provider
  end

  # -- OAuth -----------------------------------------------------------------

  def test_oauth_token_is_preferred_over_the_api_key
    FakeHttp.next_response = ok_response
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx(env("XAI_OAUTH_TOKEN" => "oauth-tok",
                                       "XAI_API_KEY" => "xai-key")))

    assert result.ok
    assert_equal 1, FakeHttp.calls.length
    assert_equal({ "Authorization" => "Bearer oauth-tok" }, FakeHttp.last[:headers])
  end

  def test_grok_oauth_token_alias
    FakeHttp.next_response = ok_response
    provider.generate("p", Z::Settings.new(model: ""), @out_base,
                      ctx(env("GROK_OAUTH_TOKEN" => "grok-tok")))
    assert_equal({ "Authorization" => "Bearer grok-tok" }, FakeHttp.last[:headers])
  end

  def test_rejected_oauth_token_falls_back_to_the_api_key
    FakeHttp.script = [status_error(401, "invalid token"), ok_response]
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx(env("XAI_OAUTH_TOKEN" => "stale",
                                       "XAI_API_KEY" => "xai-key")))

    assert result.ok, "the API key should have rendered after the OAuth rejection"
    assert_equal 2, FakeHttp.calls.length
    assert_equal({ "Authorization" => "Bearer stale" }, FakeHttp.calls[0][:headers])
    assert_equal({ "Authorization" => "Bearer xai-key" }, FakeHttp.calls[1][:headers])
    assert_equal "GROK", File.binread(result.path.to_s)
  end

  def test_forbidden_oauth_token_also_falls_back
    FakeHttp.script = [status_error(403, "forbidden"), ok_response]
    assert provider.generate("p", Z::Settings.new(model: ""), @out_base,
                             ctx(env("XAI_OAUTH_TOKEN" => "t",
                                     "XAI_API_KEY" => "k"))).ok
    assert_equal 2, FakeHttp.calls.length
  end

  def test_rejected_oauth_token_without_an_api_key_surfaces_the_error
    FakeHttp.error_to_raise = status_error(401, "invalid token")
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx(env("XAI_OAUTH_TOKEN" => "stale")))

    refute result.ok
    assert_equal "xAI API error: invalid token", result.error
    assert_equal 1, FakeHttp.calls.length
  end

  def test_non_auth_failures_never_burn_the_fallback
    # A 500 is the endpoint failing, not the credential — swapping tokens would
    # only double the load on an already-struggling API.
    FakeHttp.error_to_raise = status_error(500, "upstream down")
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx(env("XAI_OAUTH_TOKEN" => "t", "XAI_API_KEY" => "k")))

    refute result.ok
    assert_equal "xAI API error: upstream down", result.error
    assert_equal 1, FakeHttp.calls.length
  end

  def test_kilo_access_alias_is_accepted
    write_credentials_file("xai" => { "access" => "kilo-tok",
                                      "expires" => (Time.now.to_i + 3600) * 1000 })
    FakeHttp.next_response = ok_response
    provider.generate("p", Z::Settings.new(model: ""), @out_base, ctx(env))
    assert_equal({ "Authorization" => "Bearer kilo-tok" }, FakeHttp.last[:headers])
  end

  def test_oauth_credentials_file_is_read_when_no_token_env_is_set
    write_credentials_file("access_token" => "file-tok",
                           "expires_at" => Time.now.to_i + 3600)
    FakeHttp.next_response = ok_response
    assert provider.generate("p", Z::Settings.new(model: ""), @out_base,
                             ctx(env)).ok
    assert_equal({ "Authorization" => "Bearer file-tok" }, FakeHttp.last[:headers])
  end

  def test_nested_and_millisecond_expiry_shapes_are_accepted
    write_credentials_file("xai" => { "access_token" => "nested-tok",
                                      "expires_at" => (Time.now.to_i + 3600) * 1000 })
    FakeHttp.next_response = ok_response
    provider.generate("p", Z::Settings.new(model: ""), @out_base, ctx(env))
    assert_equal({ "Authorization" => "Bearer nested-tok" }, FakeHttp.last[:headers])
  end

  def test_expired_file_token_is_treated_as_absent
    write_credentials_file("access_token" => "expired-tok",
                           "expires_at" => Time.now.to_i - 10)
    FakeHttp.next_response = ok_response
    provider.generate("p", Z::Settings.new(model: ""), @out_base,
                      ctx(env("XAI_API_KEY" => "xai-key")))

    # No wasted request on a token we already know is dead.
    assert_equal 1, FakeHttp.calls.length
    assert_equal({ "Authorization" => "Bearer xai-key" }, FakeHttp.last[:headers])
  end

  # --- refresh: an expired token whose store can renew it (Kilo Code's login) ---

  KILO = ".local/share/kilo/auth.json"

  def write_kilo_store(**slot)
    record = { "type" => "oauth", "access" => "old-tok", "refresh" => "old-refresh",
               "client_id" => "kilo-client",
               "expires" => ((Time.now.to_f - 60) * 1000).to_i }
    record.merge!(slot.transform_keys(&:to_s))
    path = write_credentials_file({ "xai" => record, "other" => { "keep" => 1 } }, KILO)
    File.chmod(0o600, path)
    path
  end

  def jwt(claims)
    body = [JSON.dump(claims)].pack("m0").tr("+/", "-_").delete("=")
    "e30.#{body}.sig"
  end

  def refresh_calls
    FakeHttp.calls.select { |call| call[:kind] == :request }
  end

  def image_calls
    FakeHttp.calls.select { |call| call[:kind] == :json }
  end

  def test_expired_kilo_token_is_refreshed_and_saved_in_its_own_shape
    path = write_kilo_store
    FakeHttp.script = [{ "access_token" => "new-tok", "refresh_token" => "new-refresh",
                         "expires_in" => 7200 }, ok_response]
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base, ctx(env))

    assert result.ok
    assert_equal({ "Authorization" => "Bearer new-tok" }, image_calls[0][:headers])
    assert_equal 1, refresh_calls.length
    assert_equal "https://auth.x.ai/oauth2/token", refresh_calls[0][:url]
    assert_equal "POST", refresh_calls[0][:method]
    assert_equal({ "grant_type" => ["refresh_token"], "refresh_token" => ["old-refresh"],
                   "client_id" => ["kilo-client"] },
                 URI.decode_www_form(refresh_calls[0][:data]).group_by(&:first)
                    .transform_values { |pairs| pairs.map(&:last) })
    store = JSON.parse(File.read(path))
    slot = store["xai"]
    assert_equal ["new-tok", "new-refresh", "oauth"], slot.values_at("access", "refresh", "type")
    refute slot.key?("access_token")                        # Kilo's key names kept
    assert_operator slot["expires"], :>, (Time.now.to_f + 7000) * 1000  # still ms
    assert_equal({ "keep" => 1 }, store["other"])           # the rest of the store kept
    assert_equal 0o600, File.stat(path).mode & 0o777

    # The saved token is fresh, so the next run reads it without refreshing.
    FakeHttp.script = [ok_response]
    provider.generate("p", Z::Settings.new(model: ""), @out_base, ctx(env))
    assert_equal({ "Authorization" => "Bearer new-tok" }, image_calls.last[:headers])
    assert_equal 1, refresh_calls.length
  end

  def test_refresh_reads_client_id_from_the_jwt_when_the_store_has_none
    path = write_kilo_store(client_id: nil, access: jwt("aud" => ["jwt-client"]))
    FakeHttp.script = [{ "access_token" => "new-tok" }, ok_response]
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base, ctx(env))

    assert result.ok
    assert_includes refresh_calls[0][:data], "client_id=jwt-client"
    # No rotated refresh token in the answer: the stored one is kept.
    assert_equal "old-refresh", JSON.parse(File.read(path))["xai"]["refresh"]
  end

  def test_expired_refreshable_token_counts_as_configured_without_a_request
    path = write_kilo_store
    assert provider.is_configured(env)
    assert_equal "Grok OAuth token (#{path}; expired, refreshed on use)", Z::XAIAuth.describe(env)
    assert_empty FakeHttp.calls
  end

  def test_failed_refresh_falls_back_to_the_api_key
    path = write_kilo_store
    before = File.read(path)
    FakeHttp.script = [Z::HttpStatusError.new(400, '{"error":"invalid_grant"}',
                                              Z::XAIAuth::TOKEN_ENDPOINT), ok_response]
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base,
                               ctx(env("XAI_API_KEY" => "xai-key")))

    assert result.ok
    assert_equal({ "Authorization" => "Bearer xai-key" }, image_calls[0][:headers])
    assert_equal before, File.read(path)
  end

  def test_failed_refresh_without_a_fallback_is_an_error_not_a_request
    write_kilo_store
    FakeHttp.script = [Z::HttpStatusError.new(
      400, '{"error":"invalid_grant","error_description":"echoed input"}',
      Z::XAIAuth::TOKEN_ENDPOINT
    )]
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base, ctx(env))

    refute result.ok
    assert_equal "xAI OAuth refresh failed (HTTP 400: invalid_grant); re-run your Grok login",
                 result.error
    assert_empty image_calls
  end

  def test_iso_expiry_is_saved_as_iso
    path = write_credentials_file("access_token" => "old", "refresh_token" => "r",
                                  "client_id" => "c", "expires_at" => "2020-01-01T00:00:00Z")
    FakeHttp.script = [{ "access_token" => "new", "expires_in" => 3600 }, ok_response]
    provider.generate("p", Z::Settings.new(model: ""), @out_base, ctx(env))

    saved = JSON.parse(File.read(path))
    assert_equal "new", saved["access_token"]
    assert_match(/\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\z/, saved["expires_at"])
    refute_nil Z::XAIAuth.describe(env)
  end

  def test_grok_client_refreshes_before_its_first_call
    write_kilo_store
    FakeHttp.script = [{ "access_token" => "chat-tok", "expires_in" => 3600 },
                       { "choices" => [{ "message" => { "content" => "brief" } }] }]
    client = Z::GrokClient.new(env)

    assert client.available?
    assert_equal "brief", client.complete("sys", "user")
    assert_equal({ "Authorization" => "Bearer chat-tok" }, image_calls[0][:headers])
  end

  def test_expires_in_needs_an_issue_time_to_mean_anything
    # Lifetime alone cannot date a token, so the engine keeps it rather than
    # guessing it is stale.
    write_credentials_file("access_token" => "lifetime-only", "expires_in" => 3600)
    assert_equal "Grok OAuth token (#{File.join(@tmp, '.grok/auth.json')})",
                 provider.auth_description(env)

    write_credentials_file("access_token" => "aged",
                           "expires_in" => 3600,
                           "created_at" => "2020-01-01T00:00:00Z")
    assert_nil provider.auth_description(env)
  end

  def test_credentials_file_env_override_wins_outright
    write_credentials_file({ "access_token" => "default-location" })
    explicit = File.join(@tmp, "elsewhere", "grok.json")
    FileUtils.mkdir_p(File.dirname(explicit))
    File.write(explicit, JSON.dump("access_token" => "explicit-location"))

    FakeHttp.next_response = ok_response
    provider.generate("p", Z::Settings.new(model: ""), @out_base,
                      ctx(env("GROK_OAUTH_CREDENTIALS" => explicit)))
    assert_equal({ "Authorization" => "Bearer explicit-location" },
                 FakeHttp.last[:headers])

    # A configured-but-missing path must not silently fall back to ~/.grok.
    assert_nil provider.auth_description(
      env("GROK_OAUTH_CREDENTIALS" => File.join(@tmp, "nope.json"))
    )
  end

  def test_unreadable_credentials_file_is_skipped_not_fatal
    write_credentials_file("not json at all")               # a bare JSON string
    assert_nil provider.auth_description(env)
    File.write(File.join(@tmp, ".grok/auth.json"), "{{{ broken")
    assert_nil provider.auth_description(env)
    write_credentials_file("refresh_token" => "no access token here")
    assert_nil provider.auth_description(env)
  end

  def test_xai_auth_pins_one_rung
    pinned_key = env("XAI_AUTH" => "api_key", "XAI_OAUTH_TOKEN" => "t",
                     "XAI_API_KEY" => "k")
    assert_equal "XAI_API_KEY (xAI API key)", provider.auth_description(pinned_key)

    pinned_oauth = env("XAI_AUTH" => "oauth", "XAI_OAUTH_TOKEN" => "t",
                       "XAI_API_KEY" => "k")
    assert_equal "XAI_OAUTH_TOKEN (Grok OAuth token)",
                 provider.auth_description(pinned_oauth)
    refute provider.is_configured(env("XAI_AUTH" => "oauth", "XAI_API_KEY" => "k"))

    # An unknown value is not a hard error; it degrades to the default ladder.
    assert_equal "XAI_OAUTH_TOKEN (Grok OAuth token), falling back to " \
                 "XAI_API_KEY (xAI API key)",
                 provider.auth_description(env("XAI_AUTH" => "nonsense",
                                               "XAI_OAUTH_TOKEN" => "t",
                                               "XAI_API_KEY" => "k"))
  end

  def test_base_url_override
    FakeHttp.next_response = ok_response
    provider.generate("p", Z::Settings.new(model: ""), @out_base,
                      ctx(env("XAI_BASE_URL" => "https://gateway.test/v1/",
                              "XAI_OAUTH_TOKEN" => "t")))
    assert_equal "https://gateway.test/v1/images/generations", FakeHttp.last[:url]
  end

  def test_is_configured_and_missing_hint
    refute provider.is_configured(env)
    assert provider.is_configured(env("XAI_API_KEY" => "k"))
    assert provider.is_configured(env("XAI_OAUTH_TOKEN" => "t"))
    write_credentials_file("access_token" => "file-tok")
    assert provider.is_configured(env)

    hint = provider.missing_hint(env)
    assert_includes hint, "XAI_OAUTH_TOKEN"
    assert_includes hint, "XAI_API_KEY"
    assert_includes hint, "~/.grok/auth.json"
  end

  def test_generate_without_any_credential_reports_the_hint
    result = provider.generate("p", Z::Settings.new(model: ""), @out_base, ctx(env))
    refute result.ok
    assert_equal Z::XAIAuth::MISSING_HINT, result.error
    assert_empty FakeHttp.calls
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
