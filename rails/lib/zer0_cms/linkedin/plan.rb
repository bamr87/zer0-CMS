# frozen_string_literal: true

module Zer0Cms
  module LinkedIn
    # Every call the LinkedIn client can make, declared before it is made.
    #
    # `Client#request` takes a call id, never a URL, so a request that is not
    # on this list cannot be expressed; the one caller-supplied URL (an image
    # upload slot LinkedIn hands back) is checked against `UPLOAD_HOST`.
    #
    # Two assertions keep the list honest, and both are tests:
    #
    # * `own_content_only?` — every entry's `returns` sentence contains the
    #   word "own". It reads like a weak check until you consider what it
    #   defends against: somebody adding a connections, followers or feed call
    #   without noticing that it changes what the product is. Writing the
    #   sentence forces that author to describe the data, and a sentence that
    #   cannot honestly contain "own" fails.
    # * `forbidden_path?` — no declared path reaches member graphs, messaging,
    #   per-member engagement (who liked, who commented) or search.
    #
    # Scopes are "any of": a call is refused locally only when the token's
    # granted scopes are known (from introspection) and hold none of them.
    module Plan
      Call = Struct.new(:id, :verb, :host, :path, :scopes, :write, :method_header, :purpose, :returns,
                        keyword_init: true) do
        def rest?
          host == API_HOST && path.start_with?("/rest/")
        end

        def oauth?
          host == OAUTH_HOST
        end

        def to_h
          { "id" => id.to_s, "verb" => verb, "host" => host, "path" => path, "scopes" => scopes,
            "write" => write, "purpose" => purpose, "returns" => returns }
        end
      end

      ORG_READ = %w[r_organization_social rw_organization_admin].freeze
      MEMBER_READ = %w[r_member_social].freeze
      ORG_ADMIN = %w[r_organization_admin rw_organization_admin].freeze
      WRITE_SOCIAL = %w[w_organization_social w_member_social].freeze

      CALLS = [
        Call.new(id: :token, verb: "POST", host: OAUTH_HOST, path: "/oauth/v2/accessToken", scopes: [], write: false,
                 purpose: "exchange an authorization code, or a refresh token, for an access token",
                 returns: "this app's own access token for the member who consented"),
        Call.new(id: :introspect, verb: "POST", host: OAUTH_HOST, path: "/oauth/v2/introspectToken", scopes: [], write: false,
                 purpose: "check whether a token is active, when it expires and what it may do",
                 returns: "the status, expiry and scopes of this app's own token"),
        Call.new(id: :userinfo, verb: "GET", host: API_HOST, path: "/v2/userinfo", scopes: %w[openid profile], write: false,
                 purpose: "learn which member authorized the app, to name their own person URN",
                 returns: "the authenticated member's own id and name"),
        Call.new(id: :organization_acls, verb: "GET", host: API_HOST, path: "/rest/organizationAcls", scopes: ORG_ADMIN,
                 write: false, method_header: "FINDER",
                 purpose: "list the pages the member may post to",
                 returns: "the authenticated member's own page roles"),
        Call.new(id: :organization, verb: "GET", host: API_HOST, path: "/rest/organizations/{id}", scopes: ORG_ADMIN,
                 write: false,
                 purpose: "show a page's name next to its URN",
                 returns: "the own public name of a page the member administers"),
        Call.new(id: :posts_create, verb: "POST", host: API_HOST, path: "/rest/posts", scopes: WRITE_SOCIAL, write: true,
                 purpose: "publish an approved draft as its author",
                 returns: "the id of the author's own new post"),
        Call.new(id: :posts_get, verb: "GET", host: API_HOST, path: "/rest/posts/{urn}", scopes: ORG_READ + MEMBER_READ,
                 write: false,
                 purpose: "confirm a post published",
                 returns: "the author's own post, as published"),
        Call.new(id: :posts_by_author, verb: "GET", host: API_HOST, path: "/rest/posts", scopes: ORG_READ + MEMBER_READ,
                 write: false, method_header: "FINDER",
                 purpose: "list what the configured author already published",
                 returns: "the configured author's own recent posts"),
        Call.new(id: :posts_delete, verb: "DELETE", host: API_HOST, path: "/rest/posts/{urn}", scopes: WRITE_SOCIAL,
                 write: true, method_header: "DELETE",
                 purpose: "withdraw a post the author published",
                 returns: "nothing; it removes the author's own post"),
        Call.new(id: :images_initialize, verb: "POST", host: API_HOST, path: "/rest/images", scopes: WRITE_SOCIAL,
                 write: true,
                 purpose: "reserve an upload for a link card's thumbnail",
                 returns: "an upload slot for the author's own image"),
        Call.new(id: :images_upload, verb: "PUT", host: :upload, path: "{uploadUrl}", scopes: WRITE_SOCIAL, write: true,
                 purpose: "send the thumbnail's bytes to the slot LinkedIn returned",
                 returns: "nothing; it stores the author's own image"),
        Call.new(id: :images_get, verb: "GET", host: API_HOST, path: "/rest/images/{urn}", scopes: %w[w_organization_social],
                 write: false,
                 purpose: "wait for an uploaded thumbnail to finish processing",
                 returns: "the processing status of the author's own image"),
        Call.new(id: :organization_share_statistics, verb: "GET", host: API_HOST,
                 path: "/rest/organizationalEntityShareStatistics", scopes: ORG_ADMIN, write: false, method_header: "FINDER",
                 purpose: "read how the page's published posts performed",
                 returns: "aggregate counts for the page's own posts"),
        Call.new(id: :member_post_statistics, verb: "GET", host: API_HOST, path: "/rest/memberCreatorPostAnalytics",
                 scopes: %w[r_member_postAnalytics], write: false, method_header: "FINDER",
                 purpose: "read how a member's published post performed",
                 returns: "aggregate counts for the member's own post")
      ].freeze

      BY_ID = CALLS.to_h { |call| [call.id, call] }.freeze

      # LinkedIn's upload slots are signed URLs on linkedin.com.
      UPLOAD_HOST = /\A(?:[a-z0-9-]+\.)*linkedin\.com\z/

      FORBIDDEN = %r{
        connections|/people|networkSizes|follower|memberFollowers|messages|conversations|
        socialActions|/likes|/reactions|/comments|search|/me\b|profile
      }xi

      module_function

      def fetch(id)
        BY_ID.fetch(id.to_sym) { raise Refused, "#{id} is not a declared LinkedIn call" }
      end

      def own_content_only?(calls = CALLS)
        calls.all? { |call| call.returns.match?(/\bown\b/) }
      end

      def forbidden_path?(path)
        FORBIDDEN.match?(path.to_s)
      end

      def reads
        CALLS.reject(&:write)
      end

      def writes
        CALLS.select(&:write)
      end

      # The surface as text, for a terminal, a job summary or an application form.
      def describe
        lines = ["LinkedIn calls this CMS can make, and nothing else:", ""]
        CALLS.each do |call|
          host = call.host == :upload ? "<upload slot on linkedin.com>" : call.host
          lines << "  #{call.verb.ljust(6)} #{host}#{call.host == :upload ? "" : call.path}#{call.write ? "   [write]" : ""}"
          lines << "    to        #{call.purpose}"
          lines << "    scopes    #{call.scopes.empty? ? "(app credentials)" : call.scopes.join(" | ")}"
          lines << "    returns   #{call.returns}"
          lines << ""
        end
        lines << "No member profiles, connections, followers, feeds or messages. No record of who"
        lines << "engaged with a post — aggregate counts only, for the author's own posts."
        lines.join("\n")
      end
    end
  end
end
