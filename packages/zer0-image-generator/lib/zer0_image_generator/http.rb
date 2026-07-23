# frozen_string_literal: true

require "net/http"
require "uri"
require "json"
require "securerandom"
require "timeout"

require_relative "logging"

module Zer0ImageGenerator
  # Non-2xx HTTP response, with parsed body + headers when possible.
  #
  # Ported from preview_generator.py `HttpStatusError`. One naming caveat: the
  # Python class exposes BOTH `str(exc)` (the constructor summary) and a
  # separate `exc.message()` method (the parsed provider error). Ruby's
  # `Exception#message` is already the constructor summary, so the parsed
  # provider error lives under `#error_message` here — renaming `#message`
  # would break every `raise`/log site that expects the summary string.
  class HttpStatusError < StandardError
    attr_reader :status, :body, :url, :headers

    def initialize(status, body, url, headers = nil)
      @status = status
      # Keep the body as raw bytes: providers sometimes send non-UTF-8 error
      # payloads and we must not lose them to an eager transcode.
      @body = (body || "").b
      @url = url
      # Header keys are lower-cased so `retry-after` is found regardless of the
      # server's casing (mirrors the Python dict comprehension).
      @headers = {}
      (headers || {}).each { |key, value| @headers[key.to_s.downcase] = value }
      super("HTTP #{status} from #{url}: #{error_message[0, 300]}")
    end

    # Server-requested backoff: the Retry-After header (what Anthropic/OpenAI/
    # xAI actually send on 429), falling back to a JSON body field.
    def retry_after
      header = @headers["retry-after"]
      unless header.nil? || header.to_s.empty?
        value = to_float(header)
        return value unless value.nil?
      end
      data = json
      if data.is_a?(Hash)
        # Python's `data.get("retry_after", 0) or 0` collapses every falsy value
        # (missing, null, 0, "") to 0 before the float() call.
        raw = data["retry_after"]
        raw = 0 if py_falsy?(raw)
        value = to_float(raw)
        return value unless value.nil?
      end
      0.0
    end

    # Parsed JSON body, or nil when the body is not valid JSON. `scrub` gives
    # us CPython's `bytes.decode("utf-8", "replace")` — invalid bytes become
    # U+FFFD rather than raising.
    def json
      JSON.parse(decoded_body)
    rescue JSON::ParserError
      nil
    end

    # The human-readable provider error. This is Python's `HttpStatusError.
    # message()`, deliberately NOT named `message` (see the class comment).
    def error_message
      data = json
      if data.is_a?(Hash)
        err = data["error"]
        return py_str(err["message"]) if err.is_a?(Hash) && py_truthy?(err["message"])
        # A bare string `error` is returned even when empty — no truthiness
        # gate here, matching the oracle.
        return err if err.is_a?(String)
        return py_str(data["detail"]) if py_truthy?(data["detail"])
      end
      decoded_body[0, 500]
    end

    private

    def decoded_body
      @body.dup.force_encoding(Encoding::UTF_8).scrub
    end

    def to_float(value)
      Float(value)
    rescue ArgumentError, TypeError
      nil
    end

    # CPython truthiness over the scalar/collection shapes a JSON value takes.
    def py_truthy?(value)
      case value
      when nil, false then false
      when String, Array, Hash then !value.empty?
      when Numeric then value != 0
      else true
      end
    end

    def py_falsy?(value)
      !py_truthy?(value)
    end

    # Python f-string interpolation goes through str(): booleans and nil print
    # capitalized, everything else via to_s.
    def py_str(value)
      case value
      when String then value
      when true then "True"
      when false then "False"
      when nil then "None"
      else value.to_s
      end
    end
  end

  # HTTP layer — Net::HTTP only, no third-party deps (parity with the Python
  # engine's urllib-only stance). The AnthropicClient and the image providers
  # call these as an injectable transport seam; a Rails app fakes `.json` /
  # `.multipart` the same way the tests do.
  module Http
    module_function

    RETRYABLE_STATUSES = [429, 500, 502, 503, 529].freeze

    # urllib.error.URLError + OSError (which covers ConnectionError and
    # TimeoutError) map onto this set: DNS/socket failures, Errno::*, broken
    # streams, and read/open timeouts. HttpStatusError is handled separately.
    TRANSPORT_ERRORS = [
      SocketError, SystemCallError, IOError, EOFError, Timeout::Error,
      Net::OpenTimeout, Net::ReadTimeout, Net::HTTPBadResponse, Net::ProtocolError
    ].freeze

    # urllib follows up to 10 redirects by default; matching that keeps
    # `download_to` behavior identical for providers that return 3xx image URLs.
    MAX_REDIRECTS = 10
    REDIRECT_STATUSES = [301, 302, 303, 307, 308].freeze

    def request(url, method: "GET", headers: nil, data: nil, timeout: 120)
      uri = URI(url)
      redirects = 0
      loop do
        response = perform(uri, method, headers, data, timeout)
        code = response.code.to_i
        location = response["location"]
        if REDIRECT_STATUSES.include?(code) && location && method.to_s.upcase == "GET" &&
           redirects < MAX_REDIRECTS
          redirects += 1
          uri = URI.join(uri.to_s, location)
          next
        end
        return [code, header_hash(response), (response.body || "").b] if code >= 200 && code < 300

        raise HttpStatusError.new(code, response.body, url, header_hash(response))
      end
    end

    def json(url, payload, headers, timeout: 900)
      body = JSON.generate(payload)
      # Caller-supplied headers win on conflict, exactly like `{**base, **headers}`.
      hdrs = { "Content-Type" => "application/json" }.merge(headers)
      _, _, raw = request(url, method: "POST", headers: hdrs, data: body, timeout: timeout)
      JSON.parse(raw)
    end

    # Encode multipart/form-data. `files` entries are [field, filename, content,
    # mime]. The body is assembled as raw bytes so binary image content survives
    # untouched; the boundary and layout match the oracle byte for byte.
    def build_multipart(fields, files)
      boundary = "----zer0-#{SecureRandom.hex(16)}"
      buf = +"".b
      fields.each do |name, value|
        buf << "--#{boundary}\r\n".b
        buf << "Content-Disposition: form-data; name=\"#{name}\"\r\n\r\n".b
        buf << value.to_s.b
        buf << "\r\n".b
      end
      files.each do |name, filename, content, mime|
        buf << "--#{boundary}\r\n".b
        buf << "Content-Disposition: form-data; name=\"#{name}\"; filename=\"#{filename}\"\r\n".b
        buf << "Content-Type: #{mime}\r\n\r\n".b
        buf << content.b
        buf << "\r\n".b
      end
      buf << "--#{boundary}--\r\n".b
      [buf, "multipart/form-data; boundary=#{boundary}"]
    end

    def multipart(url, fields, files, headers, timeout: 900)
      body, content_type = build_multipart(fields, files)
      hdrs = { "Content-Type" => content_type }.merge(headers)
      _, _, raw = request(url, method: "POST", headers: hdrs, data: body, timeout: timeout)
      JSON.parse(raw)
    end

    def download_to(url, dest, timeout: 120)
      _, _, raw = request(url, method: "GET", headers: {}, data: nil, timeout: timeout)
      File.binwrite(dest.to_s, raw)
      nil
    end

    # Run the block; retry transport errors and retryable HTTP statuses.
    # Backoff 2s/4s/8s (or the server's Retry-After when larger, capped 60s).
    # `sleeper` is injectable so tests observe the wait ladder without sleeping;
    # it defaults to a real sleep for production callers.
    def with_retries(what, attempts: 4, sleeper: nil)
      sleeper ||= ->(seconds) { sleep(seconds) }
      delay = 2.0
      1.upto(attempts) do |attempt|
        begin
          return yield
        rescue HttpStatusError => e
          raise if !RETRYABLE_STATUSES.include?(e.status) || attempt == attempts

          wait = [[delay, e.retry_after].max, 60.0].min
          Logging.warn("#{what}: HTTP #{e.status}, retrying in #{format('%.0f', wait)}s " \
                       "(attempt #{attempt}/#{attempts})")
        rescue *TRANSPORT_ERRORS => e
          raise if attempt == attempts

          wait = delay
          Logging.warn("#{what}: #{e.class.name}: #{e.message}; retrying in #{format('%.0f', wait)}s " \
                       "(attempt #{attempt}/#{attempts})")
        end
        sleeper.call(wait)
        delay *= 2
      end
    end

    # --- internals ------------------------------------------------------------

    def perform(uri, method, headers, data, timeout)
      http = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = (uri.scheme == "https")
      http.open_timeout = timeout
      http.read_timeout = timeout
      request = request_class(method).new(uri.request_uri)
      (headers || {}).each { |key, value| request[key] = value }
      request.body = data unless data.nil?
      http.start { |conn| conn.request(request) }
    end
    private_class_method :perform

    def request_class(method)
      case method.to_s.upcase
      when "GET" then Net::HTTP::Get
      when "POST" then Net::HTTP::Post
      when "PUT" then Net::HTTP::Put
      when "DELETE" then Net::HTTP::Delete
      else Net::HTTP::Get
      end
    end
    private_class_method :request_class

    def header_hash(response)
      hash = {}
      response.each_header { |key, value| hash[key] = value }
      hash
    end
    private_class_method :header_hash
  end
end
