# frozen_string_literal: true

require_relative "../constants"
require_relative "base"

module Zer0ImageGenerator
  # OpenAI images/generations + images/edits (the --enhance path).
  class OpenAIProvider < Provider
    def name
      "openai"
    end

    def is_configured(env)
      key = env["OPENAI_API_KEY"]
      !key.nil? && !key.empty?
    end

    def missing_hint(_env)
      "OPENAI_API_KEY environment variable is required for the OpenAI provider"
    end

    def default_model
      "gpt-image-2"
    end

    def generate(prompt, settings, out_base, ctx)
      model = Zer0ImageGenerator.effective_model(settings, self)
      size, quality = Zer0ImageGenerator.adapt_openai_size_quality(
        model, settings.size, settings.quality
      )
      out_path = out_base.sub_ext(".png")
      payload = { "model" => model, "prompt" => prompt, "n" => 1,
                  "size" => size, "quality" => quality }
      Logging.debug("OpenAI generate: model=#{model} size=#{size} quality=#{quality}")
      begin
        data = Http.with_retries("OpenAI API") do
          Http.json("https://api.openai.com/v1/images/generations",
                    payload, headers(ctx.env), timeout: 900)
        end
        entries = data["data"] || []
        if entries.empty? || !write_image_payload(entries[0], out_path)
          return ImageResult.new(false, error: "No image data in OpenAI response")
        end

        ImageResult.new(true, "png", out_path)
      rescue HttpStatusError => exc
        ImageResult.new(false, error: "OpenAI API error: #{exc.error_message}")
      rescue StandardError => exc
        ImageResult.new(false, error: exc.message)
      end
    end

    def edit(image_path, prompt, settings, ctx, out_path = nil)
      model = settings.enhance_model
      fields = {
        "prompt" => prompt,
        "model" => model,
        "n" => "1",
        "size" => "auto",
        "quality" => settings.enhance_quality,
        "output_format" => settings.enhance_format,
      }
      # gpt-image-2 does not accept input_fidelity (historical behavior).
      fields["input_fidelity"] = settings.enhance_fidelity if model != "gpt-image-2"
      image_bytes = File.binread(image_path.to_s)
      files = [["image[]", image_path.basename.to_s,
                image_bytes, Zer0ImageGenerator.image_media_type(image_bytes)]]
      out_path ||= image_path
      Logging.debug(
        "OpenAI edit: model=#{model} fidelity=" \
        "#{fields.fetch('input_fidelity', '(omitted)')} format=#{settings.enhance_format}"
      )
      begin
        data = Http.with_retries("OpenAI edits API") do
          Http.multipart("https://api.openai.com/v1/images/edits",
                         fields, files, headers(ctx.env), timeout: 900)
        end
        usage = data["usage"] || {}
        # Python `if usage.get("total_tokens")` treats 0 as absent — mirror that
        # so Ruby's truthy 0 doesn't emit a bogus "0 total" line.
        total_tokens = usage["total_tokens"]
        Logging.debug("Token usage: #{total_tokens} total") if total_tokens && total_tokens != 0
        entries = data["data"] || []
        if entries.empty? || !write_image_payload(entries[0], out_path)
          return ImageResult.new(false, error: "No image data in enhance response")
        end

        revised = entries[0]["revised_prompt"]
        Logging.debug("Revised prompt: #{revised[0, 200]}...") if revised && !revised.empty?
        ImageResult.new(true, "png", out_path)
      rescue HttpStatusError => exc
        ImageResult.new(false, error: "OpenAI enhance API error: #{exc.error_message}")
      rescue StandardError => exc
        ImageResult.new(false, error: exc.message)
      end
    end

    private

    def headers(env)
      { "Authorization" => "Bearer #{env.fetch('OPENAI_API_KEY')}" }
    end
  end
end
