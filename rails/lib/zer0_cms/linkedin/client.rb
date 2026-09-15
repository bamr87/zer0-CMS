# frozen_string_literal: true

require "json"
require "uri"

module Zer0Cms
  module LinkedIn
    # The one gateway to LinkedIn.
    #
    # `request` takes a call id from `Plan`, never a URL, and does four things
    # in order: refuses a call the plan does not declare (or a scope the token
    # is known not to hold), builds the URL and the headers LinkedIn's versioned
    # API requires, sends it through the injected transport, and maps a
    # non-2xx answer to `HTTPError`.
    #
    # Retries are deliberately asymmetric. A read is retried on 429, 5xx and a
    # dropped connection, honouring `Retry-After`. A write — creating a post,
    # uploading an image — is retried only on 429, which LinkedIn sends before
    # doing anything: a 5xx or a dropped socket after a POST may mean the post
    # exists, and retrying it is how a page publishes the same thing twice.
    class Client
      RETRY_STATUSES = [429, 500, 502, 503, 504].freeze
      MAX_ATTEMPTS = 4
      NO_RETRY = %i[token].freeze

      attr_reader :api_version
      attr_accessor :granted_scopes

      def initialize(token: nil, api_version: DEFAULT_API_VERSION, transport: NetHttpTransport.new,
                     sleeper: ->(seconds) { sleep(seconds) }, granted_scopes: nil, secrets: [])
        raise ArgumentError, "LinkedIn-Version must be YYYYMM, got #{api_version.inspect}" if LinkedIn.version_status(api_version) == :invalid

        @token = token.to_s
        @api_version = api_version.to_s
        @transport = transport
        @sleeper = sleeper
        @granted_scopes = granted_scopes
        @secrets = ([@token] + Array(secrets)).map(&:to_s).select { |s| s.length >= 8 }
      end

      def token?
        !@token.empty?
      end

      # Perform a declared call and return its Response.
      #
      #   path:  values for `{placeholders}` in the declared path (encoded here)
      #   query: ordered [key, value] pairs; a `Restli::Raw` value is inserted as is
      #   json / form / raw: the request body
      #   url:   only for `images_upload`, the slot LinkedIn returned
      def request(id, path: {}, query: [], json: nil, form: nil, raw: nil, content_type: nil, url: nil, auth: true)
        call = Plan.fetch(id)
        check_scopes!(call)
        target = url.nil? ? url_for(call, path, query) : upload_url!(call, url)
        headers = headers_for(call, auth: auth, content_type: content_type, json: json, form: form)
        body = if json then JSON.generate(json)
               elsif form then URI.encode_www_form(form)
               else raw
               end
        send_with_retries(call, target, headers, body)
      end

      # `request(...).json`, or {} for an empty body.
      def json(id, **options)
        request(id, **options).json || {}
      end

      private

      def send_with_retries(call, target, headers, body)
        attempt = 0
        loop do
          attempt += 1
          begin
            response = @transport.call(call.verb, target, headers, body)
          rescue NetworkError => e
            raise HTTPError.new(0, scrub(e.message)) unless retryable_network?(call) && attempt < MAX_ATTEMPTS

            @sleeper.call(backoff(attempt, nil))
            next
          end
          return response if response.success?
          raise error_for(response) unless retryable_status?(call, response.status) && attempt < MAX_ATTEMPTS

          @sleeper.call(backoff(attempt, response))
        end
      end

      def retryable_network?(call)
        !call.write && !NO_RETRY.include?(call.id)
      end

      def retryable_status?(call, status)
        return status == 429 if call.write || NO_RETRY.include?(call.id)

        RETRY_STATUSES.include?(status)
      end

      def backoff(attempt, response)
        retry_after = response&.header("retry-after").to_s
        return [retry_after.to_i, 60].min if retry_after.match?(/\A\d+\z/)

        [2**attempt, 30].min
      end

      def check_scopes!(call)
        return if @granted_scopes.nil? || call.scopes.empty?
        return unless (call.scopes & @granted_scopes).empty?

        raise Refused, "#{call.id} needs one of #{call.scopes.join(", ")}; this token holds #{@granted_scopes.join(", ")}"
      end

      def url_for(call, params, query)
        raise Refused, "#{call.id} takes the upload URL LinkedIn returned" if call.host == :upload

        path = call.path.gsub(/\{(\w+)\}/) do
          key = Regexp.last_match(1).to_sym
          value = params.fetch(key) { raise ArgumentError, "#{call.id} needs #{key}" }.to_s
          raise ArgumentError, "#{call.id}: #{key} is empty" if value.empty?

          Restli.encode(value)
        end
        raise Refused, "#{call.id} resolves to a forbidden path: #{path}" if Plan.forbidden_path?(path)

        qs = Restli.query(query)
        "https://#{call.host}#{path}#{qs.empty? ? "" : "?#{qs}"}"
      end

      def upload_url!(call, url)
        raise Refused, "#{call.id} does not take a URL" unless call.host == :upload

        uri = URI.parse(url.to_s)
        unless uri.is_a?(URI::HTTPS) && Plan::UPLOAD_HOST.match?(uri.host.to_s.downcase)
          raise Refused, "upload URL is not an https URL on linkedin.com"
        end

        uri.to_s
      rescue URI::InvalidURIError
        raise Refused, "upload URL is not a valid URL"
      end

      def headers_for(call, auth:, content_type:, json:, form:)
        headers = {}
        if auth && !call.oauth?
          raise Error, "no LinkedIn access token (set LINKEDIN_ACCESS_TOKEN or connect the channel)" unless token?

          headers["Authorization"] = "Bearer #{@token}"
        end
        if call.rest?
          headers["LinkedIn-Version"] = @api_version
          headers["X-Restli-Protocol-Version"] = RESTLI_PROTOCOL
          headers["X-RestLi-Method"] = call.method_header if call.method_header
        end
        type = content_type || (json && "application/json") || (form && "application/x-www-form-urlencoded")
        headers["Content-Type"] = type if type
        headers["Accept"] = "application/json" unless call.host == :upload
        headers
      end

      def error_for(response)
        data = response.json
        data = {} unless data.is_a?(Hash)
        message = data["message"] || data["error_description"] || data["error"]
        message ||= response.body.to_s.strip[0, 300]
        message = "request failed" if message.to_s.empty?
        code = data["serviceErrorCode"] || data["code"] || (data["error"] if data["error_description"])
        HTTPError.new(response.status, scrub(message.to_s), code: code, request_id: response.header("x-li-uuid"), body: data)
      end

      def scrub(text)
        @secrets.reduce(text.to_s) { |out, secret| out.gsub(secret, "[redacted]") }
      end
    end
  end
end
