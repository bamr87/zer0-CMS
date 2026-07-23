# frozen_string_literal: true

require_relative "base"

module Zer0ImageGenerator
  # Stability AI SDXL v1 text-to-image. Returns base64 under `artifacts`, not the
  # OpenAI-style `data` envelope, so it decodes inline rather than via
  # write_image_payload.
  class StabilityProvider < Provider
    def name
      "stability"
    end

    def is_configured(env)
      key = env["STABILITY_API_KEY"]
      !key.nil? && !key.empty?
    end

    def missing_hint(_env)
      "STABILITY_API_KEY environment variable is required for the Stability AI provider"
    end

    def default_model
      "stable-diffusion-xl-1024-v1-0"
    end

    def generate(prompt, _settings, out_base, ctx)
      out_path = out_base.sub_ext(".png")
      payload = {
        "text_prompts" => [{ "text" => prompt }],
        "cfg_scale" => 7,
        # SDXL v1 endpoint accepts fixed dimension sets; 1024x1024 preserved
        # from the original engine.
        "height" => 1024,
        "width" => 1024,
        "samples" => 1,
        "steps" => 30,
      }
      begin
        data = Http.with_retries("Stability API") do
          Http.json(
            "https://api.stability.ai/v1/generation/" \
            "stable-diffusion-xl-1024-v1-0/text-to-image",
            payload,
            { "Authorization" => "Bearer #{ctx.env.fetch('STABILITY_API_KEY')}" },
            timeout: 900
          )
        end
        artifacts = data["artifacts"] || []
        first_b64 = artifacts.empty? ? nil : artifacts[0]["base64"]
        if artifacts.empty? || first_b64.nil? || first_b64.empty?
          return ImageResult.new(false, error: "No image data in Stability response")
        end

        File.binwrite(out_path.to_s, Base64.decode64(first_b64))
        ImageResult.new(true, "png", out_path)
      rescue HttpStatusError => exc
        ImageResult.new(false, error: "Stability API error: #{exc.error_message}")
      rescue StandardError => exc
        ImageResult.new(false, error: exc.message)
      end
    end
  end
end
