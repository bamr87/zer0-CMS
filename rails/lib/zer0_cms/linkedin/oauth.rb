# frozen_string_literal: true

require "openssl"
require "securerandom"
require "uri"

module Zer0Cms
  module LinkedIn
    # LinkedIn's three-legged OAuth: the consent URL, the code exchange, the
    # refresh grant and token introspection.
    #
    # Each account is authorized by its own owner — a member consents for
    # their own profile, a page administrator for the pages they administer —
    # and nothing here can mint a token for anyone who did not. The client
    # secret travels only in a form body to www.linkedin.com, never in a URL,
    # and never in an error message.
    #
    # LinkedIn issues access tokens for 60 days. Refresh tokens (365 days) are
    # issued only to apps LinkedIn has enabled for programmatic refresh; an app
    # without them re-runs consent, which LinkedIn skips while the member is
    # signed in and the previous token has not expired.
    class OAuth
      AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
      STATE_TTL = 600

      # The least each author kind needs: publish, read the author's own posts
      # back, and read their aggregate statistics.
      DEFAULT_SCOPES = {
        "organization" => %w[w_organization_social r_organization_social rw_organization_admin],
        "person" => %w[openid profile w_member_social r_member_postAnalytics]
      }.freeze

      Token = Struct.new(:access_token, :expires_at, :refresh_token, :refresh_expires_at, :scopes, keyword_init: true) do
        def days_left(now = Time.now)
          expires_at && ((expires_at - now) / 86_400).ceil
        end
      end

      Introspection = Struct.new(:active, :status, :scopes, :expires_at, :created_at, :authorized_at, :auth_type,
                                 keyword_init: true) do
        def days_left(now = Time.now)
          expires_at && ((expires_at - now) / 86_400).ceil
        end
      end

      def self.new_state
        SecureRandom.urlsafe_base64(32)
      end

      def self.state_matches?(expected, given)
        a = expected.to_s
        b = given.to_s
        return false if a.empty? || a.bytesize != b.bytesize

        OpenSSL.fixed_length_secure_compare(a, b)
      end

      def self.scopes_for(author_type)
        DEFAULT_SCOPES.fetch(author_type.to_s) { DEFAULT_SCOPES["organization"] }
      end

      # The member behind a token that carries `openid profile`.
      def self.member(client)
        data = client.json(:userinfo)
        sub = data["sub"].to_s
        raise Error, "userinfo returned no member id" if sub.empty?

        { "urn" => "urn:li:person:#{sub}", "name" => data["name"].to_s }
      end

      attr_reader :client_id

      def initialize(client_id:, client_secret:, transport: NetHttpTransport.new, sleeper: ->(seconds) { sleep(seconds) })
        @client_id = client_id.to_s
        @client_secret = client_secret.to_s
        if @client_id.empty? || @client_secret.empty?
          raise ArgumentError, "LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET are both required for OAuth"
        end

        @client = Client.new(transport: transport, sleeper: sleeper, secrets: [@client_secret])
      end

      def authorize_url(redirect_uri:, state:, scopes:)
        check_redirect!(redirect_uri)
        raise ArgumentError, "state is required" if state.to_s.empty?
        raise ArgumentError, "at least one scope is required" if Array(scopes).empty?

        query = [["response_type", "code"], ["client_id", @client_id], ["redirect_uri", redirect_uri],
                 ["state", state], ["scope", Array(scopes).join(" ")]]
        "#{AUTHORIZE_URL}?#{Restli.query(query)}"
      end

      def exchange(code:, redirect_uri:, now: Time.now)
        raise ArgumentError, "authorization code is empty" if code.to_s.empty?

        token_from(post_token("grant_type" => "authorization_code", "code" => code.to_s,
                              "redirect_uri" => redirect_uri.to_s), now)
      end

      def refresh(refresh_token:, now: Time.now)
        raise ArgumentError, "refresh token is empty" if refresh_token.to_s.empty?

        token_from(post_token("grant_type" => "refresh_token", "refresh_token" => refresh_token.to_s), now)
      end

      # Needs no scope and no bearer: the app's own credentials in the body.
      def introspect(token)
        data = @client.json(:introspect, auth: false,
                                         form: { "client_id" => @client_id, "client_secret" => @client_secret,
                                                 "token" => token.to_s })
        Introspection.new(
          active: data["active"] == true,
          status: data["status"].to_s,
          scopes: data["scope"].to_s.split(/[\s,]+/).reject(&:empty?),
          expires_at: epoch(data["expires_at"]),
          created_at: epoch(data["created_at"]),
          authorized_at: epoch(data["authorized_at"]),
          auth_type: data["auth_type"].to_s
        )
      end

      private

      def post_token(fields)
        @client.json(:token, auth: false, form: fields.merge("client_id" => @client_id, "client_secret" => @client_secret))
      end

      def token_from(data, now)
        access = data["access_token"].to_s
        raise Error, "LinkedIn returned no access_token" if access.empty?

        Token.new(
          access_token: access,
          expires_at: data["expires_in"] ? now + data["expires_in"].to_i : nil,
          refresh_token: data["refresh_token"].to_s.empty? ? nil : data["refresh_token"].to_s,
          refresh_expires_at: data["refresh_token_expires_in"] ? now + data["refresh_token_expires_in"].to_i : nil,
          scopes: data["scope"].to_s.split(/[\s,]+/).reject(&:empty?)
        )
      end

      def epoch(value)
        value.nil? ? nil : Time.at(value.to_i).utc
      end

      def check_redirect!(uri)
        parsed = URI.parse(uri.to_s)
        valid = parsed.is_a?(URI::HTTP) && !parsed.host.to_s.empty? && parsed.fragment.nil?
        raise ArgumentError, "redirect_uri must be an absolute http(s) URL without a fragment" unless valid
      rescue URI::InvalidURIError
        raise ArgumentError, "redirect_uri is not a valid URL"
      end
    end
  end
end
