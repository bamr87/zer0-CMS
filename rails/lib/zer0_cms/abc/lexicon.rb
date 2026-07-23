# frozen_string_literal: true

require "yaml"

module Zer0Cms
  module Abc
    # A themed A–Z lexicon: for each letter, the concept it stands for plus a
    # drawable subject, read-aloud tagline, and alt text. Ships the "IT systems"
    # lexicon so the seed book generates fully offline; drop a new YAML in
    # lexicons/ to add a theme (or let the Anthropic provider invent one).
    class Lexicon
      LEXICON_DIR = File.join(__dir__, "lexicons")

      LETTERS = ("A".."Z").to_a.freeze

      class UnknownTheme < StandardError; end

      attr_reader :theme, :title, :subtitle, :default_art_style,
                  :default_palette, :audience, :letters

      # Look up a lexicon by theme name (case/spacing-insensitive) or by slug.
      def self.for(theme)
        slug = slugify(theme)
        path = File.join(LEXICON_DIR, "#{slug}.yml")
        unless File.file?(path)
          raise UnknownTheme, "no bundled lexicon for theme #{theme.inspect} " \
                              "(looked for #{slug}.yml; available: #{available.join(', ')})"
        end
        from_file(path)
      end

      def self.available
        Dir.glob(File.join(LEXICON_DIR, "*.yml")).map { |p| File.basename(p, ".yml") }.sort
      end

      def self.exist?(theme)
        File.file?(File.join(LEXICON_DIR, "#{slugify(theme)}.yml"))
      end

      def self.from_file(path)
        new(YAML.safe_load_file(path))
      end

      def self.slugify(text)
        text.to_s.downcase.strip.gsub(/[^a-z0-9]+/, "_").gsub(/\A_+|_+\z/, "")
      end

      def initialize(data)
        @theme             = data.fetch("theme")
        @title             = data["title"]
        @subtitle          = data["subtitle"]
        @default_art_style = data["default_art_style"]
        @default_palette   = data["default_palette"]
        @audience          = data["audience"] || "toddler"
        @letters           = data.fetch("letters")
        assert_complete!
      end

      # The entry for a letter: {"word","subject","tagline","alt"}.
      def entry(letter)
        @letters.fetch(letter.to_s.upcase)
      end

      private

      def assert_complete!
        missing = LETTERS.reject { |l| @letters.key?(l) }
        return if missing.empty?

        raise ArgumentError, "lexicon #{@theme.inspect} is missing letters: #{missing.join(', ')}"
      end
    end
  end
end
