# frozen_string_literal: true

# The Rails app's only door to LinkedIn: it builds the stdlib distribution
# pipeline for a site, with the site's connected channel's token (or the
# environment's), and the OAuth flow with the app credentials from the
# environment. Controllers never construct a client themselves.
#
# `transport` is injectable so the integration tests run the real pipeline
# against a ScriptedTransport and never open a socket.
class LinkedinGateway
  class << self
    attr_writer :transport

    def transport
      @transport || Zer0Cms::LinkedIn::NetHttpTransport.new
    end

    # A channel's author overrides the site's configured one.
    def config(site, author: nil)
      env = ENV.to_h
      env["LINKEDIN_AUTHOR_URN"] = author if author.present?
      Zer0Cms::Distribution::Config.load(site.path, env: env)
    end

    def channel_for(site, config)
      site.channels.find_by(provider: "linkedin", author_urn: config.author.to_s)
    end

    def pipeline(site, channel: nil)
      config = config(site, author: channel&.author_urn)
      channel ||= channel_for(site, config)
      credentials = channel ? channel.credentials : config.credentials
      Zer0Cms::Distribution::Pipeline.new(config, transport: transport, credentials: credentials)
    end

    def oauth_ready?
      ENV["LINKEDIN_CLIENT_ID"].present? && ENV["LINKEDIN_CLIENT_SECRET"].present?
    end

    def oauth
      Zer0Cms::LinkedIn::OAuth.new(client_id: ENV["LINKEDIN_CLIENT_ID"], client_secret: ENV["LINKEDIN_CLIENT_SECRET"],
                                   transport: transport)
    end

    # LinkedIn only redirects to a URL registered on the app, so an operator
    # behind a proxy names it; otherwise it is this request's own origin.
    def redirect_uri(request)
      ENV["ZER0_CMS_LINKEDIN_REDIRECT_URI"].presence || "#{request.base_url}/oauth/linkedin/callback"
    end

    def scopes_for(channel)
      config = channel.site ? config(channel.site, author: channel.author_urn) : nil
      config&.scopes.presence || Zer0Cms::LinkedIn::OAuth.scopes_for(channel.author_type)
    end
  end
end
