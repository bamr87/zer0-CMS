# frozen_string_literal: true

require_relative "base"
require_relative "xai_auth"

module Zer0ImageGenerator
  # xAI (Grok) images/generations.
  #
  # Two ways in, tried in order (XAIAuth owns the resolution): a Grok OAuth
  # access token, then the XAI_API_KEY. Both are Bearer credentials on the same
  # endpoint, so the fallback is genuinely a retry with a different token — an
  # OAuth token that has gone stale between runs costs one rejected request and
  # then rides the API key instead of failing the page.
  class XAIProvider < Provider
    # Statuses that mean "this credential is no good" rather than "this request
    # is no good" — the only ones worth re-trying on the next rung.
    AUTH_FAILURE_STATUSES = [401, 403].freeze

    # xAI caps the prompt; the original engine slices the first 1000 chars.
    PROMPT_LIMIT = 1000

    def name
      "xai"
    end

    def is_configured(env)
      !XAIAuth.chain(env).empty?
    end

    def missing_hint(_env)
      XAIAuth::MISSING_HINT
    end

    def auth_description(env)
      XAIAuth.describe(env)
    end

    def default_model
      "grok-2-image"
    end

    def generate(prompt, settings, out_base, ctx)
      credentials = XAIAuth.chain(ctx.env)
      return ImageResult.new(false, error: XAIAuth::MISSING_HINT) if credentials.empty?

      model = Zer0ImageGenerator.effective_model(settings, self)
      out_path = out_base.sub_ext(".png")
      payload = { "model" => model, "prompt" => prompt[0, PROMPT_LIMIT], "n" => 1 }
      url = "#{XAIAuth.base_url(ctx.env)}/images/generations"

      credentials.each_with_index do |credential, index|
        Logging.debug("xAI generate: model=#{model} auth=#{credential.source}")
        begin
          data = Http.with_retries("xAI API") do
            Http.json(url, payload, credential.headers, timeout: 900)
          end
          entries = data["data"] || []
          if entries.empty? || !write_image_payload(entries[0], out_path)
            return ImageResult.new(false, error: "No image data in xAI response")
          end

          return ImageResult.new(true, "png", out_path)
        rescue HttpStatusError => exc
          fallback = credentials[index + 1]
          if AUTH_FAILURE_STATUSES.include?(exc.status) && fallback
            Logging.warn("xAI rejected the #{credential.source} (HTTP #{exc.status}) — " \
                         "retrying with #{fallback.source}")
            next
          end

          return ImageResult.new(false, error: "xAI API error: #{exc.error_message}")
        rescue StandardError => exc
          return ImageResult.new(false, error: exc.message)
        end
      end

      # Unreachable: the last rung has no fallback and always returns above.
      ImageResult.new(false, error: "No usable xAI credential")
    end
  end
end
