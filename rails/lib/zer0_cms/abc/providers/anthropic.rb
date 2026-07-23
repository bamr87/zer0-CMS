# frozen_string_literal: true

require_relative "../content_provider"
require "json"
require "net/http"
require "uri"

module Zer0Cms
  module Abc
    module Providers
      # LLM content provider: asks Claude to invent an A–Z alphabet for an
      # arbitrary theme when no bundled lexicon exists. Stdlib-only (net/http),
      # so the engine keeps its no-gem-dependencies contract.
      #
      # Auth mirrors the fleet's other Claude callers: ANTHROPIC_API_KEY on the
      # x-api-key header, or a Claude Code OAuth token (CLAUDE_CODE_OAUTH_TOKEN /
      # ANTHROPIC_AUTH_TOKEN) on Authorization: Bearer with the oauth beta header
      # and the required "You are Claude Code" first system block.
      class Anthropic < ContentProvider
        API_URL       = "https://api.anthropic.com/v1/messages"
        API_VERSION   = "2023-06-01"
        OAUTH_BETA    = "oauth-2025-04-20"
        DEFAULT_MODEL = "claude-opus-4-8"
        CLAUDE_CODE_SYSTEM = "You are Claude Code, Anthropic's official CLI for Claude."

        class ProviderError < StandardError; end

        def initialize(model: DEFAULT_MODEL, api_key: nil, oauth_token: nil, http: nil)
          @model = model
          @api_key = api_key || ENV["ANTHROPIC_API_KEY"]
          @oauth_token = oauth_token ||
                         ENV["CLAUDE_CODE_OAUTH_TOKEN"] || ENV["ANTHROPIC_AUTH_TOKEN"]
          @http = http # inject a fake in tests
        end

        # Any theme is supported as long as a credential is configured.
        def supports?(_theme)
          configured?
        end

        def configured?
          !(@api_key.to_s.empty? && @oauth_token.to_s.empty?)
        end

        def plan(theme:, audience: "toddler")
          unless configured?
            raise ProviderError, "Anthropic provider needs ANTHROPIC_API_KEY or " \
                                 "CLAUDE_CODE_OAUTH_TOKEN (or use the deterministic provider)"
          end

          body = request_body(theme, audience)
          raw = post(body)
          plan = extract_plan(raw)
          validate_plan!(plan)
        end

        private

        def request_body(theme, audience)
          {
            model: @model,
            max_tokens: 4096,
            system: system_blocks,
            messages: [{ role: "user", content: user_prompt(theme, audience) }],
            output_config: { format: { type: "json_schema", schema: plan_schema } }
          }
        end

        # OAuth tokens require the first system block to identify as Claude Code.
        def system_blocks
          base = "You write gentle, wholesome content for a children's ABC picture book. " \
                 "Every word is text-free and safe for toddlers."
          if using_oauth?
            [{ type: "text", text: CLAUDE_CODE_SYSTEM }, { type: "text", text: base }]
          else
            base
          end
        end

        def user_prompt(theme, audience)
          <<~PROMPT
            Design a #{audience} ABC book on the theme "#{theme}".
            For every letter A through Z, choose:
              - "word": a real concept from the theme starting with that letter
              - "subject": a concrete, drawable little scene for the word (no text in it)
              - "tagline": one warm read-aloud line, e.g. "A is for Automation — little helpers that do the work!"
              - "alt": a short accessible description of the intended illustration
            Also give the book a "title" and a "subtitle" of the form "A is for <the A word>".
            Keep every word gentle and never scary. Return all 26 letters.
          PROMPT
        end

        def plan_schema
          {
            type: "object",
            additionalProperties: false,
            required: %w[title subtitle letters],
            properties: {
              title: { type: "string" },
              subtitle: { type: "string" },
              letters: {
                type: "object",
                additionalProperties: false,
                required: ContentProvider::LETTERS,
                properties: ContentProvider::LETTERS.each_with_object({}) do |l, acc|
                  acc[l] = {
                    type: "object",
                    additionalProperties: false,
                    required: %w[word subject tagline alt],
                    properties: {
                      word: { type: "string" }, subject: { type: "string" },
                      tagline: { type: "string" }, alt: { type: "string" }
                    }
                  }
                end
              }
            }
          }
        end

        def extract_plan(raw)
          data = JSON.parse(raw)
          if data["stop_reason"] == "refusal"
            raise ProviderError, "Claude refused the request; pick a different theme"
          end

          text = Array(data["content"]).find { |b| b["type"] == "text" }&.fetch("text", nil)
          raise ProviderError, "no text block in Claude response" if text.nil?

          parsed = JSON.parse(text)
          parsed.merge(
            "default_art_style" => nil, # the wizard applies the caller's chosen style
            "default_palette" => nil
          )
        rescue JSON::ParserError => e
          raise ProviderError, "could not parse Claude response: #{e.message}"
        end

        def using_oauth?
          @api_key.to_s.empty? && !@oauth_token.to_s.empty?
        end

        def post(body)
          return @http.call(body) if @http # test seam

          uri = URI(API_URL)
          req = Net::HTTP::Post.new(uri)
          req["content-type"] = "application/json"
          req["anthropic-version"] = API_VERSION
          if using_oauth?
            req["authorization"] = "Bearer #{@oauth_token}"
            req["anthropic-beta"] = OAUTH_BETA
          else
            req["x-api-key"] = @api_key
          end
          req.body = JSON.generate(body)

          res = Net::HTTP.start(uri.host, uri.port, use_ssl: true, read_timeout: 120) do |http|
            http.request(req)
          end
          unless res.is_a?(Net::HTTPSuccess)
            raise ProviderError, "Anthropic API error #{res.code}: #{res.body.to_s[0, 300]}"
          end

          res.body
        end
      end

      ContentProvider.register(:anthropic, Anthropic)
    end
  end
end
