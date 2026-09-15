# frozen_string_literal: true

module Zer0Cms
  # A LinkedIn API client in stdlib Ruby: the versioned REST gateway, the
  # three-legged OAuth flow, posts, images, the pages a member administers and
  # the aggregate statistics for the author's own posts.
  #
  # Every call this module can make is declared in `LinkedIn::Plan` as data —
  # verb, host, path, the scopes it needs and a sentence saying what comes
  # back — and `Client#request` refuses anything that is not on that list
  # before a socket opens. The plan is also what `zer0-cms linkedin plan`
  # prints, so the surface can be read by a reviewer before a credential
  # exists. A test fails the build if a read in it returns anything but the
  # author's own content.
  #
  # Nothing here decides what to publish or whether it may be published. That
  # is `Zer0Cms::Distribution`, which composes this client with the draft
  # queue, the brand guard, the approval gate and the ledger.
  module LinkedIn
    REST_BASE = "https://api.linkedin.com/rest"
    API_HOST = "api.linkedin.com"
    OAUTH_HOST = "www.linkedin.com"
    RESTLI_PROTOCOL = "2.0.0"

    # `Linkedin-Version` (YYYYMM). LinkedIn publishes a version a month and
    # supports each for at least twelve months; there is no unversioned call.
    # 202608 is the newest version on 2026-09-14.
    DEFAULT_API_VERSION = "202608"
    VERSION_SUPPORT_MONTHS = 12
    VERSION_WARN_MONTHS = 10

    # The Posts API's limit on `commentary`, counted after little-text escaping.
    COMMENTARY_MAX = 3000

    URN = /\Aurn:li:(person|organization|organizationBrand|share|ugcPost|image):([A-Za-z0-9_-]+)\z/
    AUTHOR_TYPES = %w[person organization].freeze

    module_function

    # "organization" or "person" for an author URN, else nil.
    def author_type(urn)
      match = URN.match(urn.to_s)
      match && AUTHOR_TYPES.include?(match[1]) ? match[1] : nil
    end

    # :ok, :aging (within two months of the support window closing), :sunset
    # (past it — LinkedIn rejects the header), :future, or :invalid.
    def version_status(version, today: Date.today)
      match = /\A(\d{4})(\d{2})\z/.match(version.to_s)
      return :invalid unless match && (1..12).cover?(match[2].to_i)

      age = ((today.year * 12) + today.month) - ((match[1].to_i * 12) + match[2].to_i)
      return :future if age.negative?
      return :sunset if age >= VERSION_SUPPORT_MONTHS
      return :aging if age >= VERSION_WARN_MONTHS

      :ok
    end
  end
end

require "date"
require_relative "linkedin/errors"
require_relative "linkedin/restli"
require_relative "linkedin/little_text"
require_relative "linkedin/plan"
require_relative "linkedin/transport"
require_relative "linkedin/client"
require_relative "linkedin/oauth"
require_relative "linkedin/posts"
require_relative "linkedin/images"
require_relative "linkedin/organizations"
require_relative "linkedin/statistics"
