# frozen_string_literal: true

module Zer0Cms
  module Distribution
    # Python's `json.dumps`, byte for byte, for the shapes a ledger holds.
    #
    # The ledger is one flat file that several lanes write — this library, the
    # VS Code extension (`pyJsonDump` in src/core/shared/jsonio.ts) and, for
    # years, a Python publisher. If two serializers disagreed by so much as a
    # space, the file would churn on every run and its git history would be
    # noise. So this reproduces Python's separators (`", "` flat, `","` plus a
    # newline when indented, `": "` always), recursive `sort_keys`, lowercase
    # `\uXXXX` escapes with surrogate pairs under `ensure_ascii`, and the
    # `repr` spelling of a float.
    module PyJson
      ESCAPES = { '"' => '\\"', "\\" => "\\\\", "\n" => "\\n", "\r" => "\\r", "\t" => "\\t", "\b" => "\\b",
                  "\f" => "\\f" }.freeze

      module_function

      def dump(value, indent: nil, sort_keys: false, ensure_ascii: true)
        emit(value, indent, sort_keys, ensure_ascii, 0)
      end

      def emit(value, indent, sort_keys, ascii, depth)
        case value
        when Hash
          return "{}" if value.empty?

          pairs = value.map { |key, item| [key.to_s, item] }
          pairs = pairs.sort_by(&:first) if sort_keys
          join("{", "}", pairs.map { |key, item| "#{string(key, ascii)}: #{emit(item, indent, sort_keys, ascii, depth + 1)}" },
               indent, depth)
        when Array
          return "[]" if value.empty?

          join("[", "]", value.map { |item| emit(item, indent, sort_keys, ascii, depth + 1) }, indent, depth)
        when String, Symbol then string(value.to_s, ascii)
        when true then "true"
        when false then "false"
        when nil then "null"
        when Integer then value.to_s
        when Float
          raise ArgumentError, "#{value} is not representable in JSON" unless value.finite?

          value.to_s.sub(".0e", "e")
        else
          raise ArgumentError, "cannot serialize #{value.class}"
        end
      end

      def join(open, close, items, indent, depth)
        return "#{open}#{items.join(", ")}#{close}" if indent.nil?

        inner = " " * (indent * (depth + 1))
        outer = " " * (indent * depth)
        "#{open}\n#{inner}#{items.join(",\n#{inner}")}\n#{outer}#{close}"
      end

      def string(text, ascii)
        out = +'"'
        text.each_char do |char|
          escaped = ESCAPES[char]
          code = char.ord
          if escaped
            out << escaped
          elsif code < 0x20 || (ascii && code > 0x7e)
            if code > 0xFFFF
              code -= 0x10000
              out << format("\\u%04x\\u%04x", 0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF))
            else
              out << format("\\u%04x", code)
            end
          else
            out << char
          end
        end
        out << '"'
      end
    end
  end
end
