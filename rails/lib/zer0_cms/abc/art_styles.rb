# frozen_string_literal: true

require "yaml"

module Zer0Cms
  module Abc
    # Loads the shared ABC art-style catalog and composes per-letter prompts.
    #
    # The catalog (data/abc_art_styles.yml) is a byte-identical VENDORED COPY of
    # the source of truth in the zer0-image-generator gem
    # (lib/zer0_image_generator/abc/art_styles.yml). The prompt-composition
    # logic here mirrors that gem's StylePack#render_prompt so a book composed by
    # the content engine and one composed by the image plugin read the same.
    # Re-sync the data file whenever the gem's catalog changes.
    class ArtStyles
      CATALOG_PATH = File.join(__dir__, "..", "data", "abc_art_styles.yml")

      class UnknownStyle < StandardError; end

      attr_reader :version, :styles, :palettes, :backgrounds, :lettering,
                  :moods, :safety_suffix

      def self.default
        @default ||= from_file(CATALOG_PATH)
      end

      def self.from_file(path)
        new(YAML.safe_load_file(path))
      end

      def initialize(catalog)
        @version       = catalog.fetch("version", 1)
        @styles        = index(catalog.fetch("styles"))
        options        = catalog.fetch("options", {})
        @palettes      = index(options.fetch("palettes", []))
        @backgrounds   = index(options.fetch("backgrounds", []))
        @lettering     = index(options.fetch("lettering", []))
        @moods         = index(options.fetch("moods", []))
        @safety_suffix = squish(catalog.fetch("safety_suffix", ""))
      end

      def style_ids
        @styles.keys.sort
      end

      def style(id)
        @styles[id.to_s] ||
          raise(UnknownStyle, "unknown ABC art style: #{id.inspect} " \
                              "(known: #{style_ids.join(', ')})")
      end

      def style?(id)
        @styles.key?(id.to_s)
      end

      def default_palette(style_id)
        style(style_id)["default_palette"]
      end

      def default_lettering(style_id)
        style(style_id)["default_lettering"]
      end

      # The reusable style tag (denormalised into book front matter for the
      # publisher's colophon and any re-render).
      def style_prompt(style_id)
        squish(style(style_id).fetch("prompt"))
      end

      # Compose the text-free raster prompt for one letter. Deterministic and
      # kept identical to Zer0ImageGenerator::Abc::StylePack#render_prompt.
      def render_prompt(letter:, word:, subject:, style:, palette: nil,
                        background: "plain", mood: "playful")
        sty = style(style)
        palette_id = palette || sty["default_palette"]

        parts = [
          squish(sty.fetch("prompt")),
          fragment(@backgrounds, background),
          fragment(@palettes, palette_id),
          "Subject: #{subject.to_s.strip}, standing for the word " \
          "#{word.to_s.strip.upcase} (letter #{letter.to_s.strip.upcase}).",
          fragment(@moods, mood),
          @safety_suffix
        ].compact.reject(&:empty?)

        squish(parts.join(". ").gsub(/\.\s*\./, ".").strip)
      end

      def to_menu
        {
          "version" => @version,
          "styles" => @styles.values.map do |s|
            s.slice("id", "name", "summary", "default_palette",
                    "default_lettering", "best_for")
          end,
          "palettes"    => menu_of(@palettes),
          "backgrounds" => menu_of(@backgrounds),
          "lettering"   => menu_of(@lettering),
          "moods"       => menu_of(@moods)
        }
      end

      private

      def index(list)
        list.each_with_object({}) { |item, acc| acc[item.fetch("id")] = item }
      end

      def menu_of(hash)
        hash.values.map { |v| v.slice("id", "name") }
      end

      def fragment(catalog, id)
        return nil if id.nil?

        entry = catalog[id.to_s]
        entry && entry["fragment"] ? squish(entry["fragment"]) : nil
      end

      def squish(text)
        text.to_s.gsub(/\s+/, " ").strip
      end
    end
  end
end
