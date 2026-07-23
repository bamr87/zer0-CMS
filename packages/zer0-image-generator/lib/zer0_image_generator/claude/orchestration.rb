# frozen_string_literal: true

require "json"

require_relative "../constants"
require_relative "../content"
require_relative "../logging"

module Zer0ImageGenerator
  # The analyze + review stages: Claude ORCHESTRATES (writes the art-direction
  # brief, vision-reviews the render), an image model RENDERS. Both stages are
  # enhancement layers that degrade to the template prompt / an approval on any
  # failure — neither may ever be a hard dependency of a generation run.
  #
  # The `client` argument is duck-typed against AnthropicClient (`complete`,
  # `complete_vision`), so a Rails app can inject a fake without this module
  # depending on the client class.
  module Orchestration
    module_function

    def claude_model_for(settings)
      # `settings.claude_model or DEFAULT_CLAUDE_MODEL`: an empty configured
      # model falls through to the engine default.
      model = settings.claude_model
      model.to_s.empty? ? DEFAULT_CLAUDE_MODEL : model
    end

    # Analyze stage (prompt_engine: claude): Claude reads the article and writes
    # the art-direction brief the renderer will receive. Falls back to the
    # template prompt on any failure.
    def claude_article_brief(client, cf, settings, base_prompt)
      excerpt = Content.collapse_whitespace((cf.content || "")[0, 1500])
      article =
        "ARTICLE\nTitle: #{Content.py_str(cf.title)}\n" \
        "Description: #{none_if_blank(cf.description)}\n" \
        "Categories/tags: #{none_if_blank(cf.categories)}\n" \
        "Excerpt: #{none_if_blank(excerpt)}\n\n" \
        "MANDATORY STYLE DIRECTIONS\nArt style: #{Content.py_str(settings.style)}\n" \
        "Style modifiers: #{none_if_blank(settings.style_modifiers)}\n\n" \
        "Write the image-generation prompt now."

      begin
        text = py_strip(client.complete(
                          ART_DIRECTOR_SYSTEM, article,
                          model: claude_model_for(settings), max_tokens: 2048,
                          effort: settings.claude_effort
                        ))
        unless text.empty?
          Logging.debug("Claude art-direction brief: #{text[0, 300]}...")
          return text
        end
        Logging.warn("Claude analysis returned empty text; using template prompt")
      rescue StandardError => e
        Logging.warn("Claude analysis failed (#{e.message}); using template prompt")
      end
      base_prompt
    end

    # Tolerant JSON extraction: the reviewer is told "JSON only" but models
    # occasionally wrap prose or fences around it, so we take the outermost
    # brace pair and parse that.
    def extract_json_object(text)
      start = text.index("{")
      finish = text.rindex("}")
      return nil if start.nil? || finish.nil? || finish <= start

      begin
        data = JSON.parse(text[start..finish])
      rescue JSON::ParserError
        return nil
      end
      data.is_a?(Hash) ? data : nil
    end

    # Review stage (review_engine: claude): Claude inspects the rendered banner.
    # Returns [approved, critique, revised_prompt]. Any failure counts as
    # approval — review must never block generation.
    def claude_review_image(client, image_path, cf, prompt, settings)
      mods = settings.style_modifiers
      style_line = Content.py_str(settings.style) +
                   (Content.truthy?(mods) ? "; #{Content.py_str(mods)}" : "")
      context =
        "ARTICLE\nTitle: #{Content.py_str(cf.title)}\n" \
        "Description: #{none_if_blank(cf.description)}\n" \
        "Categories/tags: #{none_if_blank(cf.categories)}\n\n" \
        "REQUIRED STYLE\n#{style_line}" \
        "\n\nPROMPT THE IMAGE WAS GENERATED FROM\n#{Content.py_str(prompt)}\n\n" \
        "Review the image above against the article and style. JSON only."

      begin
        text = client.complete_vision(
          REVIEWER_SYSTEM, context, image_path,
          model: claude_model_for(settings), effort: settings.claude_effort
        )
        data = extract_json_object(text)
        unless data
          Logging.warn("Claude review returned no parseable verdict; keeping image")
          return [true, "", ""]
        end
        verdict = Content.py_str(data.fetch("verdict", "approve")).downcase
        critique = py_strip(Content.py_str(data.fetch("critique", "")))
        revised = py_strip(Content.py_str(data.fetch("revised_prompt", "")))
        return [false, critique, revised] if verdict == "revise" && !revised.empty?

        [true, critique, ""]
      rescue StandardError => e
        Logging.warn("Claude review failed (#{e.message}); keeping image")
        [true, "", ""]
      end
    end

    # `value or '(none)'` with CPython truthiness: nil, false, and "" become
    # the "(none)" placeholder; everything else prints via str().
    def none_if_blank(value)
      Content.truthy?(value) ? Content.py_str(value) : "(none)"
    end

    # `str.strip()` with CPython's whitespace set. Reuses the content layer's
    # single source of truth for that set rather than duplicating the codepoint
    # table (Ruby's own String#strip is ASCII-only and also eats NUL, which
    # Python's does not). Unlike collapse_whitespace this trims edges only.
    PY_STRIP_RE = /\A[#{Content::PY_SPACE_CLASS}]+|[#{Content::PY_SPACE_CLASS}]+\z/.freeze

    def py_strip(text)
      text.to_s.gsub(PY_STRIP_RE, "")
    end
  end
end
