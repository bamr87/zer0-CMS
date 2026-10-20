# frozen_string_literal: true

require "base64"

require_relative "../constants"
require_relative "../http"
require_relative "../providers/xai_auth"

module Zer0ImageGenerator
  # OpenAI-compatible chat client for api.x.ai. Duck-typed against
  # AnthropicClient (`complete`, `complete_vision`, `available?`, `describe`)
  # so the analyze/review stages can run on Grok with the same OAuth token
  # the image renderer already uses.
  class GrokClient
    DEFAULT_MODEL = "grok-4"

    def initialize(env = nil, transport: nil)
      @env = env.nil? ? ENV.to_h : env.to_h
      @transport = transport || Http
      @credential = XAIAuth.chain(@env).first
    end

    def available?
      !@credential.nil?
    end

    def describe
      @credential ? @credential.source : "none"
    end

    def complete(system_text, user_text, model: DEFAULT_MODEL,
                 max_tokens: 2048, effort: "")
      raise "no xAI credential configured" unless @credential

      payload = {
        "model" => resolve_model(model),
        "messages" => [
          { "role" => "system", "content" => system_text },
          { "role" => "user", "content" => user_text }
        ],
        "max_tokens" => max_tokens
      }
      message_text(api_call(payload, "xAI chat"))
    end

    def complete_vision(system_text, user_text, image_path, model: DEFAULT_MODEL,
                        max_tokens: 2048, effort: "")
      raise "no xAI credential configured" unless @credential

      raw = File.binread(image_path.to_s)
      b64 = Base64.strict_encode64(raw)
      payload = {
        "model" => resolve_model(model),
        "messages" => [
          { "role" => "system", "content" => system_text },
          { "role" => "user", "content" => [
            { "type" => "image_url",
              "image_url" => { "url" => "data:#{Zer0ImageGenerator.image_media_type(raw)};base64,#{b64}" } },
            { "type" => "text", "text" => user_text }
          ] }
        ],
        "max_tokens" => max_tokens
      }
      message_text(api_call(payload, "xAI chat (review)"))
    end

    private

    def resolve_model(model)
      name = model.to_s.strip
      return DEFAULT_MODEL if name.empty? || name.start_with?("claude")

      name
    end

    def api_call(payload, what)
      @credential = XAIAuth.ready_credential(@credential)
      url = "#{XAIAuth.base_url(@env)}/chat/completions"
      Http.with_retries(what) do
        @transport.json(url, payload, @credential.headers, timeout: 900)
      end
    end

    def message_text(data)
      choices = data["choices"] || []
      return "" if choices.empty?

      message = choices[0]["message"] || {}
      message["content"].to_s
    end
  end
end
