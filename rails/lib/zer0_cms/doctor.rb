# frozen_string_literal: true

require "json"

module Zer0Cms
  # What is left of the Ruby `zer0 doctor` (PLAN G4): its reader for the
  # zer0.json dialect, JSON with comments and trailing commas, which the
  # LinkedIn distribution lane (lib/zer0_cms/distribution: Config and Guard)
  # still reads zer0.json with until PLAN G5 absorbs the lane. The doctor is
  # the platform's now — content/sites/doctor.py, run by `bin/zer0 doctor`
  # and the reusable zer0-doctor.yml — held to this one's recorded findings
  # by content/tests/sites/test_doctor.py.
  module Doctor
    # JSON with comments and trailing commas (the zer0.json dialect), read
    # with the stdlib JSON parser after both are stripped outside strings.
    module Jsonc
      module_function

      def parse(text)
        JSON.parse(strip_trailing_commas(strip_comments(text.to_s.delete_prefix("﻿"))))
      end

      def strip_comments(text)
        chars = text.chars
        out = +""
        i = 0
        in_string = false
        while i < chars.size
          char = chars[i]
          if in_string
            out << char
            if char == "\\"
              out << chars[i + 1].to_s
              i += 1
            elsif char == '"'
              in_string = false
            end
          elsif char == '"'
            in_string = true
            out << char
          elsif char == "/" && chars[i + 1] == "/"
            i += 1 while i < chars.size && chars[i] != "\n"
            next
          elsif char == "/" && chars[i + 1] == "*"
            close = i + 2
            close += 1 while close < chars.size && !(chars[close] == "*" && chars[close + 1] == "/")
            raise JSON::ParserError, "unterminated /* comment" if close >= chars.size

            out << chars[i..(close + 1)].join.gsub(/[^\n]/, " ")
            i = close + 2
            next
          else
            out << char
          end
          i += 1
        end
        out
      end

      def strip_trailing_commas(text)
        chars = text.chars
        out = +""
        in_string = false
        i = 0
        while i < chars.size
          char = chars[i]
          if in_string
            out << char
            if char == "\\"
              out << chars[i + 1].to_s
              i += 1
            elsif char == '"'
              in_string = false
            end
          elsif char == '"'
            in_string = true
            out << char
          elsif char == ","
            j = i + 1
            j += 1 while j < chars.size && chars[j].match?(/\s/)
            out << char unless ["]", "}"].include?(chars[j])
          else
            out << char
          end
          i += 1
        end
        out
      end
    end
  end
end
