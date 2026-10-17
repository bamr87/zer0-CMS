# frozen_string_literal: true

require "yaml"

module Zer0ImageGenerator
  # ABC / alphabet-book illustration support.
  #
  # This module is the plugin seam by which the fleet's content engine
  # (zer0-CMS) and publisher (drsai) drive THIS gem to illustrate children's
  # ABC books. It is deliberately self-contained and ADDITIVE: it requires
  # nothing from the byte-identity engine port (constants.rb / prompt.rb /
  # runner.rb) and changes none of it, so the deterministic `local` provider
  # and every committed sample stay bit-for-bit unchanged.
  #
  # It owns two things:
  #   * the art-style catalog (art_styles.yml) — the SOURCE OF TRUTH shared,
  #     by vendored copy, with zer0-CMS and the zer0-mistakes theme; and
  #   * StylePack, which composes one raster prompt per alphabet letter from a
  #     style id + a few knobs, in a way that is stable and reproducible.
  #
  # The composed prompt is text-free by contract (the big letter is HTML
  # typography in the theme), so raster models never garble spelling.
  module Abc
    CATALOG_PATH = File.join(__dir__, "art_styles.yml")

    class UnknownStyle < StandardError; end

    # Loads and indexes art_styles.yml. Frozen after load; cheap to keep one
    # shared instance via .default, or build your own for a custom catalog.
    class StylePack
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
        freeze
      end

      # All selectable style ids, sorted — handy for a wizard's menu.
      def style_ids
        @styles.keys.sort
      end

      def style(id)
        @styles[id.to_s] || raise(UnknownStyle, "unknown ABC art style: #{id.inspect} " \
                                                 "(known: #{style_ids.join(', ')})")
      end

      def style?(id)
        @styles.key?(id.to_s)
      end

      # Compose the raster prompt for a single letter.
      #
      #   letter  — "A".."Z" (rendered by the theme, never drawn into the art)
      #   word    — the concept the letter stands for, e.g. "Automation"
      #   subject — a concrete, drawable scene for the word, e.g.
      #             "a friendly robot arm stacking blocks"
      #   style   — a style id from the catalog (String/Symbol)
      #   palette:/background:/mood: — option ids; nil falls back to the
      #             style's defaults (palette) or a sensible default.
      #
      # Returns a single-line String prompt. Deterministic: same inputs → same
      # bytes, so committed books re-render identically.
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

      # The default HTML lettering hint for a style (theme consumes this).
      def lettering_for(style_id)
        style(style_id)["default_lettering"]
      end

      # A compact, serialisable description of the whole catalog — what a
      # wizard renders as its style/option menus.
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
        list.each_with_object({}) { |item, acc| acc[item.fetch("id")] = item }.freeze
      end

      def menu_of(hash)
        hash.values.map { |v| v.slice("id", "name") }
      end

      def fragment(catalog, id)
        return nil if id.nil?

        entry = catalog[id.to_s]
        return nil if entry.nil?

        frag = entry["fragment"]
        frag.nil? ? nil : squish(frag)
      end

      # Collapse folded-YAML newlines / runs of whitespace into single spaces.
      def squish(text)
        text.to_s.gsub(/\s+/, " ").strip
      end
    end
  end
end
