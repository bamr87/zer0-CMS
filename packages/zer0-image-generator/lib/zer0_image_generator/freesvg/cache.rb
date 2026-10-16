# frozen_string_literal: true

require "json"
require "fileutils"

module Zer0ImageGenerator
  module Freesvg
    # API base and the tier TTLs, lifted verbatim from tools/svg/freesvg.py so
    # an on-disk cache written by either language stays valid for the other.
    API = "https://freesvg.org/api/v1"
    SEARCH_TTL = 7 * 86_400   # searches: 7 days
    META_TTL = 30 * 86_400    # per-item metadata: 30 days
    TIMEOUT = 30

    # -- error hierarchy -------------------------------------------------------
    #
    # freesvg.py leans on Python's exception types: AuthError subclasses
    # RuntimeError, api_get raises bare RuntimeError, and transport failure
    # surfaces as OSError/URLError. `_cached` catches (AuthError, RuntimeError)
    # and re-raises them, but catches OSError separately to serve stale cache.
    # The Ruby split preserves that: Error (and its subclasses) propagate;
    # TransportError is the offline signal Cache#fetch_cached catches. So
    # TransportError deliberately does NOT descend from Error.

    class Error < StandardError; end

    # Missing/invalid credentials or a failed login. Python: AuthError(RuntimeError).
    class AuthError < Error; end

    # A request the server answered but rejected (non-200), or a response we
    # could not turn into art. Python: the bare RuntimeErrors in api_get /
    # _extract_svg / promote.
    class RequestError < Error; end

    # Transport-level failure (DNS, refused, timeout, TLS). The offline signal:
    # Cache#fetch_cached catches it to fall back to a stale entry. Mirrors
    # Python relying on urllib raising OSError/URLError. IOError keeps it clearly
    # distinct from the Error tree above.
    class TransportError < IOError; end

    # The tiered local cache that makes repeat FreeSVG lookups cost zero API
    # calls. On-disk layout (git-ignored; safe to delete — it rebuilds):
    #
    #   token.json           JWT + parsed expiry, chmod 600
    #   searches/<key>.json  search responses,  TTL 7 days
    #   meta/<id>.json       per-item metadata,  TTL 30 days
    #   files/<id>.svg       downloaded art — immutable, cached forever
    #
    # Cache entries wrap their payload as {"fetched_at": <epoch>, "data": ...};
    # freshness is now - fetched_at < ttl. A fresh entry never touches the
    # network; a fetch failure with any cached copy present serves it stale.
    #
    # The clock is injected (a callable returning epoch seconds) so TTL
    # boundaries are testable without sleeping — the seam replacing freesvg.py's
    # monkeypatched `_now`.
    class Cache
      attr_reader :dir

      def initialize(dir:, clock: -> { Time.now.to_f }, warn: ->(_msg) {})
        @dir = dir
        @clock = clock
        @warn = warn
      end

      def now
        @clock.call
      end

      # Full path under the cache dir, with its parent directory created —
      # freesvg.py's `_ensure`.
      def ensure_path(*parts)
        full = File.join(@dir, *parts)
        FileUtils.mkdir_p(File.dirname(full))
        full
      end

      def path(*parts)
        File.join(@dir, *parts)
      end

      # Parsed JSON, or nil when absent/corrupt. freesvg.py's `_read_json`
      # swallows exactly OSError/ValueError; the Ruby equivalents are
      # SystemCallError/IOError (file trouble) and JSON::ParserError (bad JSON).
      # Explicit, not a bare rescue: a damaged cache file must read as "absent"
      # so the tier simply refetches.
      def read_json(file)
        JSON.parse(File.read(file))
      rescue JSON::ParserError, SystemCallError, IOError
        nil
      end

      # freesvg.py's `_write_json`. Cache files are git-ignored working memory,
      # so the exact byte layout is not a contract (unlike the manifest) — only
      # the schema and the chmod-600 on the token are. pretty_generate keeps
      # them human-diffable; a trailing newline matches the Python writer.
      def write_json(file, data, private: false)
        FileUtils.mkdir_p(File.dirname(file))
        File.write(file, JSON.pretty_generate(data) + "\n")
        # The JWT is a bearer credential: keep it owner-only on disk.
        File.chmod(0o600, file) if private
      end

      # The freshness core (freesvg.py's `_cached`). Returns [data, from_cache?].
      #   fresh hit + no refresh -> serve cache, no network
      #   miss / stale / refresh -> run the fetch block
      #   fetch raised TransportError with a cached copy present -> serve stale + warn
      # AuthError/RequestError from the block propagate untouched, exactly as
      # Python re-raises (AuthError, RuntimeError) ahead of its OSError branch.
      def fetch_cached(file, ttl, refresh)
        entry = read_json(file)
        fresh = present_hash?(entry) && (now - (entry["fetched_at"] || 0) < ttl)
        return [entry["data"], true] if fresh && !refresh

        begin
          data = yield
        rescue TransportError => exc
          if present_hash?(entry)
            stamped = Time.at(entry["fetched_at"]).strftime("%Y-%m-%d")
            @warn.call("network unavailable (#{exc.message}); serving stale cache from #{stamped}")
            return [entry["data"], true]
          end
          raise
        end

        write_json(file, { "fetched_at" => now, "data" => data })
        [data, false]
      end

      # freesvg.py's `prune`: walk files/meta/searches, and while the cache is
      # over budget delete oldest-first (by mtime, then size, then path — the
      # tuple order Python's sorted() uses). Returns [removed_count, total_bytes].
      def prune(max_mb: 50.0)
        victims = []
        %w[files meta searches].each do |sub|
          base = File.join(@dir, sub)
          next unless File.directory?(base)

          Dir.children(base).each do |name|
            full = File.join(base, name)
            victims << [File.mtime(full).to_f, File.size(full), full]
          end
        end

        total = victims.sum { |_mtime, size, _path| size }
        removed = 0
        budget = max_mb * 1024 * 1024
        victims.sort_by { |mtime, size, path| [mtime, size, path] }.each do |_mtime, size, path|
          break if total <= budget

          File.delete(path)
          total -= size
          removed += 1
        end
        [removed, total]
      end

      private

      # Python truthiness for a parsed cache entry: a dict is truthy only when
      # non-empty, so a stray `{}` cache file counts as "no usable entry" — both
      # for the freshness check and the stale-serve fallback.
      def present_hash?(entry)
        entry.is_a?(Hash) && !entry.empty?
      end
    end
  end
end
