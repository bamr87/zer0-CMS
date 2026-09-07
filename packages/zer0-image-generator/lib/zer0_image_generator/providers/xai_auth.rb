# frozen_string_literal: true

require "json"
require "time"

# xAI (Grok) credential resolution, shared by the XAIProvider.
#
# api.x.ai takes a plain `Authorization: Bearer <value>` for BOTH kinds of
# credential, so the only thing that varies between an OAuth access token and a
# console API key is where the value comes from and what we tell the human when
# it is rejected. This file owns that chain; the provider owns the request.
#
# Deliberately NOT implemented here: minting or refreshing an OAuth token. xAI
# does not publish its device-code/PKCE endpoints or a public client id, and the
# credentials file belongs to whichever login tool wrote it — inventing a token
# endpoint, or writing back into another tool's store, would be guesswork. The
# engine CONSUMES a token that a Grok login already produced, treats an expired
# one as absent, and falls back to the API key.
module Zer0ImageGenerator
  # One resolved way to authenticate against api.x.ai.
  class XAICredential
    attr_reader :mode, :token, :source

    # mode:   "oauth" | "api_key" — which rung of the chain this is.
    # source: human label for logs and fallback warnings.
    def initialize(mode, token, source)
      @mode = mode
      @token = token
      @source = source
    end

    def headers
      { "Authorization" => "Bearer #{@token}" }
    end
  end

  module XAIAuth
    API_BASE = "https://api.x.ai/v1"

    # OAuth access token, straight from the environment. XAI_ first (it matches
    # the vendor's own XAI_* naming), GROK_ accepted because that is what the
    # consumer-facing login is called.
    OAUTH_TOKEN_ENV = %w[XAI_OAUTH_TOKEN GROK_OAUTH_TOKEN].freeze

    # Explicit path to a credentials file written by a Grok OAuth login.
    CREDENTIALS_FILE_ENV = %w[XAI_OAUTH_CREDENTIALS GROK_OAUTH_CREDENTIALS].freeze

    API_KEY_ENV = "XAI_API_KEY"

    # Where a Grok login drops its token when no path is configured. Relative to
    # the home directory so a test (and a container) can point HOME elsewhere.
    DEFAULT_CREDENTIALS_FILES = [
      ".grok/auth.json", ".config/grok/auth.json", ".xai/auth.json"
    ].freeze

    # Credential files nest the token differently per tool; look at the top
    # level first, then inside the usual containers.
    NESTED_KEYS = %w[xai grok oauth tokens credentials].freeze

    # Treat a token that expires within the minute as already gone — a run can
    # easily outlive that, and the API key fallback is cheaper than a mid-run
    # 401 on every remaining page.
    EXPIRY_LEEWAY = 60.0

    # Which rung(s) to try, as an env knob. `auto` (the default) is OAuth first
    # with the API key as the fallback; the other two pin one rung.
    AUTH_MODE_ENV = "XAI_AUTH"
    AUTH_MODES = %w[auto oauth api_key].freeze

    MISSING_HINT =
      "The xAI provider needs a Grok OAuth token or an xAI API key — any ONE of:\n" \
      "  1. XAI_OAUTH_TOKEN (or GROK_OAUTH_TOKEN) — an OAuth access token from a\n" \
      "     Grok login (SuperGrok / X Premium+)\n" \
      "  2. a Grok OAuth credentials file — ~/.grok/auth.json by default, or the\n" \
      "     path in XAI_OAUTH_CREDENTIALS / GROK_OAUTH_CREDENTIALS\n" \
      "  3. XAI_API_KEY — a key from console.x.ai (also the automatic fallback\n" \
      "     when an OAuth token is expired or rejected)\n" \
      "Pin one rung with XAI_AUTH=oauth|api_key; the default tries OAuth first."

    module_function

    # The credentials to try, best rung first. An empty list means the provider
    # is unconfigured.
    def chain(env)
      mode = auth_mode(env)
      credentials = []
      credentials.concat(oauth_credentials(env)) unless mode == "api_key"
      credentials << api_key_credential(env) unless mode == "oauth"
      credentials.compact
    end

    # One-line summary of how this run will authenticate (nil when it cannot).
    def describe(env)
      credentials = chain(env)
      return nil if credentials.empty?

      primary = credentials[0].source
      fallback = credentials[1]
      fallback ? "#{primary}, falling back to #{fallback.source}" : primary
    end

    # Base for the images endpoint. XAI_BASE_URL is xAI's own override and is
    # honored here so an OAuth surface on a different host stays reachable.
    def base_url(env)
      configured = env["XAI_BASE_URL"]
      return API_BASE if configured.nil? || configured.empty?

      configured.chomp("/")
    end

    def auth_mode(env)
      raw = (env[AUTH_MODE_ENV] || "").strip.downcase
      return "auto" if raw.empty?
      return raw if AUTH_MODES.include?(raw)

      debug("#{AUTH_MODE_ENV}=#{raw} is not one of #{AUTH_MODES.join('|')}; using auto")
      "auto"
    end

    def oauth_credentials(env)
      OAUTH_TOKEN_ENV.each do |name|
        value = env[name]
        next if value.nil? || value.empty?

        return [XAICredential.new("oauth", value, "#{name} (Grok OAuth token)")]
      end
      credential_files(env).each do |path|
        credential = file_credential(path)
        return [credential] if credential
      end
      []
    end

    def api_key_credential(env)
      value = env[API_KEY_ENV]
      return nil if value.nil? || value.empty?

      XAICredential.new("api_key", value, "#{API_KEY_ENV} (xAI API key)")
    end

    # Candidate credential-file paths: an explicit override wins outright, so a
    # configured-but-missing path never silently reads someone else's token.
    def credential_files(env)
      CREDENTIALS_FILE_ENV.each do |name|
        value = env[name]
        return [value] unless value.nil? || value.empty?
      end
      home = home_dir(env)
      return [] if home.nil? || home.empty?

      DEFAULT_CREDENTIALS_FILES.map { |rel| File.join(home, rel) }
    end

    # The env snapshot is the source of truth (tests and containers set HOME);
    # Dir.home is only the last resort.
    def home_dir(env)
      %w[HOME USERPROFILE].each do |name|
        value = env[name]
        return value unless value.nil? || value.empty?
      end
      begin
        Dir.home
      rescue ArgumentError, SystemCallError
        # No resolvable home (empty env in a container) — no default file to read.
        nil
      end
    end

    # Read one credentials file. Anything unreadable, unparseable, tokenless or
    # expired is "no credential here" — the chain moves on to the next rung.
    def file_credential(path)
      return nil unless File.file?(path)

      data = JSON.parse(File.read(path, encoding: "UTF-8"))
      unless data.is_a?(Hash)
        debug("xAI OAuth: #{path} is not a JSON object; ignoring")
        return nil
      end
      node = token_node(data)
      if node.nil?
        debug("xAI OAuth: no access_token in #{path}; ignoring")
        return nil
      end
      if expired?(node)
        debug("xAI OAuth: the token in #{path} has expired; re-run your Grok login")
        return nil
      end

      XAICredential.new("oauth", node["access_token"].to_s,
                        "Grok OAuth token (#{path})")
    rescue JSON::ParserError => exc
      debug("xAI OAuth: #{path} is not valid JSON (#{exc.message}); ignoring")
      nil
    rescue SystemCallError, IOError => exc
      debug("xAI OAuth: cannot read #{path} (#{exc.message}); ignoring")
      nil
    end

    # The hash actually holding `access_token`: the document itself, or one of
    # the containers a login tool nests it under.
    def token_node(data)
      return data if token_string?(data["access_token"])

      NESTED_KEYS.each do |key|
        nested = data[key]
        return nested if nested.is_a?(Hash) && token_string?(nested["access_token"])
      end
      nil
    end

    def token_string?(value)
      value.is_a?(String) && !value.empty?
    end

    def expired?(node, now = Time.now.to_f)
      expires_at = absolute_expiry(node)
      return false if expires_at.nil?

      expires_at <= now + EXPIRY_LEEWAY
    end

    # Absolute expiry in epoch seconds, or nil when the file records none.
    def absolute_expiry(node)
      %w[expires_at expiry expiration expires].each do |key|
        value = epoch_seconds(node[key])
        return value unless value.nil?
      end
      # `expires_in` is relative and only means something next to an issue time.
      lifetime = number(node["expires_in"])
      return nil if lifetime.nil?

      %w[created_at obtained_at issued_at issued].each do |key|
        issued = epoch_seconds(node[key])
        return issued + lifetime unless issued.nil?
      end
      nil
    end

    # Accepts epoch seconds, epoch milliseconds, or an ISO-8601 timestamp.
    def epoch_seconds(raw)
      value = number(raw)
      # 1e11 seconds is the year 5138; anything past it is milliseconds.
      return value > 1e11 ? value / 1000.0 : value unless value.nil?
      return nil unless raw.is_a?(String) && !raw.empty?

      begin
        Time.iso8601(raw).to_f
      rescue ArgumentError
        nil
      end
    end

    def number(raw)
      return raw.to_f if raw.is_a?(Numeric)
      return nil unless raw.is_a?(String) && !raw.empty?

      begin
        Float(raw)
      rescue ArgumentError, TypeError
        nil
      end
    end

    # Logging is a sibling slice resolved at call time (see providers/base.rb);
    # never let a diagnostic take down credential resolution.
    def debug(message)
      Logging.debug(message) if defined?(Logging)
    end
  end
end
