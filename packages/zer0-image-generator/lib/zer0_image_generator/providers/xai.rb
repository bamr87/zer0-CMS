# frozen_string_literal: true

require_relative "base"

module Zer0ImageGenerator
  # xAI (Grok) images/generations.
  class XAIProvider < Provider
    def name
      "xai"
    end

    def is_configured(env)
      key = env["XAI_API_KEY"]
      !key.nil? && !key.empty?
    end

    def missing_hint(_env)
      "XAI_API_KEY environment variable is required for the xAI provider"
    end

    def default_model
      "grok-2-image"
    end

    def generate(prompt, settings, out_base, ctx)
      model = Zer0ImageGenerator.effective_model(settings, self)
      out_path = out_base.sub_ext(".png")
      # xAI caps the prompt; the original engine slices the first 1000 chars.
      payload = { "model" => model, "prompt" => prompt[0, 1000], "n" => 1 }
      begin
        data = Http.with_retries("xAI API") do
          Http.json("https://api.x.ai/v1/images/generations",
                    payload,
                    { "Authorization" => "Bearer #{ctx.env.fetch('XAI_API_KEY')}" },
                    timeout: 900)
        end
        entries = data["data"] || []
        if entries.empty? || !write_image_payload(entries[0], out_path)
          return ImageResult.new(false, error: "No image data in xAI response")
        end

        ImageResult.new(true, "png", out_path)
      rescue HttpStatusError => exc
        ImageResult.new(false, error: "xAI API error: #{exc.error_message}")
      rescue StandardError => exc
        ImageResult.new(false, error: exc.message)
      end
    end
  end
end
