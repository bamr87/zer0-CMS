# frozen_string_literal: true

require_relative "base"

module Zer0ImageGenerator
  # Google Gemini generateContent. The image comes back as inline base64 nested
  # under candidates[].content.parts[], keyed either `inlineData` (REST/JSON) or
  # `inline_data` (proto) — accept both.
  class GeminiProvider < Provider
    def name
      "gemini"
    end

    def is_configured(env)
      key = env["GEMINI_API_KEY"]
      !key.nil? && !key.empty?
    end

    def missing_hint(_env)
      "GEMINI_API_KEY environment variable is required for the Gemini provider"
    end

    def default_model
      "gemini-2.5-flash-image"
    end

    def generate(prompt, settings, out_base, ctx)
      model = Zer0ImageGenerator.effective_model(settings, self)
      out_path = out_base.sub_ext(".png")
      url = "https://generativelanguage.googleapis.com/v1beta/models/" \
            "#{model}:generateContent"
      payload = { "contents" => [{ "parts" => [{ "text" => prompt }] }] }
      begin
        data = Http.with_retries("Gemini API") do
          Http.json(url, payload,
                    { "x-goog-api-key" => ctx.env.fetch("GEMINI_API_KEY") },
                    timeout: 900)
        end
        (data["candidates"] || []).each do |candidate|
          parts = ((candidate["content"] || {})["parts"]) || []
          parts.each do |part|
            inline = part["inlineData"] || part["inline_data"]
            next unless inline

            payload_b64 = inline["data"]
            next if payload_b64.nil? || payload_b64.empty?

            File.binwrite(out_path.to_s, Base64.decode64(payload_b64))
            return ImageResult.new(true, "png", out_path)
          end
        end
        ImageResult.new(false, error: "No inline image data in Gemini response")
      rescue HttpStatusError => exc
        ImageResult.new(false, error: "Gemini API error: #{exc.error_message}")
      rescue StandardError => exc
        ImageResult.new(false, error: exc.message)
      end
    end
  end
end
