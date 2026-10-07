# frozen_string_literal: true

require "json"
require "time"
require "uri"

require_relative "../http"

# xAI (Grok) credential resolution, shared by the XAIProvider.
#
# api.x.ai takes a plain `Authorization: Bearer <value>` for BOTH kinds of
# credential, so the only thing that varies between an OAuth access token and a
# console API key is where the value comes from and what we tell the human when
# it is rejected. This file owns that chain; the provider owns the request.
#
# Refresh, not login. The engine never MINTS a token — that takes an interactive
# login — but an expired token whose store also holds a refresh
# token and a client id (Kilo Code's login does) is refreshed at auth.x.ai once,
# right before a request needs it, and written back to that store so the login
# tool and the next run both see the rotated pair (lifehacker.dev's cover-art
# script already refreshes and saves the same way). Expired with nothing to
# refresh with, a token is treated as absent and the chain falls back to the
# API key.
module Zer0ImageGenerator
  # One resolved way to authenticate against api.x.ai.
  class XAICredential
    attr_reader :mode, :token, :source, :refresh_path

    # mode:   "oauth" | "api_key" — which rung of the chain this is.
    # source: human label for logs and fallback warnings.
    # refresh_path: set when the token has expired but its store can refresh
    #   it — the token is empty until XAIAuth.ready_credential refreshes it.
    def initialize(mode, token, source, refresh_path = nil)
      @mode = mode
      @token = token
      @source = source
      @refresh_path = refresh_path
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
      ".grok/auth.json", ".config/grok/auth.json", ".xai/auth.json",
      ".local/share/kilo/auth.json"
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

    # The refresh grant's endpoint, as auth.x.ai's OIDC discovery document
    # (/.well-known/openid-configuration) publishes it.
    TOKEN_ENDPOINT = "https://auth.x.ai/oauth2/token"
    REFRESH_TOKEN_KEYS = %w[refresh_token refresh].freeze
    EXPIRY_KEYS = %w[expires_at expiry expiration expires].freeze
    ISSUED_KEYS = %w[created_at obtained_at issued_at issued].freeze
    # Workers share one store: the first to find the token expired refreshes
    # it, the rest wait and read the result. A refresh token may rotate on use,
    # so two concurrent refreshes would leave one worker holding a dead token.
    REFRESH_LOCK = Mutex.new

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

      paths = DEFAULT_CREDENTIALS_FILES.map { |rel| File.join(home, rel) }
      kilo = env["KILO_AUTH_PATH"]
      paths.unshift(kilo) unless kilo.nil? || kilo.empty?
      paths
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
        if refresh_token(node) && client_id(node)
          return XAICredential.new("oauth", "",
                                   "Grok OAuth token (#{path}; expired, refreshed on use)",
                                   path)
        end
        debug("xAI OAuth: the token in #{path} has expired and holds nothing to " \
              "refresh it with; re-run your Grok login")
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

    # The credential ready to send: itself, or for an expired OAuth token its
    # store can refresh, the refreshed one. Raises RuntimeError on a failed refresh.
    def ready_credential(credential)
      return credential if credential.refresh_path.nil?

      refresh_file_credential(credential.refresh_path)
    end

    def refresh_file_credential(path)
      REFRESH_LOCK.synchronize do
        begin
          data = JSON.parse(File.read(path, encoding: "UTF-8"))
        rescue JSON::ParserError, SystemCallError, IOError => exc
          raise "xAI OAuth: cannot re-read #{path} (#{exc.message})"
        end
        node = data.is_a?(Hash) ? find_token_node(data) : nil
        raise "xAI OAuth: no access token left in #{path}" if node.nil?

        # Another worker may have refreshed the store while this one waited.
        current = token_node(data)
        if current && !expired?(current)
          return XAICredential.new("oauth", current["access_token"].to_s,
                                   "Grok OAuth token (#{path})")
        end
        refresh = refresh_token(node)
        cid = client_id(node)
        raise "xAI OAuth: the token in #{path} cannot be refreshed" if refresh.nil? || cid.nil?

        fresh = request_refresh(refresh, cid)
        store_refreshed(node, fresh, Time.now.to_f)
        begin
          write_store(path, data)
        rescue SystemCallError, IOError => exc
          # The refresh token may already have rotated, so say so loudly — but
          # this run still holds a working access token.
          warn_log("xAI OAuth: refreshed, but could not save the new token to #{path} " \
                   "(#{exc.message}); the login tool may need a fresh sign-in")
        end
        debug("xAI OAuth: refreshed the token in #{path}")
        XAICredential.new("oauth", fresh["access_token"].to_s,
                          "Grok OAuth token (#{path}; refreshed)")
      end
    end

    # POST the refresh grant. Never retried: a refresh token that rotated on a
    # request whose response was lost is already spent.
    def request_refresh(refresh_token, client_id)
      body = URI.encode_www_form("grant_type" => "refresh_token",
                                 "refresh_token" => refresh_token,
                                 "client_id" => client_id)
      headers = { "Content-Type" => "application/x-www-form-urlencoded",
                  "Accept" => "application/json" }
      begin
        _, _, raw = Http.request(TOKEN_ENDPOINT, method: "POST", headers: headers,
                                                 data: body, timeout: 60)
      rescue HttpStatusError => exc
        # The OAuth error code (invalid_grant, invalid_client) is safe to show
        # and says whether a re-login is due; the description may echo input.
        details = exc.json
        code = details.is_a?(Hash) ? details["error"] : nil
        reason = token_string?(code) ? "HTTP #{exc.status}: #{code}" : "HTTP #{exc.status}"
        raise "xAI OAuth refresh failed (#{reason})"
      end
      begin
        data = JSON.parse(raw.to_s.dup.force_encoding("UTF-8"))
      rescue JSON::ParserError, EncodingError
        raise "xAI OAuth refresh returned non-JSON"
      end
      unless data.is_a?(Hash) && token_string?(data["access_token"])
        raise "xAI OAuth refresh returned no access_token"
      end

      data
    end

    # Write the refreshed pair into the store's own node, in its own key names
    # and time units, so the tool that owns the file still reads it.
    def store_refreshed(node, fresh, now)
      token_key = token_string?(node["access_token"]) ? "access_token" : "access"
      node[token_key] = fresh["access_token"]
      if token_string?(fresh["refresh_token"])
        refresh_key = REFRESH_TOKEN_KEYS.find { |key| token_string?(node[key]) } || "refresh_token"
        node[refresh_key] = fresh["refresh_token"]
      end
      lifetime = number(fresh["expires_in"])
      lifetime = 3600.0 if lifetime.nil? || lifetime.zero?
      EXPIRY_KEYS.each do |key|
        next if epoch_seconds(node[key]).nil?

        node[key] = timestamp_like(node[key], now + lifetime)
        return
      end
      return if number(node["expires_in"]).nil?

      node["expires_in"] = lifetime.to_i
      ISSUED_KEYS.each do |key|
        next if epoch_seconds(node[key]).nil?

        node[key] = timestamp_like(node[key], now)
        return
      end
    end

    # `seconds` in the shape `previous` used: epoch ms, epoch s, or ISO-8601.
    def timestamp_like(previous, seconds)
      value = number(previous)
      unless value.nil?
        stamp = value > 1e11 ? (seconds * 1000).to_i : seconds.to_i
        return previous.is_a?(String) ? stamp.to_s : stamp
      end
      Time.at(seconds.to_i).utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    end

    # Replace the store atomically, keeping its permissions (it holds secrets).
    def write_store(path, data)
      target = File.realpath(path)
      mode = File.stat(target).mode & 0o777
      tmp = File.join(File.dirname(target), ".#{File.basename(target)}.#{Process.pid}.tmp")
      begin
        # Created owner-only: the token must never sit world-readable, even briefly.
        File.open(tmp, File::WRONLY | File::CREAT | File::TRUNC, 0o600) do |handle|
          handle.write("#{JSON.pretty_generate(data)}\n")
        end
        File.chmod(mode, tmp)
        File.rename(tmp, target)
      ensure
        File.delete(tmp) if File.exist?(tmp)
      end
    end

    def refresh_token(node)
      REFRESH_TOKEN_KEYS.each { |key| return node[key] if token_string?(node[key]) }
      nil
    end

    # The OAuth client the token was issued to: the store's own record, else
    # the access token's JWT claims (client_id, then a string or first aud).
    def client_id(node)
      return node["client_id"] if token_string?(node["client_id"])

      access = token_string?(node["access_token"]) ? node["access_token"] : node["access"]
      claims = jwt_claims(access)
      return claims["client_id"] if token_string?(claims["client_id"])

      aud = claims["aud"]
      aud = aud.find { |entry| token_string?(entry) } if aud.is_a?(Array)
      token_string?(aud) ? aud : nil
    end

    def jwt_claims(token)
      parts = token.is_a?(String) ? token.split(".") : []
      return {} if parts.length < 2

      claims = JSON.parse(parts[1].tr("-_", "+/").unpack1("m").force_encoding("UTF-8"))
      claims.is_a?(Hash) ? claims : {}
    rescue JSON::ParserError, ArgumentError, EncodingError
      {}
    end

    # The hash actually holding `access_token`: the document itself, or one of
    # the containers a login tool nests it under.
    def token_node(data)
      node = find_token_node(data)
      return nil if node.nil?
      return node if token_string?(node["access_token"])

      node.merge("access_token" => node["access"])
    end

    def find_token_node(data)
      return data if token_string?(data["access_token"]) || token_string?(data["access"])

      NESTED_KEYS.each do |key|
        nested = data[key]
        next unless nested.is_a?(Hash)
        return nested if token_string?(nested["access_token"]) || token_string?(nested["access"])
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

    # Aspect ratios the Imagine models take. grok-imagine renders a square
    # unless told otherwise, which a wide banner then crops; grok-2-image
    # predates the parameter, so it is sent nothing.
    IMAGINE_PREFIX = "grok-imagine"
    ASPECT_RATIOS = [
      ["1:1", 1.0], ["3:2", 1.5], ["2:3", 2.0 / 3], ["4:3", 4.0 / 3],
      ["3:4", 0.75], ["16:9", 16.0 / 9], ["9:16", 9.0 / 16]
    ].freeze

    # The Imagine aspect ratio nearest the configured WIDTHxHEIGHT size, or nil
    # for a non-Imagine model or a size with no dimensions (e.g. `auto`).
    def aspect_ratio(model, size)
      return nil unless (model || "").to_s.strip.downcase.start_with?(IMAGINE_PREFIX)

      match = /\A\s*(\d+)\s*[xX]\s*(\d+)\s*\z/.match(size.to_s)
      return nil if match.nil? || match[1].to_i.zero? || match[2].to_i.zero?

      wanted = Math.log(match[1].to_f / match[2].to_i)
      ASPECT_RATIOS.min_by { |(_label, ratio)| (Math.log(ratio) - wanted).abs }[0]
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

    def warn_log(message)
      Logging.warn(message) if defined?(Logging)
    end
  end
end
