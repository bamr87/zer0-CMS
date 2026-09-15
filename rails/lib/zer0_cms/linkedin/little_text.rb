# frozen_string_literal: true

module Zer0Cms
  module LinkedIn
    # The Posts API's `little` text format for `commentary`.
    #
    # Fifteen characters are reserved — `| { } @ [ ] ( ) < > # \ * _ ~` — and
    # LinkedIn's documentation is explicit that every one of them must be
    # backslash-escaped to be read as text, "even if those characters are not
    # used in one of the supported elements". Sent raw, the text around an
    # unescaped reserved character is misparsed: the classic symptom is a post
    # silently cut off at its first parenthesis.
    #
    # Two things an author writes on purpose are kept as elements rather than
    # escaped into text:
    #
    # * a hashtag — `#` followed by letters or digits, not glued to a preceding
    #   word (`#SmallBusiness` stays a hashtag, `C#` becomes `C\#`);
    # * a mention written in LinkedIn's own syntax, `@[Name](urn:li:person:…)`
    #   or `…(urn:li:organization:…)`.
    #
    # Everything else reserved is escaped. `escape` is idempotent only in the
    # sense that matters for review: what a person approved is the unescaped
    # draft, and the payload preview shows both.
    module LittleText
      RESERVED = "|{}@[]()<>#\\*_~"
      TOKEN = /
        (?<mention>@\[[^\[\]\n]{1,200}\]\(urn:li:(?:person|organization|organizationBrand):[A-Za-z0-9_-]+\))
        |(?<hashtag>(?<![\p{L}\p{N}\\])\#[\p{L}\p{N}]+)
        |(?<reserved>[|{}@\[\]()<>\#\\*_~])
      /x

      module_function

      def escape(text)
        text.to_s.gsub(TOKEN) do
          match = Regexp.last_match
          match[:mention] || match[:hashtag] || "\\#{match[:reserved]}"
        end
      end
    end
  end
end
