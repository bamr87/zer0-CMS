# frozen_string_literal: true

require "json"
require "yaml"

module Zer0Cms
  module Abc
    # An in-memory ABC Book Spec — the object the wizard builds and the exporter
    # writes. Mirrors schema/abc-book.schema.json; `validate!` performs the
    # structural checks that matter without pulling in a JSON-Schema gem (the
    # engine is stdlib-only).
    class Spec
      SPEC_VERSION = 1
      LETTERS = ("A".."Z").to_a.freeze

      class InvalidSpec < StandardError; end

      attr_accessor :series, :slug, :title, :subtitle, :theme, :audience,
                    :language, :art_style, :palette, :background, :mood,
                    :lettering, :art_style_prompt, :generator, :cover, :alphabet

      def initialize(attrs = {})
        attrs = stringify(attrs)
        @series           = attrs["series"] || SERIES
        @slug             = attrs["slug"]
        @title            = attrs["title"]
        @subtitle         = attrs["subtitle"]
        @theme            = attrs["theme"]
        @audience         = attrs["audience"] || "toddler"
        @language         = attrs["language"] || "en"
        @art_style        = attrs["art_style"]
        @palette          = attrs["palette"]
        @background       = attrs["background"] || "plain"
        @mood             = attrs["mood"] || "playful"
        @lettering        = attrs["lettering"]
        @art_style_prompt = attrs["art_style_prompt"]
        @generator        = attrs["generator"]
        @cover            = attrs["cover"]
        @alphabet         = Array(attrs["alphabet"])
      end

      def self.from_json(text)
        new(JSON.parse(text))
      end

      def self.from_yaml(text)
        new(YAML.safe_load(text))
      end

      # Ordered hash matching the schema; nils/empties dropped so the emitted
      # spec and front matter stay tidy.
      def to_h
        h = {
          "spec_version"     => SPEC_VERSION,
          "series"           => series,
          "slug"             => slug,
          "title"            => title,
          "subtitle"         => subtitle,
          "theme"            => theme,
          "audience"         => audience,
          "language"         => language,
          "art_style"        => art_style,
          "palette"          => palette,
          "background"       => background,
          "mood"             => mood,
          "lettering"        => lettering,
          "art_style_prompt" => art_style_prompt,
          "generator"        => generator,
          "cover"            => cover,
          "alphabet"         => alphabet
        }
        h.reject { |_, v| v.nil? || (v.respond_to?(:empty?) && v.empty?) }
      end

      def to_json(*args)
        JSON.pretty_generate(to_h, *args)
      end

      def to_yaml
        to_h.to_yaml
      end

      def letters
        alphabet.map { |e| e["letter"] }
      end

      def validate!
        errors = []
        errors << "slug is required" if blank?(slug)
        errors << "slug must be url-safe (a-z0-9-)" if slug && slug !~ /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/
        errors << "title is required" if blank?(title)
        errors << "art_style is required" if blank?(art_style)
        unless %w[toddler preschool early-reader].include?(audience)
          errors << "audience #{audience.inspect} is not one of toddler/preschool/early-reader"
        end
        errors.concat(alphabet_errors)
        raise InvalidSpec, "invalid ABC Book Spec: #{errors.join('; ')}" unless errors.empty?

        self
      end

      private

      def alphabet_errors
        errs = []
        errs << "alphabet must have 1–26 letters (has #{alphabet.length})" unless (1..26).cover?(alphabet.length)
        seen = []
        alphabet.each_with_index do |e, i|
          %w[letter word subject tagline].each do |k|
            errs << "alphabet[#{i}] missing #{k}" if blank?(e[k])
          end
          l = e["letter"]
          errs << "alphabet[#{i}] letter #{l.inspect} must be A–Z" if l && !LETTERS.include?(l)
          errs << "duplicate letter #{l.inspect}" if l && seen.include?(l)
          seen << l
        end
        errs
      end

      def blank?(value)
        value.nil? || value.to_s.strip.empty?
      end

      def stringify(hash)
        (hash || {}).each_with_object({}) { |(k, v), acc| acc[k.to_s] = v }
      end
    end
  end
end
