# frozen_string_literal: true

require "fileutils"
require "yaml"
require "json"
require_relative "spec"

module Zer0Cms
  module Abc
    # Writes an ABC Book Spec into a Jekyll site (drsai) as a `books`-collection
    # board book plus a machine-readable sidecar. This is the hand-off seam
    # between the content engine and the publisher: everything the wizard decided
    # becomes front matter the zer0-mistakes `book-abc` layout renders and the
    # zer0-image-generator plugin renders art from.
    #
    # Layout on disk (relative to the target site root):
    #   pages/_books/<slug>/index.md    the board book (layout: book-abc)
    #   _data/abc_books/<slug>.json     the ABC Book Spec (round-trip / re-render)
    class JekyllExporter
      AUDIENCE_LABELS = {
        "toddler"      => "Ages 1–4 (toddler board book)",
        "preschool"    => "Ages 3–5 (preschool)",
        "early-reader" => "Ages 5–7 (early reader)"
      }.freeze

      Result = Struct.new(:book_path, :spec_path, :planned_images, keyword_init: true)

      def initialize(spec, site_root:, collections_dir: "pages")
        @spec = spec.validate!
        @root = site_root.to_s
        @collections_dir = collections_dir
      end

      # Writes the bundle and returns a Result with the paths it created and the
      # list of declared-but-missing image paths (what the illustrator renders).
      def export
        book_dir = File.join(@root, @collections_dir, "_books", @spec.slug)
        FileUtils.mkdir_p(book_dir)
        book_path = File.join(book_dir, "index.md")
        File.write(book_path, render_markdown)

        spec_dir = File.join(@root, "_data", "abc_books")
        FileUtils.mkdir_p(spec_dir)
        spec_path = File.join(spec_dir, "#{@spec.slug}.json")
        File.write(spec_path, "#{@spec.to_json}\n")

        Result.new(
          book_path: book_path,
          spec_path: spec_path,
          planned_images: planned_images
        )
      end

      # Preview the book markdown without writing anything (used by the web UI).
      def render_markdown
        "#{front_matter.to_yaml}---\n\n#{body}"
      end

      private

      def front_matter
        {
          "title"            => @spec.title,
          "subtitle"         => @spec.subtitle,
          "layout"           => "book-abc",
          "book"             => @spec.slug,
          "series"           => @spec.series,
          "audience"         => AUDIENCE_LABELS.fetch(@spec.audience, @spec.audience),
          "status"           => book_status,
          "art_style"        => @spec.art_style,
          "art_style_prompt" => @spec.art_style_prompt,
          "palette"          => @spec.palette,
          "lettering"        => @spec.lettering,
          "cover_image"      => @spec.cover&.fetch("image", nil),
          "cover_prompt"     => @spec.cover&.fetch("prompt", nil),
          "preview"          => @spec.cover&.fetch("image", nil),
          "description"      => description,
          "generator"        => @spec.generator,
          "alphabet"         => @spec.alphabet.map { |e| letter_front_matter(e) }
        }.reject { |_, v| v.nil? }
      end

      def letter_front_matter(entry)
        {
          "letter"  => entry["letter"],
          "word"    => entry["word"],
          "tagline" => entry["tagline"],
          "image"   => entry["image"],
          "alt"     => entry["alt"],
          "prompt"  => entry["prompt"],
          "status"  => entry["status"] || "planned"
        }.reject { |_, v| v.nil? }
      end

      def body
        # One physical line per paragraph — the fleet's markdown "oneline" lint
        # (tools/unwrap-prose.py) requires it, so the generated page stays clean.
        "A first alphabet about **#{@spec.theme}** — one big friendly letter per " \
          "page, a word to say out loud, and a picture to point at. Read it top " \
          "to bottom, or jump to any letter.\n"
      end

      def description
        "A #{@spec.audience} ABC picture book about #{@spec.theme}: one letter, " \
          "one word, one picture per page — from #{@spec.alphabet.first['tagline']}"
      end

      def book_status
        rendered = @spec.alphabet.all? { |e| e["status"] == "rendered" }
        rendered ? "complete" : "illustrations-planned"
      end

      def planned_images
        images = @spec.alphabet
                      .select { |e| e["status"] != "rendered" }
                      .map { |e| e["image"] }
        images << @spec.cover["image"] if @spec.cover && @spec.cover["image"]
        images.compact
      end
    end
  end
end
