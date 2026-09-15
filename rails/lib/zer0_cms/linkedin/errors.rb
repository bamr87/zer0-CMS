# frozen_string_literal: true

module Zer0Cms
  module LinkedIn
    class Error < StandardError; end

    # A request the declared plan does not contain, a host outside it, or a
    # scope the token is known not to hold. Raised before any socket opens.
    class Refused < Error; end

    # The socket could not be opened, or the peer went away.
    class NetworkError < Error; end

    # A non-2xx answer from LinkedIn, after the retries a call is allowed.
    #
    # The message is built from LinkedIn's error body and never from the
    # request, so a bearer token or a client secret cannot reach a log through
    # it; `Client` additionally scrubs any credential it holds out of the text.
    class HTTPError < Error
      attr_reader :status, :code, :request_id, :body

      def initialize(status, message, code: nil, request_id: nil, body: nil)
        @status = status
        @code = code
        @request_id = request_id
        @body = body
        detail = +"HTTP #{status}: #{message}"
        detail << " (#{code})" if code
        detail << " [x-li-uuid #{request_id}]" if request_id
        super(detail)
      end

      def unauthorized?
        status == 401
      end

      def forbidden?
        status == 403
      end

      def not_found?
        status == 404
      end
    end
  end
end
