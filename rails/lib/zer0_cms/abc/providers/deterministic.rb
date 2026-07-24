# frozen_string_literal: true

require_relative "../content_provider"
require_relative "../lexicon"

module Zer0Cms
  module Abc
    module Providers
      # Offline content provider: builds the plan from a bundled themed lexicon
      # (lexicons/*.yml). Needs no network or API key, so the seed book and the
      # whole test suite are fully reproducible. This is the default provider.
      class Deterministic < ContentProvider
        def supports?(theme)
          Lexicon.exist?(theme)
        end

        def plan(theme:, audience: "toddler")
          lex = Lexicon.for(theme)
          letters = ContentProvider::LETTERS.each_with_object({}) do |l, acc|
            e = lex.entry(l)
            acc[l] = {
              "word"    => e.fetch("word"),
              "subject" => e.fetch("subject"),
              "tagline" => e.fetch("tagline"),
              "alt"     => e["alt"]
            }
          end
          validate_plan!(
            "title"             => lex.title,
            "subtitle"          => lex.subtitle,
            "default_art_style" => lex.default_art_style,
            "default_palette"   => lex.default_palette,
            "letters"           => letters
          )
        end
      end

      ContentProvider.register(:deterministic, Deterministic)
    end
  end
end
