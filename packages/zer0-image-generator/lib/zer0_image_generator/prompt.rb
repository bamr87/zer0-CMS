# frozen_string_literal: true

require_relative "content"

module Zer0ImageGenerator
  # Prompt layer: turn a ContentFile plus resolved Settings into the text prompt
  # the image model receives. Ported from the oracle
  # (lib/zer0_image_generator/preview_generator.py). Wording is carried over
  # verbatim from the original engine and must not drift — the committed showcase
  # briefs were produced from these exact strings.
  module Prompt
    # Fallback used by build_enhance_prompt when settings.enhance_prompt is
    # empty. Kept byte-identical to the oracle's DEFAULT_ENHANCE_PROMPT.
    DEFAULT_ENHANCE_PROMPT =
      "Improve this preview banner image: fix any misspelled, garbled, or " \
      "incorrect text so it reads clearly and accurately. Sharpen visual details " \
      "and improve composition while preserving the original art style, color " \
      "palette, and theme. Ensure the image is clean and professional."

    # Template prompt — wording carried over from the original engine.
    def self.build_prompt(cf, settings)
      parts = ["Create a blog preview banner image for an article titled '#{cf.title}'."]
      parts << "The article is about: #{cf.description}." unless cf.description.empty?
      parts << "Categories: #{cf.categories}." unless cf.categories.empty?
      # First 500 characters, whitespace-collapsed — Content.collapse_whitespace
      # reproduces CPython's `re.sub(r"\s+", " ", ...).strip()` exactly.
      excerpt = Content.collapse_whitespace(cf.content[0, 500] || "")
      parts << "Key themes from content: #{excerpt}" unless excerpt.empty?
      parts << "Art style: #{settings.style}."
      unless settings.style_modifiers.empty?
        parts << "Additional style: #{settings.style_modifiers}."
      end
      parts << "The image should be suitable as a wide blog header/banner image with " \
               "clean composition. No text or words in the image."
      parts.join(" ")
    end

    def self.build_enhance_prompt(cf, settings)
      prompt = settings.enhance_prompt.empty? ? DEFAULT_ENHANCE_PROMPT : settings.enhance_prompt
      unless cf.title.empty?
        prompt += " Context: This is a preview banner for an article titled '#{cf.title}'."
      end
      prompt += " Article topic: #{cf.description}." unless cf.description.empty?
      prompt += " Maintain the #{settings.style} artistic style."
      prompt
    end
  end
end
