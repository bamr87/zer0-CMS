# frozen_string_literal: true

require "socket"
require "uri"

module Zer0Cms
  module Distribution
    # The one request of a three-legged OAuth flow that comes back to a
    # terminal: LinkedIn redirects the member's browser to a loopback address,
    # and this listens there for exactly that request.
    #
    # It binds 127.0.0.1 only, answers anything that is not the callback path
    # with a 404 and keeps waiting, accepts one callback, and closes. The
    # authorization code it returns is single-use and expires in 30 minutes;
    # the caller checks `state` before exchanging it.
    module Callback
      module_function

      def wait(port:, path: "/callback", timeout: 300, host: "127.0.0.1")
        server = TCPServer.new(host, port)
        deadline = Time.now + timeout
        loop do
          remaining = deadline - Time.now
          raise LinkedIn::Error, "no OAuth callback arrived within #{timeout} seconds" if remaining <= 0
          next unless IO.select([server], nil, nil, remaining)

          socket = server.accept
          begin
            # A local client that connects and sends nothing must not hold the
            # flow past its deadline.
            line = IO.select([socket], nil, nil, 10) ? socket.gets("\n", 8192).to_s : ""
            params = parse_request_line(line, path)
            socket.write(response(params ? 200 : 404, params ? "zer0-CMS received LinkedIn's answer. You can close this tab." : "Not found."))
            return params if params
          ensure
            socket.close
          end
        end
      ensure
        server&.close
      end

      # `GET /callback?code=…&state=… HTTP/1.1` → { "code" => …, "state" => … }
      def parse_request_line(line, path = "/callback")
        match = %r{\AGET (\S+) HTTP/1\.[01]\r?\n?\z}.match(line.to_s)
        return nil unless match

        uri = URI.parse(match[1])
        return nil unless uri.path == path

        URI.decode_www_form(uri.query.to_s).to_h
      rescue URI::InvalidURIError, ArgumentError
        nil
      end

      def response(status, text)
        reason = status == 200 ? "OK" : "Not Found"
        "HTTP/1.1 #{status} #{reason}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: #{text.bytesize}\r\n" \
          "Connection: close\r\nCache-Control: no-store\r\n\r\n#{text}"
      end
    end
  end
end
