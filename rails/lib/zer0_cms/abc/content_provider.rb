# frozen_string_literal: true

module Zer0Cms
  module Abc
    # Strategy interface: given a theme, produce the *words* of an ABC book —
    # for every letter A–Z, the concept it stands for, a drawable subject, a
    # read-aloud tagline and alt text, plus book-level title/style defaults.
    #
    # Art direction (turning subjects into raster prompts) is a separate concern
    # owned by ArtStyles, so a provider never has to know about illustration.
    #
    #   plan(theme:, audience:) => {
    #     "title", "subtitle", "default_art_style", "default_palette",
    #     "letters" => { "A" => {"word","subject","tagline","alt"}, ... A..Z }
    #   }
    class ContentProvider
      LETTERS = ("A".."Z").to_a.freeze

      # Provider registry so the CLI/Rails can pick one by name.
      REGISTRY = {}

      def self.register(name, klass)
        REGISTRY[name.to_s] = klass
      end

      def self.build(name, **opts)
        klass = REGISTRY.fetch(name.to_s) do
          raise ArgumentError, "unknown content provider #{name.inspect} " \
                               "(known: #{REGISTRY.keys.sort.join(', ')})"
        end
        klass.new(**opts)
      end

      def self.names
        REGISTRY.keys.sort
      end

      # @return [Hash] the content plan (see above).
      def plan(theme:, audience: "toddler")
        raise NotImplementedError, "#{self.class} must implement #plan"
      end

      # Whether this provider can serve `theme` without falling back.
      def supports?(_theme)
        true
      end

      protected

      # Validate that a plan covers all 26 letters with the required fields —
      # shared by every provider so bad LLM output fails loudly, not silently.
      def validate_plan!(plan)
        letters = plan["letters"] || {}
        missing = LETTERS.reject { |l| letters[l].is_a?(Hash) }
        raise ArgumentError, "content plan missing letters: #{missing.join(', ')}" unless missing.empty?

        LETTERS.each do |l|
          %w[word subject tagline].each do |k|
            if letters[l][k].to_s.strip.empty?
              raise ArgumentError, "content plan letter #{l} missing #{k}"
            end
          end
        end
        plan
      end
    end
  end
end
