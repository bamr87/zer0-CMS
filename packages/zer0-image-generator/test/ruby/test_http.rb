# frozen_string_literal: true

# Unit + differential tests for the ported HTTP layer (lib/.../http.rb).
# Zero-network by construction: with_retries takes an injected sleeper and a
# plain block, HttpStatusError is pure parsing, build_multipart is pure, and the
# one test that exercises Http.request stubs the socket-touching internal. The
# differential half shells out to python3's build_multipart to prove the
# multipart body layout is byte-identical; it skips cleanly without python3.
#
#     ruby -Ilib test/ruby/test_http.rb

require "minitest/autorun"
require "json"
require "base64"
require "open3"
require_relative "../../lib/zer0_image_generator/http"

module HttpTestHelpers
  M = Zer0ImageGenerator
  ORACLE_DIR = File.expand_path("../../lib/zer0_image_generator", __dir__)

  def python_available?
    out, status = Open3.capture2e("python3", "--version")
    status.success? && out.include?("Python 3")
  rescue StandardError
    false
  end

  # A response double for the one test that drives Http.request without a socket.
  FakeResponse = Struct.new(:code_i, :body, :hdrs) do
    def code
      code_i.to_s
    end

    def [](key)
      (hdrs || {})[key]
    end

    def each_header(&block)
      (hdrs || {}).each(&block)
    end
  end
end

class TestHttpStatusError < Minitest::Test
  include HttpTestHelpers

  def test_status_is_stored
    exc = M::HttpStatusError.new(429, '{"error": {"message": "slow down"}}', "https://api")
    assert_equal 429, exc.status
  end

  def test_error_message_from_nested_error
    exc = M::HttpStatusError.new(429, '{"error": {"message": "slow down"}}', "https://api")
    assert_equal "slow down", exc.error_message
  end

  def test_error_message_from_bare_string_error
    exc = M::HttpStatusError.new(400, '{"error": "bad request"}', "https://api")
    assert_equal "bad request", exc.error_message
  end

  def test_error_message_from_detail
    exc = M::HttpStatusError.new(422, '{"detail": "nope"}', "https://api")
    assert_equal "nope", exc.error_message
  end

  def test_non_json_body_falls_back_to_raw
    exc = M::HttpStatusError.new(500, "<html>oops</html>", "https://api")
    assert_includes exc.error_message, "oops"
  end

  def test_exception_message_summarizes
    exc = M::HttpStatusError.new(429, '{"error": {"message": "slow down"}}', "https://api")
    assert_equal "HTTP 429 from https://api: slow down", exc.message
  end

  def test_retry_after_prefers_http_header
    exc = M::HttpStatusError.new(429, "{}", "https://api", { "Retry-After" => "31" })
    assert_in_delta 31.0, exc.retry_after
  end

  def test_retry_after_header_case_insensitive
    exc = M::HttpStatusError.new(429, "{}", "https://api", { "retry-after" => "5" })
    assert_in_delta 5.0, exc.retry_after
  end

  def test_retry_after_invalid_header_falls_through_to_json
    exc = M::HttpStatusError.new(429, "{}", "https://api", { "Retry-After" => "soon" })
    assert_in_delta 0.0, exc.retry_after
  end

  def test_retry_after_json_fallback
    exc = M::HttpStatusError.new(429, '{"retry_after": 7}', "https://api")
    assert_in_delta 7.0, exc.retry_after
  end

  def test_retry_after_default_zero
    exc = M::HttpStatusError.new(500, "x", "u")
    assert_in_delta 0.0, exc.retry_after
  end

  def test_json_parses_body
    exc = M::HttpStatusError.new(400, '{"a": 1}', "u")
    assert_equal({ "a" => 1 }, exc.json)
  end

  def test_json_returns_nil_on_garbage
    assert_nil M::HttpStatusError.new(400, "{broken", "u").json
  end
end

class TestWithRetries < Minitest::Test
  include HttpTestHelpers

  def recorder
    sleeps = []
    [sleeps, ->(seconds) { sleeps << seconds }]
  end

  def test_returns_value_without_retry_on_success
    sleeps, sleeper = recorder
    result = M::Http.with_retries("t", sleeper: sleeper) { "done" }
    assert_equal "done", result
    assert_empty sleeps
  end

  def test_retryable_status_retries_then_succeeds
    sleeps, sleeper = recorder
    calls = 0
    result = M::Http.with_retries("t", sleeper: sleeper) do
      calls += 1
      raise M::HttpStatusError.new(500, "{}", "u") if calls == 1

      "ok"
    end
    assert_equal "ok", result
    assert_equal 2, calls
    assert_equal [2.0], sleeps
  end

  def test_each_retryable_status_retries
    M::Http::RETRYABLE_STATUSES.each do |status|
      _, sleeper = recorder
      calls = 0
      result = M::Http.with_retries("t", sleeper: sleeper) do
        calls += 1
        raise M::HttpStatusError.new(status, "{}", "u") if calls == 1

        "ok"
      end
      assert_equal "ok", result, "status #{status} should retry"
      assert_equal 2, calls, "status #{status} should retry exactly once"
    end
  end

  def test_retry_after_header_wins_over_ladder
    sleeps, sleeper = recorder
    calls = 0
    M::Http.with_retries("t", sleeper: sleeper) do
      calls += 1
      raise M::HttpStatusError.new(429, "{}", "u", { "retry-after" => "5" }) if calls == 1

      "done"
    end
    assert_equal [5.0], sleeps
  end

  def test_retry_after_capped_at_60
    sleeps, sleeper = recorder
    calls = 0
    M::Http.with_retries("t", sleeper: sleeper) do
      calls += 1
      raise M::HttpStatusError.new(503, "{}", "u", { "retry-after" => "120" }) if calls == 1

      "done"
    end
    assert_equal [60.0], sleeps
  end

  def test_backoff_doubles
    sleeps, sleeper = recorder
    calls = 0
    M::Http.with_retries("t", sleeper: sleeper) do
      calls += 1
      raise M::HttpStatusError.new(500, "{}", "u") if calls < 4

      "done"
    end
    assert_equal [2.0, 4.0, 8.0], sleeps
  end

  def test_non_retryable_4xx_raises_immediately
    sleeps, sleeper = recorder
    calls = 0
    assert_raises(M::HttpStatusError) do
      M::Http.with_retries("t", sleeper: sleeper) do
        calls += 1
        raise M::HttpStatusError.new(404, "{}", "u")
      end
    end
    assert_equal 1, calls
    assert_empty sleeps
  end

  def test_400_does_not_retry
    calls = 0
    _, sleeper = recorder
    assert_raises(M::HttpStatusError) do
      M::Http.with_retries("t", sleeper: sleeper) do
        calls += 1
        raise M::HttpStatusError.new(400, "{}", "u")
      end
    end
    assert_equal 1, calls
  end

  def test_exhausts_attempts_and_reraises
    sleeps, sleeper = recorder
    calls = 0
    assert_raises(M::HttpStatusError) do
      M::Http.with_retries("t", sleeper: sleeper) do
        calls += 1
        raise M::HttpStatusError.new(500, "{}", "u")
      end
    end
    assert_equal 4, calls
    assert_equal [2.0, 4.0, 8.0], sleeps # 3 waits before the 4th (final) attempt
  end

  def test_transport_error_retries
    sleeps, sleeper = recorder
    calls = 0
    result = M::Http.with_retries("t", sleeper: sleeper) do
      calls += 1
      raise SocketError, "getaddrinfo failed" if calls < 3

      "recovered"
    end
    assert_equal "recovered", result
    assert_equal [2.0, 4.0], sleeps
  end

  def test_transport_error_exhausts_and_reraises
    _, sleeper = recorder
    assert_raises(Errno::ECONNRESET) do
      M::Http.with_retries("t", attempts: 2, sleeper: sleeper) do
        raise Errno::ECONNRESET
      end
    end
  end
end

class TestMultipartLayout < Minitest::Test
  include HttpTestHelpers

  def test_fields_and_files_encoded
    body, content_type = M::Http.build_multipart(
      { "prompt" => "hello" }, [["image[]", "a.png", "BYTES".b, "image/png"]]
    )
    assert_includes content_type, "multipart/form-data; boundary="
    boundary = content_type.split("boundary=")[1]
    assert_includes body, "--#{boundary}".b
    assert_includes body, %(name="prompt"\r\n\r\nhello).b
    assert_includes body, %(filename="a.png").b
    assert_includes body, "BYTES".b
    assert body.end_with?("--#{boundary}--\r\n".b)
  end

  def test_body_is_binary
    body, = M::Http.build_multipart({}, [["f", "x.bin", "\x00\x01\xff".b, "application/octet-stream"]])
    assert_equal Encoding::ASCII_8BIT, body.encoding
    assert_includes body, "\x00\x01\xff".b
  end

  # Differential: the body layout (CRLF placement, header order, terminator)
  # must match the oracle byte for byte once the random boundary is normalized.
  def test_layout_matches_python_oracle
    skip "python3 unavailable" unless python_available?

    fields = { "prompt" => "a vivid scene", "n" => "1", "unicode" => "café" }
    files = [
      ["image[]", "a.png", "\x89PNG\r\n\x1a\nBYTES".b, "image/png"],
      ["mask", "m.bin", "\x00\x01\x02\xfe\xff".b, "application/octet-stream"]
    ]

    rb_body, rb_ct = M::Http.build_multipart(fields, files)
    rb_boundary = rb_ct.split("boundary=")[1]

    py_body, py_boundary = python_multipart(fields, files)

    assert_equal normalize(py_body, py_boundary), normalize(rb_body, rb_boundary)
  end

  private

  def normalize(body, boundary)
    body.b.gsub(boundary.b, "BOUNDARY".b)
  end

  def python_multipart(fields, files)
    req = {
      "fields" => fields,
      "files" => files.map { |name, fn, content, mime| [name, fn, Base64.strict_encode64(content), mime] }
    }
    out, status = Open3.capture2("python3", "-c", PY_DRIVER, ORACLE_DIR, stdin_data: JSON.generate(req))
    raise "python driver failed: #{out}" unless status.success?

    res = JSON.parse(out)
    [Base64.strict_decode64(res["body_b64"]), res["boundary"]]
  end

  PY_DRIVER = <<~'PYSRC'
    import sys, json, base64
    sys.path.insert(0, sys.argv[1])
    import preview_generator as pg
    req = json.load(sys.stdin)
    files = [(n, fn, base64.b64decode(c), m) for n, fn, c, m in req["files"]]
    body, content_type = pg.build_multipart(req["fields"], files)
    boundary = content_type.split("boundary=", 1)[1]
    print(json.dumps({"body_b64": base64.b64encode(body).decode("ascii"), "boundary": boundary}))
  PYSRC
end

class TestHttpRequest < Minitest::Test
  include HttpTestHelpers

  # Minitest 6 dropped Object#stub, so swap the socket-touching internal by
  # hand: alias the original out, install the fake, always restore. This lets
  # the real Http.request/json/multipart status + parse logic run with no socket.
  def with_perform(fake)
    singleton = M::Http.singleton_class
    singleton.send(:alias_method, :__orig_perform, :perform)
    singleton.send(:define_method, :perform) { |*args| fake.call(*args) }
    yield
  ensure
    singleton.send(:alias_method, :perform, :__orig_perform)
    singleton.send(:remove_method, :__orig_perform)
    singleton.send(:private, :perform)
  end

  def test_2xx_returns_status_headers_body
    resp = FakeResponse.new(200, %({"ok": true}), { "content-type" => "application/json" })
    with_perform(->(*) { resp }) do
      status, headers, body = M::Http.request("https://api", method: "GET")
      assert_equal 200, status
      assert_equal "application/json", headers["content-type"]
      assert_equal %({"ok": true}), body
      assert_equal Encoding::ASCII_8BIT, body.encoding
    end
  end

  def test_non_2xx_raises_http_status_error
    resp = FakeResponse.new(500, %({"error": {"message": "boom"}}), {})
    with_perform(->(*) { resp }) do
      exc = assert_raises(M::HttpStatusError) { M::Http.request("https://api", method: "POST") }
      assert_equal 500, exc.status
      assert_equal "boom", exc.error_message
    end
  end

  # Every request names the engine unless the caller names a client: a CDN
  # rejects a stock client signature (Cloudflare `error code: 1010` on api.x.ai).
  def test_default_user_agent_and_caller_override
    seen = []
    resp = FakeResponse.new(200, "{}", {})
    with_perform(->(_uri, _method, headers, *) { seen << headers; resp }) do
      M::Http.request("https://api", method: "POST", headers: { "Accept" => "x" })
      M::Http.request("https://api", method: "POST", headers: { "user-agent" => "custom/1" })
    end
    assert_equal({ "Accept" => "x", "User-Agent" => "zer0-image-generator" }, seen[0])
    assert_equal({ "user-agent" => "custom/1" }, seen[1])
  end

  def test_json_posts_and_parses
    resp = FakeResponse.new(200, %({"stop_reason": "end_turn"}), {})
    with_perform(->(*) { resp }) do
      data = M::Http.json("https://api", { "model" => "m" }, { "x-api-key" => "k" })
      assert_equal({ "stop_reason" => "end_turn" }, data)
    end
  end

  def test_multipart_posts_and_parses
    resp = FakeResponse.new(200, %({"data": []}), {})
    with_perform(->(*) { resp }) do
      data = M::Http.multipart("https://api", { "prompt" => "p" },
                               [["image", "a.png", "X".b, "image/png"]], { "authorization" => "Bearer t" })
      assert_equal({ "data" => [] }, data)
    end
  end
end
