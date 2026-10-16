# frozen_string_literal: true

require_relative "abc/style_pack"

module Zer0ImageGenerator
  module Abc
    # High-level plugin entry point: turn an ABC Book Spec (the JSON/YAML the
    # zer0-CMS engine emits and drsai ships) into concrete render work, using
    # the shared art-style catalog for prompt composition.
    #
    # This is what makes zer0-image-generator "a plugin" of the pipeline: the
    # content engine owns WHAT each letter means; this gem owns HOW it looks and
    # how it renders. Both sides agree on the StylePack catalog and the spec
    # shape below.
    module Plugin
      module_function

      # A single unit of render work — mirrors drsai's tools Job so either the
      # Python illustrator or this gem's Runner can consume a plan.
      RenderJob = Struct.new(:letter, :word, :prompt, :out_path, :size, keyword_init: true)

      # Landscape by default reads well for a big centred subject on a card.
      DEFAULT_SIZE = "1024x1024"

      # Compose a prompt for every letter in `book`, mutating a copy of its
      # `alphabet` entries to carry a `prompt` (only where one is absent so
      # hand-authored overrides win). Returns the updated book hash.
      #
      # `book` is an ABC Book Spec hash with at least:
      #   "art_style"  => catalog style id
      #   "palette"/"background"/"mood" => option ids (optional)
      #   "alphabet"   => [ { "letter", "word", "subject", "prompt"? }, ... ]
      def compose_prompts(book, pack: StylePack.default)
        style      = book.fetch("art_style")
        palette    = book["palette"]
        background = book["background"] || "plain"
        mood       = book["mood"] || "playful"

        alphabet = Array(book["alphabet"]).map do |entry|
          e = entry.dup
          if e["prompt"].nil? || e["prompt"].to_s.strip.empty?
            e["prompt"] = pack.render_prompt(
              letter: e.fetch("letter"), word: e.fetch("word"),
              subject: e.fetch("subject"), style: style,
              palette: palette, background: background, mood: mood
            )
          end
          e
        end

        book.merge("alphabet" => alphabet)
      end

      # Build the list of RenderJobs for the letters that still need art.
      # `root` resolves each entry's leading-slash `image` path; a job is only
      # emitted when the target file does not already exist (idempotent, like
      # the drsai illustrator).
      def build_plan(book, root:, size: DEFAULT_SIZE, pack: StylePack.default)
        composed = compose_prompts(book, pack: pack)
        Array(composed["alphabet"]).filter_map do |entry|
          image = entry["image"]
          next if image.nil? || image.to_s.empty?

          out = File.join(root.to_s, image.to_s.sub(%r{\A/}, ""))
          next if File.exist?(out)

          RenderJob.new(
            letter: entry["letter"], word: entry["word"],
            prompt: entry["prompt"], out_path: out, size: size
          )
        end
      end
    end
  end
end
