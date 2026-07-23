# frozen_string_literal: true

require_relative "art_styles"
require_relative "lexicon"
require_relative "spec"
require_relative "content_provider"

module Zer0Cms
  module Abc
    # The ABC book wizard. Headless and deterministic given its inputs: it walks
    # theme → content plan → art direction → per-letter composition → cover →
    # validated Spec. The Rails controller and the `bin/zer0-cms` CLI both drive
    # this same object, so the web and CLI flows can never diverge.
    #
    #   Wizard.new(theme: "IT systems", art_style: "isometric-tech-toy").run
    #     => Zer0Cms::Abc::Spec   (26 letters, prompts composed, images planned)
    class Wizard
      # Which provider to use:
      #   :auto          — deterministic when a bundled lexicon exists, else Anthropic
      #   :deterministic — bundled lexicon only (offline; the seed-book path)
      #   :anthropic     — always ask Claude (arbitrary themes)
      DEFAULT_PROVIDER = :auto

      attr_reader :warnings

      def initialize(theme:, series: SERIES, slug: nil, title: nil, subtitle: nil,
                     art_style: nil, palette: nil, background: "plain", mood: "playful",
                     lettering: nil, audience: nil, language: "en",
                     provider: DEFAULT_PROVIDER, art_styles: ArtStyles.default,
                     content_provider: nil, assets_prefix: "/assets/images/books")
        @theme = theme
        @series = series
        @slug = slug
        @title = title
        @subtitle = subtitle
        @art_style = art_style
        @palette = palette
        @background = background
        @mood = mood
        @lettering = lettering
        @audience = audience
        @language = language
        @provider_choice = provider.to_sym
        @styles = art_styles
        @content_provider = content_provider
        @assets_prefix = assets_prefix
        @warnings = []
      end

      def run
        plan = content_plan
        style = resolved_art_style(plan)
        @styles.style(style) # raises early on an unknown style id

        # Resolve the palette ONCE and thread it everywhere: the `palette:`
        # metadata, the cover plate, and every letter plate must agree. (Passing
        # the raw @palette — nil unless the caller set one — into the per-letter
        # prompts would let them fall back to the style's own default and diverge
        # from the palette the book advertises and its cover uses.)
        palette = @palette || plan["default_palette"] || @styles.default_palette(style)

        spec = Spec.new(
          "series"           => @series,
          "slug"             => resolved_slug(plan),
          "title"            => @title || plan["title"] || default_title,
          "subtitle"         => @subtitle || plan["subtitle"],
          "theme"            => @theme,
          "audience"         => @audience || plan["audience"] || "toddler",
          "language"         => @language,
          "art_style"        => style,
          "palette"          => palette,
          "background"       => @background,
          "mood"             => @mood,
          "lettering"        => @lettering || @styles.default_lettering(style),
          "art_style_prompt" => @styles.style_prompt(style),
          "generator"        => generator_note(plan),
          "alphabet"         => build_alphabet(plan, style, palette)
        )
        spec.cover = build_cover(spec, style)
        spec.validate!
      end

      private

      # -- content -------------------------------------------------------------

      def content_plan
        provider.plan(theme: @theme, audience: @audience || "toddler")
      end

      def provider
        return @content_provider if @content_provider

        name = resolve_provider_name
        ContentProvider.build(name)
      end

      def resolve_provider_name
        case @provider_choice
        when :deterministic, :anthropic
          @provider_choice
        when :auto
          if Lexicon.exist?(@theme)
            :deterministic
          else
            @warnings << "no bundled lexicon for #{@theme.inspect}; using the Anthropic provider"
            :anthropic
          end
        else
          raise ArgumentError, "unknown provider #{@provider_choice.inspect}"
        end
      end

      # -- art direction -------------------------------------------------------

      def resolved_art_style(plan)
        style = @art_style || plan["default_art_style"] || "isometric-tech-toy"
        unless @styles.style?(style)
          @warnings << "unknown art style #{style.inspect}; falling back to isometric-tech-toy"
          style = "isometric-tech-toy"
        end
        style
      end

      # -- assembly ------------------------------------------------------------

      def build_alphabet(plan, style, palette)
        slug = resolved_slug(plan)
        ContentProvider::LETTERS.map do |letter|
          e = plan.fetch("letters").fetch(letter)
          word = e.fetch("word")
          {
            "letter"  => letter,
            "word"    => word,
            "subject" => e.fetch("subject"),
            "tagline" => e.fetch("tagline"),
            "alt"     => e["alt"] || "#{word}, illustrated for the letter #{letter}.",
            "prompt"  => @styles.render_prompt(
              letter: letter, word: word, subject: e.fetch("subject"),
              style: style, palette: palette, background: @background, mood: @mood
            ),
            "image"   => image_path(slug, letter, word),
            "status"  => "planned"
          }
        end
      end

      def build_cover(spec, style)
        subject = "a joyful cover for an alphabet book about #{@theme}, " \
                  "a big friendly letter A and a smiling #{first_word(spec)}"
        {
          "subject" => subject,
          "prompt"  => @styles.render_prompt(
            letter: "A", word: first_word(spec), subject: subject,
            style: style, palette: spec.palette, background: "scene", mood: @mood
          ),
          "image"   => "#{@assets_prefix}/#{spec.slug}/cover.png",
          "alt"     => "Cover of #{spec.title}."
        }
      end

      def first_word(spec)
        spec.alphabet.first&.fetch("word") { "letter" } || "letter"
      end

      # -- helpers -------------------------------------------------------------

      def image_path(slug, letter, word)
        "#{@assets_prefix}/#{slug}/#{letter.downcase}-#{slugify(word)}.png"
      end

      def resolved_slug(plan)
        @slug ||= slugify(plan["title"] || @title || @theme)
      end

      def default_title
        "The #{@theme} Alphabet"
      end

      def generator_note(plan)
        source = plan["default_art_style"].nil? && !Lexicon.exist?(@theme) ? "Claude (Anthropic)" : "the bundled #{@theme} lexicon"
        "Text generated by the zer0-CMS ABC wizard from #{source}; illustrations " \
          "composed for the zer0-image-generator plugin and rendered by drsai."
      end

      def slugify(text)
        text.to_s.downcase.strip.gsub(/[^a-z0-9]+/, "-").gsub(/\A-+|-+\z/, "")
      end
    end
  end
end
