# frozen_string_literal: true

module Zer0Cms
  module LinkedIn
    # Rest.li 2.0 query and path encoding.
    #
    # A URN inside a URL is percent-encoded (`urn:li:share:1` becomes
    # `urn%3Ali%3Ashare%3A1`), but the structural characters of a Rest.li
    # value — `List(` `,` `)` and a record's `(key:value)` — are not. So a value
    # is either a plain string, which `encode` escapes completely, or a `Raw`
    # built by `list` / `record`, which is inserted as written.
    module Restli
      Raw = Struct.new(:text) do
        def to_s
          text
        end
      end

      UNRESERVED = /[^A-Za-z0-9\-._~]/n

      module_function

      # RFC 3986 percent-encoding of every byte outside the unreserved set.
      def encode(value)
        return value.text if value.is_a?(Raw)

        value.to_s.dup.force_encoding(Encoding::BINARY)
             .gsub(UNRESERVED) { |byte| format("%%%02X", byte.ord) }
             .force_encoding(Encoding::UTF_8)
      end

      def raw(text)
        Raw.new(text.to_s)
      end

      # `List(urn%3Ali%3Ashare%3A1,urn%3Ali%3Ashare%3A2)`
      def list(values)
        raw("List(#{values.map { |value| encode(value) }.join(",")})")
      end

      # `(share:urn%3Ali%3Ashare%3A1)` — a Rest.li record with encoded values.
      def record(pairs)
        raw("(#{pairs.map { |key, value| "#{key}:#{value.is_a?(Raw) ? value.text : encode(value)}" }.join(",")})")
      end

      # `a=1&b=List(...)` from ordered pairs; nil values are dropped.
      def query(pairs)
        pairs.reject { |_, value| value.nil? }.map { |key, value| "#{encode(key)}=#{encode(value)}" }.join("&")
      end
    end
  end
end
