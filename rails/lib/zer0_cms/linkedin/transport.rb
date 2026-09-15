# frozen_string_literal: true

require "json"
require "net/http"
require "openssl"
require "uri"

module Zer0Cms
  module LinkedIn
    # What a transport returns. Header names are lower-cased.
    Response = Struct.new(:status, :headers, :body, keyword_init: true) do
      def header(name)
        headers[name.to_s.downcase]
      end

      def success?
        status.between?(200, 299)
      end

      def json
        text = body.to_s
        text.strip.empty? ? nil : JSON.parse(text)
      rescue JSON::ParserError
        nil
      end
    end

    # The production transport: one HTTPS request per call through Net::HTTP.
    # `Client` owns retries and error mapping; this class only moves bytes, and
    # refuses anything that is not https.
    class NetHttpTransport
      VERBS = {
        "GET" => Net::HTTP::Get, "POST" => Net::HTTP::Post, "PUT" => Net::HTTP::Put, "DELETE" => Net::HTTP::Delete
      }.freeze
      NETWORK_ERRORS = [SocketError, Timeout::Error, IOError, SystemCallError, OpenSSL::SSL::SSLError,
                        Net::ProtocolError].freeze

      def initialize(open_timeout: 10, read_timeout: 30)
        @open_timeout = open_timeout
        @read_timeout = read_timeout
      end

      def call(verb, url, headers, body)
        uri = URI.parse(url)
        raise Refused, "only https is allowed: #{uri.scheme}://#{uri.host}" unless uri.scheme == "https"

        http = Net::HTTP.new(uri.host, uri.port)
        http.use_ssl = true
        http.open_timeout = @open_timeout
        http.read_timeout = @read_timeout
        request = VERBS.fetch(verb).new(uri.request_uri)
        headers.each { |key, value| request[key] = value }
        request.body = body if body
        response = http.request(request)
        Response.new(status: response.code.to_i, headers: response.each_header.to_h, body: response.body.to_s)
      rescue *NETWORK_ERRORS => e
        raise NetworkError, "#{uri&.host}: #{e.class.name}"
      end
    end

    # A transport that answers from a script and records what it was asked.
    #
    # It is how every test in this repository exercises the client without a
    # network, and how `zer0-cms linkedin publish` can be rehearsed against a
    # recorded exchange. It never opens a socket. `on` registers an answer for
    # a verb and a URL prefix (a String) or pattern (a Regexp); an unmatched
    # request raises, so a test cannot pass by accident against an unscripted
    # call.
    class ScriptedTransport
      Request = Struct.new(:verb, :url, :headers, :body, keyword_init: true) do
        def json
          JSON.parse(body.to_s)
        end

        def form
          URI.decode_www_form(body.to_s).to_h
        end

        def query
          URI.decode_www_form(URI.parse(url).query.to_s).to_h
        end
      end

      attr_reader :requests

      def initialize
        @routes = []
        @requests = []
      end

      # `response` is a Response, a Hash (JSON body, 200), or a callable taking
      # the Request. `times` limits how often the route answers.
      def on(verb, matcher, response = nil, status: 200, headers: {}, times: nil, &block)
        @routes << { verb: verb, matcher: matcher, response: block || response, status: status, headers: headers,
                     times: times }
        self
      end

      def call(verb, url, headers, body)
        request = Request.new(verb: verb, url: url, headers: headers, body: body)
        @requests << request
        route = @routes.find { |r| r[:verb] == verb && match?(r[:matcher], url) && (r[:times].nil? || r[:times].positive?) }
        raise Error, "unscripted #{verb} #{url}" unless route

        route[:times] -= 1 if route[:times]
        answer = route[:response]
        answer = answer.call(request) if answer.respond_to?(:call)
        return answer if answer.is_a?(Response)
        raise answer if answer.is_a?(Exception)

        body = answer.nil? ? "" : (answer.is_a?(String) ? answer : JSON.generate(answer))
        Response.new(status: route[:status], headers: route[:headers].transform_keys { |k| k.to_s.downcase }, body: body)
      end

      def calls(verb = nil)
        verb ? @requests.select { |r| r.verb == verb } : @requests
      end

      private

      def match?(matcher, url)
        matcher.is_a?(Regexp) ? matcher.match?(url) : url.start_with?(matcher)
      end
    end
  end
end
