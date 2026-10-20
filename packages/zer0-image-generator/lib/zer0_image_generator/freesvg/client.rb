# frozen_string_literal: true

require "net/http"
require "uri"
require "json"
require "digest"
require "fileutils"

require_relative "cache"
require_relative "../library"
require_relative "../svg/lint"
require_relative "../svg/sanitizer"

module Zer0ImageGenerator
  module Freesvg
    # Fields that, on an item, may hold a downloadable SVG URL. Same tuple and
    # order as freesvg.py's URL_KEYS — the order is load-bearing, since
    # _extract_svg returns the first URL field that yields real SVG bytes.
    URL_KEYS = %w[svg url file path download_url svg_url image link].freeze

    # Default HTTP transport. Returns [status, body_bytes] for any answered
    # request (including 4xx/5xx — freesvg.py's `_http` folds HTTPError back
    # into a (code, body) pair) and raises TransportError only when the request
    # never completed, which is the signal Cache#fetch_cached treats as offline.
    #
    # Injectable: the Client takes any object with this #call shape, so tests
    # (and a Rails app that wants its own connection pooling) can supply their
    # own without a live network.
    class HttpTransport
      def call(method:, url:, body: nil, token: nil)
        uri = URI.parse(url)
        request = build_request(method, uri, body, token)
        http = Net::HTTP.new(uri.host, uri.port)
        http.use_ssl = uri.scheme == "https"
        http.open_timeout = TIMEOUT
        http.read_timeout = TIMEOUT
        response = http.request(request)
        [response.code.to_i, response.body.to_s.b]
      rescue SocketError, SystemCallError, Timeout::Error, OpenSSL::SSL::SSLError, IOError => exc
        # urllib surfaces these as OSError/URLError; re-badge as the offline
        # signal so the cache can serve stale instead of hard-failing.
        raise TransportError, exc.message
      end

      private

      def build_request(method, uri, body, token)
        klass = method.to_s.upcase == "POST" ? Net::HTTP::Post : Net::HTTP::Get
        request = klass.new(uri)
        request["Accept"] = "application/json"
        request["User-Agent"] = "zer0-image-generator/freesvg-cache"
        if body
          request["Content-Type"] = "application/json"
          request.body = JSON.generate(body)
        end
        request["Authorization"] = "Bearer #{token}" if token
        request
      end
    end

    # FreeSVG.org API client with the tiered local cache (Cache) and the example
    # library (Library) behind it. Public methods return structured Ruby values
    # — item hashes, cache-hit booleans, filesystem paths — never printed text,
    # so a Rails UI can drive search / preview / promote directly.
    #
    #   client.search("rocket")   => [items, from_cache?]
    #   client.item_info("123")   => [item, from_cache?]
    #   client.fetch("123")       => cache path to the linted .svg
    #   client.promote("123")     => repo-relative path of the graduated file
    #   client.prune(max_mb: 50)  => [removed, total_bytes]
    #   client.status             => Hash of cache + auth health
    #
    # Determinism/testability seams: `transport` (network) and `clock` (time)
    # are injected, replacing the module globals freesvg.py monkeypatches in its
    # tests. Credentials resolve from explicit args, then the environment, then
    # the repo's git-ignored .env — matching freesvg.py's precedence.
    class Client
      attr_reader :cache, :library

      def initialize(root: self.class.default_root,
                     cache_dir: nil, manifest_path: nil,
                     transport: HttpTransport.new,
                     clock: -> { Time.now.to_f },
                     warn: nil,
                     email: nil, password: nil)
        @root = root
        @cache_dir = cache_dir || ENV["FREESVG_CACHE_DIR"] ||
                     File.join(root, "tools", "svg", "library", "cache", "freesvg")
        @manifest_path = manifest_path || ENV["FREESVG_MANIFEST"] ||
                         File.join(root, "tools", "svg", "library", "MANIFEST.json")
        @transport = transport
        @clock = clock
        @warn = warn || method(:default_warn)
        @email_override = email
        @password_override = password
        @cache = Cache.new(dir: @cache_dir, clock: @clock, warn: @warn)
        @library = Library.new(@manifest_path)
      end

      # freesvg.py derives ROOT from the file location (tools/svg/..); the gem's
      # copy lives at lib/zer0_image_generator/freesvg/client.rb, so the repo
      # root is four levels up. Overridable via the constructor for tests.
      def self.default_root
        File.expand_path("../../..", __dir__)
      end

      # -- search / info -------------------------------------------------------

      def search(query, page: 1, refresh: false)
        # Cache key: sha256("<trimmed lowercased query>|<page>")[:16]. Identical
        # bytes to freesvg.py so a warm cache dir is shared across languages.
        key = Digest::SHA256.hexdigest("#{query.strip.downcase}|#{page}")[0, 16]
        file = @cache.ensure_path("searches", "#{key}.json")
        query_string = URI.encode_www_form("query" => query, "page" => page)
        payload, from_cache = @cache.fetch_cached(file, SEARCH_TTL, refresh) do
          api_get("/search?#{query_string}")
        end
        [items_of(payload), from_cache]
      end

      def item_info(svg_id, refresh: false)
        file = @cache.ensure_path("meta", "#{svg_id}.json")
        payload, from_cache = @cache.fetch_cached(file, META_TTL, refresh) do
          api_get("/svg/#{svg_id}")
        end
        items = items_of(payload)
        [items.empty? ? payload : items.first, from_cache]
      end

      # -- download ------------------------------------------------------------

      # Download one item's SVG into the immutable files/ tier and lint it. A
      # cached file is returned untouched (never refetched) unless refresh:.
      # A lint failure is surfaced as a warning but the file is kept — promote
      # is the gate that actually refuses dirty art.
      def fetch(svg_id, refresh: false)
        file = @cache.ensure_path("files", "#{svg_id}.svg")
        return file if File.exist?(file) && !refresh

        item, = item_info(svg_id, refresh: refresh)
        body = extract_svg(item)
        File.binwrite(file, body)

        report = lint(file)
        unless report.clean?
          @warn.call("downloaded file has lint errors (kept in cache, blocked from " \
                     "promote):\n#{report.stderr_lines.join("\n")}")
        end
        file
      end

      # -- promote -------------------------------------------------------------

      # Graduate a cached keeper into the committed library with full
      # provenance, appending its MANIFEST.json entry. Idempotent: a file
      # already in the manifest is left unchanged.
      #
      # Two gates guard the library, both of which must pass:
      #   1. Lint (svg-check parity) — a hard refusal on errors, as in Python.
      #   2. Sanitizer — the security gate ADDED in this port (see the code
      #      comment and DEVIATIONS): external SVG is untrusted input, and the
      #      linter does not catch <script>/foreignObject/event-handlers/DOCTYPE.
      def promote(svg_id, name: "", tags: nil)
        local = fetch(svg_id)

        report = lint(local)
        unless report.clean?
          raise RequestError,
                "refusing to promote #{svg_id}: lint errors\n#{report.stderr_lines.join("\n")}"
        end

        reject_unsafe!(svg_id, local)

        item, = item_info(svg_id)
        title = (presence(item["title"]) || presence(item["name"]) || "freesvg #{svg_id}").to_s
        slug = presence(name) || slugify(title)
        dest_rel = "tools/svg/library/external/freesvg/freesvg-#{slug}.svg"
        dest = File.join(@root, dest_rel)
        FileUtils.mkdir_p(File.dirname(dest))
        # Keep the pristine file: only write the destination on first promote.
        File.binwrite(dest, File.binread(local)) unless File.exist?(dest)

        if @library.has_file?(dest_rel)
          @warn.call("#{dest_rel} already in manifest; leaving entry unchanged")
          return dest_rel
        end

        @library.add_entry(build_entry(dest_rel, dest, title, svg_id, tags, item["tags"], report.warnings))
        dest_rel
      end

      def prune(max_mb: 50.0)
        @cache.prune(max_mb: max_mb)
      end

      # Structured cache + auth health for a UI. freesvg.py's `status` command
      # prints this; here it is returned so the caller decides how to render it.
      def status
        counts = {}
        %w[files meta searches].each do |sub|
          base = @cache.path(sub)
          counts[sub] = File.directory?(base) ? Dir.children(base).length : 0
        end
        email, password = credentials
        token = @cache.read_json(@cache.path("token.json"))
        {
          cache_dir: @cache.dir,
          counts: counts,
          credentials_set: !presence(email).nil? && !presence(password).nil?,
          token: token_status(token)
        }
      end

      # -- credentials + token (exposed; a Rails app inspects auth state) ------

      # [email, password], each resolved from override -> ENV -> .env, with
      # Python's `or` semantics: an empty string is falsy and falls through to
      # the next source. Either may be nil when unset.
      def credentials
        fallback = env_file_creds
        email = presence(@email_override) || presence(ENV["FREESVG_EMAIL"]) || fallback["FREESVG_EMAIL"]
        password = presence(@password_override) || presence(ENV["FREESVG_PASSWORD"]) || fallback["FREESVG_PASSWORD"]
        [email, password]
      end

      # Cached JWT, reused until it is within 60s of expiry. force: re-logs in.
      def get_token(force: false)
        file = @cache.ensure_path("token.json")
        unless force
          cached = @cache.read_json(file)
          if cached && (cached["exp"] || 0) > @clock.call + 60
            return cached["token"]
          end
        end

        email, password = credentials
        unless presence(email) && presence(password)
          raise AuthError,
                "FreeSVG credentials missing. Set FREESVG_EMAIL and FREESVG_PASSWORD " \
                "in the environment or the repo's git-ignored .env " \
                "(register at https://freesvg.org — the API is for registered users)."
        end

        status, body = http("POST", "#{API}/auth/login", body: { "email" => email, "password" => password })
        raise AuthError, "login failed (HTTP #{status}): #{decode_snippet(body)}" if status != 200

        token = presence(parse_json(body)["token"])
        raise AuthError, "login response had no token" if token.nil?

        @cache.write_json(file, { "token" => token, "exp" => jwt_exp(token) }, private: true)
        token
      end

      private

      # Authenticated GET returning parsed JSON; one forced-relogin retry on 401.
      def api_get(path)
        token = get_token
        status, body = http("GET", "#{API}#{path}", token: token)
        if status == 401
          token = get_token(force: true)
          status, body = http("GET", "#{API}#{path}", token: token)
        end
        raise RequestError, "GET #{path} failed (HTTP #{status}): #{decode_snippet(body)}" if status != 200

        parse_json(body)
      end

      def http(method, url, body: nil, token: nil)
        @transport.call(method: method, url: url, body: body, token: token)
      end

      # Unwrap the list of items from the several response shapes FreeSVG has
      # been seen to return. Mirrors freesvg.py's `_items_of`.
      def items_of(payload)
        return payload if payload.is_a?(Array)

        if payload.is_a?(Hash)
          %w[data svgs results items].each do |key|
            return payload[key] if payload[key].is_a?(Array)
          end
        end
        [payload]
      end

      # Locate SVG bytes in an item: inline markup on any field first, then the
      # first URL_KEYS field pointing at a downloadable .svg. The failure names
      # the fields present so the schema can be adapted. Mirrors `_extract_svg`.
      def extract_svg(item)
        item.each_value do |value|
          if value.is_a?(String) && value.lstrip.start_with?("<?xml", "<svg")
            return value
          end
        end

        URL_KEYS.each do |key|
          value = item[key]
          next unless value.is_a?(String) && value.start_with?("http") &&
                      (value.downcase.include?(".svg") || value.downcase.include?("download"))

          status, body = http("GET", value, token: get_token)
          return body if status == 200 && looks_like_svg?(body)
        end

        raise RequestError,
              "could not locate SVG content in item; fields present: " \
              "#{item.keys.sort.join(', ')} — update URL_KEYS/_extract_svg in " \
              "tools/svg/freesvg.py for this shape"
      end

      # Byte sniff for a downloaded body (freesvg.py's `_looks_like_svg`).
      # Precedence matches: (starts <?xml AND contains <svg) OR starts <svg.
      def looks_like_svg?(body)
        bytes = body.b
        head = bytes[0, 2048].to_s.lstrip.downcase
        (head.start_with?("<?xml") && bytes[0, 4096].to_s.downcase.include?("<svg")) ||
          head.start_with?("<svg")
      end

      # The lint gate, via the ported deterministic linter (svg/lint.rb, itself
      # differential-tested against tools/svg/svg-check.py). freesvg.py shells
      # out to svg-check.py with --max-kb 1024; this is the in-process, no-
      # subprocess, no-network equivalent with identical findings and exit code.
      def lint(file)
        Zer0ImageGenerator::Svg::Lint.check(file, max_kb: 1024.0)
      end

      # SECURITY GATE — added in the Ruby port; freesvg.py has no equivalent.
      # svg-check.py flags external <image>/network refs but NOT <script>,
      # foreignObject, on* handlers, non-local url(), or DOCTYPE/ENTITY, so a
      # weaponized third-party SVG can pass the lint gate. Before anything
      # enters the committed library we additionally require it to survive the
      # engine's own sanitizer with nothing stripped. The pristine file is left
      # untouched (README: external files stay pristine) — a finding is a hard
      # refusal, not a rewrite.
      def reject_unsafe!(svg_id, file)
        _clean, findings = Zer0ImageGenerator::Svg::Sanitizer.sanitize_svg(
          File.binread(file).force_encoding("UTF-8")
        )
        return if findings.empty?

        raise RequestError,
              "refusing to promote #{svg_id}: sanitizer flagged unsafe content " \
              "(#{findings.join('; ')}) — external SVG must survive sanitize_svg untouched"
      rescue Zer0ImageGenerator::Svg::SvgError => exc
        raise RequestError, "refusing to promote #{svg_id}: #{exc.message}"
      end

      # Build the provenance-bearing manifest entry. Key order and values match
      # freesvg.py's promote exactly (file, title, source_url, license,
      # license_url, tags, lint, size_kb) so PyJson reproduces its bytes.
      def build_entry(dest_rel, dest_abs, title, svg_id, tags, item_tags, warnings)
        normalized = normalize_item_tags(item_tags)
        chosen = [tags, normalized].find { |candidate| truthy?(candidate) } || []
        entry_tags = chosen.first(6)
        entry_tags = ["illustration"] if entry_tags.empty?

        lint_status =
          if warnings.empty?
            "clean"
          else
            "warn: " + warnings.join("; ")[0, 160]
          end

        {
          "file" => dest_rel,
          "title" => title,
          "source_url" => "#{API}/svg/#{svg_id}",
          "license" => "CC0 / Public domain",
          "license_url" => "https://freesvg.org",
          "tags" => entry_tags.map { |t| t.to_s.downcase } + ["freesvg"],
          "lint" => lint_status,
          # Guaranteed byte-match to Python's round(bytes/1024, 1): "%.1f" and
          # CPython round both use IEEE round-half-to-even, and ties are
          # impossible here (bytes/1024 is dyadic, a half-tenth never is). Float
          # of that string is the exact double repr renders as "N.N".
          "size_kb" => Float(format("%.1f", File.size(dest_abs) / 1024.0))
        }
      end

      # item tags may arrive as a list or a comma-joined string; normalize to a
      # list (or pass through nil). Mirrors the isinstance(str) branch in promote.
      def normalize_item_tags(item_tags)
        return item_tags unless item_tags.is_a?(String)

        item_tags.split(",").map(&:strip).reject(&:empty?)
      end

      # slug: lowercase, non-alnum runs to "-", collapse dashes, trim dashes,
      # default "untitled". Mirrors freesvg.py's `_slugify`.
      def slugify(text)
        slug = text.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/-+/, "-")
        slug = slug.sub(/\A-+/, "").sub(/-+\z/, "")
        slug.empty? ? "untitled" : slug
      end

      # Best-effort JWT expiry from the payload; a short conservative fallback
      # when the token is unreadable. Mirrors freesvg.py's `_jwt_exp`, whose
      # broad `except Exception` is faithfully reproduced here: the JWT is
      # opaque third-party text, so any decode/parse failure just means "trust
      # it for a few hours, no more".
      def jwt_exp(token)
        payload = token.split(".")[1].to_s.tr("-_", "+/")
        payload += "=" * ((-payload.length) % 4)
        # unpack1("m") is stdlib base64 decode — no dependency on the `base64`
        # gem, which is no longer a default library. Mirrors Python's
        # base64.urlsafe_b64decode after the -_/+/ translation + padding above.
        Float(JSON.parse(payload.unpack1("m"))["exp"])
      rescue StandardError
        @clock.call + (6 * 3600)
      end

      def env_file_creds
        creds = {}
        path = File.join(@root, ".env")
        return creds unless File.exist?(path)

        File.foreach(path) do |line|
          match = line.match(/\s*(?:export\s+)?(FREESVG_[A-Z_]+)\s*=\s*(.*)\s*$/)
          next unless match

          # Python strips only surrounding quotes here (str.strip("'\"")),
          # deliberately not whitespace, so mirror that precisely.
          creds[match[1]] = match[2].sub(/\A["']+/, "").sub(/["']+\z/, "")
        end
        creds
      rescue SystemCallError
        creds
      end

      def token_status(token)
        return { cached: false } unless token

        left = (token["exp"] || 0) - @clock.call
        left.positive? ? { cached: true, valid_hours: left / 3600.0 } : { cached: true, expired: true }
      end

      def parse_json(body)
        JSON.parse(body)
      end

      # First 200 bytes decoded as UTF-8 with replacement, for error messages.
      # Mirrors body[:200].decode("utf-8", "replace").
      def decode_snippet(body)
        body.b[0, 200].to_s.force_encoding("UTF-8").scrub
      end

      # Python truthiness for `x or y`: nil, false, "", empty collections, and
      # numeric zero are all falsy and fall through.
      def truthy?(value)
        return false if value.nil? || value == false
        return false if value.respond_to?(:empty?) && value.empty?
        return false if value.is_a?(Numeric) && value.zero?

        true
      end

      def presence(value)
        value if truthy?(value)
      end

      def default_warn(message)
        warn("freesvg: #{message}")
      end
    end
  end
end
