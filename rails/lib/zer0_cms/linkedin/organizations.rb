# frozen_string_literal: true

module Zer0Cms
  module LinkedIn
    # The pages the authenticated member may post to, and their names.
    #
    # Page roles are verified through LinkedIn rather than asserted by
    # configuration: a channel names a page, and `administered` is how the CMS
    # shows whether the connected member actually holds a posting role on it.
    #
    # A 403 returns nil, not []. "This token may not read page roles" and "this
    # member administers no pages" are different answers, and a screen that
    # rendered both as an empty list would be lying about one of them.
    module Organizations
      POSTING_ROLES = %w[ADMINISTRATOR CONTENT_ADMINISTRATOR DIRECT_SPONSORED_CONTENT_POSTER].freeze

      Page = Struct.new(:urn, :role, :name, keyword_init: true)

      module_function

      def administered(client, count: 100)
        data = client.json(:organization_acls, query: [["q", "roleAssignee"], ["state", "APPROVED"],
                                                       ["count", count.to_i.clamp(1, 100)]])
        pages = Array(data["elements"]).filter_map do |element|
          urn = element["organization"] || element["organizationTarget"]
          next unless LinkedIn.author_type(urn) == "organization" && POSTING_ROLES.include?(element["role"])

          Page.new(urn: urn, role: element["role"])
        end
        pages.group_by(&:urn).map { |_, same| same.min_by { |page| POSTING_ROLES.index(page.role) } }
      rescue HTTPError => e
        raise unless e.forbidden?

        nil
      end

      def name(client, urn)
        raise ArgumentError, "not an organization URN: #{urn.inspect}" unless LinkedIn.author_type(urn) == "organization"

        client.json(:organization, path: { id: urn.to_s.split(":").last })["localizedName"]
      rescue HTTPError => e
        raise unless e.forbidden? || e.not_found?

        nil
      end

      # Does the member hold a posting role on `urn`? nil when unknowable.
      def can_post?(client, urn)
        pages = administered(client)
        pages && pages.any? { |page| page.urn == urn }
      end
    end
  end
end
