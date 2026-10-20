# frozen_string_literal: true

# Tests for the FreeSVG sourcing client, its tiered cache, and the library
# manifest reader/writer.
#
#     ruby -Ilib test/ruby/test_freesvg.rb
#
# No network and no bundler: the client takes an injectable transport and clock,
# so every request and every TTL boundary is exercised deterministically. Three
# layers:
#   1. The contract ported from test/test_freesvg.py (auth, cache tiers, fetch,
#      promote, prune, slugify) — same assertions, faked transport instead of a
#      mocked _http.
#   2. Byte-identity: the exact MANIFEST.json bytes `promote` writes are compared
#      against the real tools/svg/freesvg.py running the same input (oracle
#      driver), and PyJson is round-tripped against the committed manifest and
#      CPython's json.dumps. Skips cleanly without python3.
#   3. The added sanitizer security gate and 4xx/5xx/malformed error handling.

require "minitest/autorun"
require "open3"
require "json"
require "tmpdir"
require "fileutils"

require_relative "../../lib/zer0_image_generator/library"
require_relative "../../lib/zer0_image_generator/freesvg/cache"
require_relative "../../lib/zer0_image_generator/freesvg/client"

module Zer0ImageGenerator
  module Freesvg
    GOOD_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img">' \
               "<title>t</title><rect width=\"10\" height=\"10\"/></svg>"

    # A clean-of-errors but warning-carrying SVG (no <title>, no role): lints
    # with exit 0 + WARN lines, so promote proceeds and records lint: "warn: …".
    WARN_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">' \
               "<rect width=\"10\" height=\"10\"/></svg>"

    def self.fake_jwt(exp)
      # A token whose payload base64url-decodes to {"exp": exp}. The exact bytes
      # differ from CPython's fake_jwt (JSON.generate omits the space after ':'),
      # but jwt_exp only reads the decoded exp, which is identical.
      payload = [JSON.generate("exp" => exp)].pack("m0").tr("+/", "-_").delete("=")
      "e30.#{payload}.sig"
    end

    LOGIN = ["auth/login", 200, { "token" => fake_jwt(9_999_999_999) }].freeze

    # Records calls and matches a URL substring to a canned (status, payload),
    # mirroring test_freesvg.py's http_ok. String payloads are returned as raw
    # bytes (SVG); everything else is JSON-encoded.
    class FakeTransport
      attr_reader :calls

      def initialize(responses)
        @responses = responses
        @calls = []
      end

      def call(method:, url:, body: nil, token: nil)
        @calls << [method, url]
        @responses.each do |substr, status, payload|
          next unless url.include?(substr)

          raw = payload.is_a?(String) ? payload.b : JSON.generate(payload).b
          return [status, raw]
        end
        raise "unexpected url #{url}"
      end

      def logins
        @calls.count { |_method, url| url.include?("auth/login") }
      end
    end

    class FakeClock
      attr_accessor :t

      def initialize(t = Time.now.to_f)
        @t = t
      end

      def call
        @t
      end
    end

    class Base < Minitest::Test
      def setup
        @tmp = Dir.mktmpdir
        @root = @tmp
        @cache_dir = File.join(@tmp, "cache")
        @manifest = File.join(@tmp, "tools", "svg", "library", "MANIFEST.json")
        FileUtils.mkdir_p(File.dirname(@manifest))
        File.write(@manifest, JSON.generate("entries" => []))
        @warns = []
      end

      def teardown
        FileUtils.remove_entry(@tmp) if @tmp && File.directory?(@tmp)
      end

      def build_client(transport:, clock: -> { Time.now.to_f }, warns: @warns,
                       email: "u@example.com", password: "pw")
        Client.new(
          root: @root, cache_dir: @cache_dir, manifest_path: @manifest,
          transport: transport, clock: clock,
          warn: ->(message) { warns << message }, email: email, password: password
        )
      end

      def manifest_entries
        Library.new(@manifest).entries
      end
    end

    # ---- auth (ports test_freesvg.py TestAuth) --------------------------------

    class AuthTest < Base
      def test_missing_credentials_is_actionable
        client = build_client(transport: FakeTransport.new([]), email: nil, password: nil)
        with_env("FREESVG_EMAIL" => "", "FREESVG_PASSWORD" => "") do
          error = assert_raises(AuthError) { client.get_token }
          assert_includes error.message, "FREESVG_EMAIL"
        end
      end

      def test_token_cached_and_reused
        transport = FakeTransport.new([LOGIN, ["search", 200, { "data" => [] }]])
        client = build_client(transport: transport)
        client.search("cat")
        client.search("dog")
        assert_equal 1, transport.logins
        mode = File.stat(File.join(@cache_dir, "token.json")).mode & 0o777
        assert_equal 0o600, mode
      end

      def test_401_triggers_one_relogin_retry
        state = { n: 0 }
        transport = Class.new do
          define_method(:initialize) { @calls = [] }
          attr_reader :calls
          define_method(:call) do |method:, url:, body: nil, token: nil|
            @calls << [method, url]
            next [200, JSON.generate("token" => Freesvg.fake_jwt(9_999_999_999)).b] if url.include?("auth/login")

            state[:n] += 1
            next [401, '{"error":"Unauthenticated."}'.b] if state[:n] == 1

            [200, JSON.generate("data" => [{ "id" => 1 }]).b]
          end
          define_method(:logins) { @calls.count { |_m, u| u.include?("auth/login") } }
        end.new
        client = build_client(transport: transport)
        items, = client.search("cat")
        assert_equal [{ "id" => 1 }], items
        assert_equal 2, transport.logins
      end
    end

    # ---- cache tiers (ports TestCache) ----------------------------------------

    class CacheTest < Base
      def test_search_second_call_hits_cache_not_network
        transport = FakeTransport.new([LOGIN, ["search", 200, { "data" => [{ "id" => 5, "title" => "Cat" }] }]])
        client = build_client(transport: transport)
        items1, cached1 = client.search("cat")
        after_first = transport.calls.length
        items2, cached2 = client.search("cat")
        assert_equal items1, items2
        refute cached1
        assert cached2
        assert_equal after_first, transport.calls.length
      end

      def test_search_ttl_expiry_refetches
        clock = FakeClock.new
        transport = FakeTransport.new([LOGIN, ["search", 200, { "data" => [] }]])
        client = build_client(transport: transport, clock: clock)
        client.search("cat")
        after_first = transport.calls.length
        clock.t += SEARCH_TTL + 1
        client.search("cat")
        assert_operator transport.calls.length, :>, after_first
      end

      def test_meta_ttl_expiry_refetches
        clock = FakeClock.new
        transport = FakeTransport.new([LOGIN, ["/svg/7", 200, { "data" => [{ "id" => 7 }] }]])
        client = build_client(transport: transport, clock: clock)
        client.item_info("7")
        after_first = transport.calls.length
        clock.t += META_TTL + 1
        client.item_info("7")
        assert_operator transport.calls.length, :>, after_first
      end

      def test_token_refreshes_when_near_expiry
        clock = FakeClock.new
        short_exp = clock.t + 100 # valid now (> now + 60), stale after +50
        transport = FakeTransport.new(
          [["auth/login", 200, { "token" => Freesvg.fake_jwt(short_exp) }], ["search", 200, { "data" => [] }]]
        )
        client = build_client(transport: transport, clock: clock)
        client.search("cat")                # login #1
        clock.t += 50                       # now within the 60s expiry guard
        client.search("cat", refresh: true) # forces the network, so the token is re-checked
        assert_equal 2, transport.logins
      end

      def test_offline_serves_stale_with_warning
        transport = FakeTransport.new([LOGIN, ["search", 200, { "data" => [{ "id" => 9 }] }]])
        build_client(transport: transport).search("cat")

        offline = Object.new
        def offline.call(method:, url:, body: nil, token: nil)
          raise TransportError, "no route to host"
        end
        warns = []
        offline_client = build_client(transport: offline, warns: warns)
        items, cached = offline_client.search("cat", refresh: true)
        assert_equal [{ "id" => 9 }], items
        assert cached
        assert(warns.any? { |message| message.include?("stale") })
      end
    end

    # ---- fetch + promote (ports TestFetchPromote) -----------------------------

    class FetchPromoteTest < Base
      def item_responses(item)
        [LOGIN, ["/svg/7", 200, { "data" => [item] }]]
      end

      def test_fetch_inline_svg_then_immutable
        item = { "id" => 7, "title" => "Rocket Art", "svg" => GOOD_SVG }
        transport = FakeTransport.new(item_responses(item))
        client = build_client(transport: transport)
        path = client.fetch("7")
        after_first = transport.calls.length
        path2 = client.fetch("7")
        assert_equal path, path2
        assert_equal after_first, transport.calls.length
        assert_includes File.read(path), "<svg"
      end

      def test_fetch_via_url_field
        item = { "id" => 7, "title" => "X", "file" => "https://freesvg.org/storage/img/x.svg" }
        responses = item_responses(item) + [["storage/img/x.svg", 200, GOOD_SVG]]
        path = build_client(transport: FakeTransport.new(responses)).fetch("7")
        assert File.exist?(path)
      end

      def test_fetch_unknown_shape_names_fields
        item = { "id" => 7, "weird" => "value" }
        client = build_client(transport: FakeTransport.new(item_responses(item)))
        error = assert_raises(RequestError) { client.fetch("7") }
        assert_includes error.message, "weird"
      end

      def test_promote_appends_manifest_entry_once
        item = { "id" => 7, "title" => "Rocket Art", "tags" => %w[rocket space], "svg" => GOOD_SVG }
        client = build_client(transport: FakeTransport.new(item_responses(item)))
        rel = client.promote("7")
        rel2 = client.promote("7")
        assert_equal rel, rel2
        assert_equal "tools/svg/library/external/freesvg/freesvg-rocket-art.svg", rel
        assert File.exist?(File.join(@tmp, rel))
        entries = manifest_entries
        assert_equal 1, entries.length
        assert_equal "CC0 / Public domain", entries[0]["license"]
        assert_includes entries[0]["tags"], "freesvg"
      end

      def test_promote_refuses_lint_errors
        item = { "id" => 7, "title" => "Bad", "svg" => "<svg><rect/></svg>" } # no viewBox
        client = build_client(transport: FakeTransport.new(item_responses(item)))
        error = assert_raises(RequestError) { client.promote("7") }
        assert_includes error.message, "lint"
        assert_equal [], manifest_entries
      end
    end

    # ---- prune + slugify (ports TestPrune) ------------------------------------

    class PruneTest < Base
      def test_prune_removes_oldest_first
        files_dir = File.join(@cache_dir, "files")
        FileUtils.mkdir_p(files_dir)
        [300, 200, 100].each_with_index do |age, i|
          path = File.join(files_dir, "#{i}.svg")
          File.binwrite(path, "x" * 1024)
          past = Time.now.to_f - age
          File.utime(past, past, path)
        end
        client = build_client(transport: FakeTransport.new([]))
        removed, = client.prune(max_mb: 2.0 / 1024) # keep ~2KB
        assert_equal 1, removed
        refute File.exist?(File.join(files_dir, "0.svg"))
      end

      def test_slugify
        client = build_client(transport: FakeTransport.new([]))
        assert_equal "rocket-art-v2", client.send(:slugify, "Rocket  Art! (v2)")
      end
    end

    # ---- added security gate (no Python equivalent) ---------------------------

    class SecurityGateTest < Base
      # A <script>-bearing SVG lints clean (svg-check has no script rule), so the
      # linter alone would let it into the library. The sanitizer gate must catch
      # it — the reason this port refuses where freesvg.py would promote.
      def test_promote_refuses_script_that_lint_misses
        malicious = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img">' \
                    "<title>t</title><script>alert(1)</script><rect width=\"10\" height=\"10\"/></svg>"
        item = { "id" => 7, "title" => "Trojan", "svg" => malicious }
        client = build_client(transport: FakeTransport.new([LOGIN, ["/svg/7", 200, { "data" => [item] }]]))

        # The linter itself is clean on this input — proves the gate, not lint,
        # is what refuses.
        cached_path = client.fetch("7")
        assert client.send(:lint, cached_path).clean?

        error = assert_raises(RequestError) { client.promote("7") }
        assert_includes error.message, "sanitizer"
        assert_equal [], manifest_entries
      end
    end

    # ---- error handling: 4xx / 5xx / malformed --------------------------------

    class ErrorHandlingTest < Base
      def test_login_non_200_raises_auth_error
        client = build_client(transport: FakeTransport.new([["auth/login", 403, { "error" => "bad" }]]))
        error = assert_raises(AuthError) { client.search("cat") }
        assert_includes error.message, "403"
      end

      def test_login_without_token_raises_auth_error
        client = build_client(transport: FakeTransport.new([["auth/login", 200, { "nope" => 1 }]]))
        error = assert_raises(AuthError) { client.search("cat") }
        assert_includes error.message, "no token"
      end

      def test_api_5xx_raises_request_error
        client = build_client(transport: FakeTransport.new([LOGIN, ["search", 500, { "error" => "boom" }]]))
        error = assert_raises(RequestError) { client.search("cat") }
        assert_includes error.message, "500"
      end

      def test_malformed_login_body_propagates
        client = build_client(transport: FakeTransport.new([["auth/login", 200, "not json"]]))
        assert_raises(JSON::ParserError) { client.search("cat") }
      end

      def test_malformed_api_body_propagates
        client = build_client(transport: FakeTransport.new([LOGIN, ["search", 200, "not json"]]))
        assert_raises(JSON::ParserError) { client.search("cat") }
      end
    end

    # ---- PyJson byte-identity -------------------------------------------------

    class PyJsonTest < Minitest::Test
      REPO = File.expand_path("../..", __dir__)

      def python3?
        @python3 ||= system("python3", "--version", out: File::NULL, err: File::NULL)
      end

      def test_round_trips_the_committed_manifest_byte_for_byte
        # The strongest proof: parse the real 60-entry manifest and re-emit it.
        # Exercises key-order preservation, the Integer(3) vs Float(2.0) size_kb
        # distinction, and escaped quotes — all pinned to the file on disk.
        path = File.join(REPO, "tools", "svg", "library", "MANIFEST.json")
        original = File.binread(path)
        reserialized = PyJson.dump(JSON.parse(original)) + "\n"
        assert_equal original, reserialized
      end

      def test_matches_cpython_json_dumps_indent2
        skip "python3 not available" unless python3?

        obj = {
          "_comment" => "café / <tag> & \"quotes\"\t\n \u{1F680}",
          "entries" => [],
          "nested" => [{ "a" => 1, "b" => 2.0, "c" => 148.1, "d" => [] }, "x", true, false, nil],
          "empty_obj" => {}
        }
        ruby = PyJson.dump(obj)
        python = Open3.capture2("python3", "-c",
                                "import json,sys; print(json.dumps(json.load(sys.stdin), indent=2), end='')",
                                stdin_data: JSON.generate(obj)).first
        assert_equal python, ruby
      end
    end

    # ---- promote byte-identity vs the Python oracle ---------------------------

    class PromoteByteIdentityTest < Minitest::Test
      REPO = File.expand_path("../..", __dir__)
      ORACLE = File.expand_path("freesvg_promote_oracle.py", __dir__)

      def python3?
        @python3 ||= system("python3", "--version", out: File::NULL, err: File::NULL)
      end

      def python_manifest(spec)
        out, err, status = Open3.capture3("python3", ORACLE, stdin_data: JSON.generate(spec), chdir: REPO)
        raise "oracle failed (#{status.exitstatus}): #{err}" unless status.success?

        out
      end

      def ruby_manifest(spec)
        Dir.mktmpdir do |tmp|
          cache_dir = File.join(tmp, "cache")
          manifest = File.join(tmp, "tools", "svg", "library", "MANIFEST.json")
          FileUtils.mkdir_p(File.dirname(manifest))
          File.write(manifest, JSON.generate("entries" => []))

          svg_id = spec["id"] || "7"
          responses = [
            ["auth/login", 200, { "token" => Freesvg.fake_jwt(9_999_999_999) }],
            ["/svg/#{svg_id}", 200, { "data" => [spec["item"]] }]
          ]
          if (file_url = spec["file_url"])
            responses << [file_url["substr"], 200, file_url["b64"].unpack1("m")]
          end

          Client.new(
            root: tmp, cache_dir: cache_dir, manifest_path: manifest,
            transport: FakeTransport.new(responses), clock: -> { Time.now.to_f },
            warn: ->(_message) {}, email: "u@example.com", password: "pw"
          ).promote(svg_id, name: spec["name"] || "", tags: spec["tags"])

          File.binread(manifest)
        end
      end

      def assert_manifest_parity(spec)
        assert_equal python_manifest(spec), ruby_manifest(spec),
                     "manifest bytes differ from the Python oracle for #{spec.inspect}"
      end

      def test_clean_inline_promote
        skip "python3 not available" unless python3?

        assert_manifest_parity(
          "id" => "7",
          "item" => { "id" => 7, "title" => "Rocket Art", "tags" => %w[rocket space], "svg" => GOOD_SVG }
        )
      end

      def test_warning_lint_status
        skip "python3 not available" unless python3?

        assert_manifest_parity(
          "id" => "7",
          "item" => { "id" => 7, "title" => "Warny", "tags" => ["a"], "svg" => WARN_SVG }
        )
      end

      def test_non_ascii_title_and_tags
        skip "python3 not available" unless python3?

        assert_manifest_parity(
          "id" => "7",
          "item" => { "id" => 7, "title" => "Café Art", "tags" => %w[café rocket], "svg" => GOOD_SVG }
        )
      end

      def test_comma_string_tags
        skip "python3 not available" unless python3?

        assert_manifest_parity(
          "id" => "7",
          "item" => { "id" => 7, "title" => "Comma", "tags" => "alpha, beta ,gamma", "svg" => GOOD_SVG }
        )
      end

      def test_url_field_download
        skip "python3 not available" unless python3?

        assert_manifest_parity(
          "id" => "7",
          "item" => { "id" => 7, "title" => "Url One", "file" => "https://freesvg.org/storage/img/one.svg" },
          "file_url" => { "substr" => "storage/img/one.svg", "b64" => [GOOD_SVG].pack("m0") }
        )
      end

      def test_custom_name_and_tag_truncation
        skip "python3 not available" unless python3?

        assert_manifest_parity(
          "id" => "7",
          "name" => "custom-name",
          "tags" => %w[t1 t2 t3 t4 t5 t6 t7 t8],
          "item" => { "id" => 7, "title" => "Ignored", "svg" => GOOD_SVG }
        )
      end
    end
  end
end

# Temporarily override environment variables for the duration of a block.
module Zer0ImageGenerator
  module Freesvg
    class Base
      def with_env(overrides)
        saved = overrides.keys.to_h { |key| [key, ENV[key]] }
        overrides.each { |key, value| ENV[key] = value }
        yield
      ensure
        saved.each { |key, value| value.nil? ? ENV.delete(key) : ENV[key] = value }
      end
    end
  end
end
