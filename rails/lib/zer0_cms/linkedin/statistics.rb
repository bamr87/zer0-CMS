# frozen_string_literal: true

module Zer0Cms
  module LinkedIn
    # Aggregate statistics for the author's own posts — and nothing about who
    # engaged.
    #
    # Both endpoints return counts attached to a post: impressions, clicks,
    # reactions, comments, shares. There is no per-member record in either,
    # nothing here asks for one, and `normalize` drops every field it does not
    # name, so a field LinkedIn adds later does not flow into the CMS on its
    # own.
    #
    # * A page's posts: `organizationalEntityShareStatistics`, lifetime totals
    #   for up to twenty posts a call. A post LinkedIn leaves out of the answer
    #   had no impressions and no actions — its documentation says to read that
    #   as zero, and only posts this lane asked about are filled in.
    # * A member's post: `memberCreatorPostAnalytics` with the `entity` finder,
    #   one metric per call. `LINK_CLICKS` exists from version 202604.
    module Statistics
      METRICS = %w[impressions clicks reactions comments shares].freeze
      ORGANIZATION_FIELDS = {
        "impressions" => "impressionCount", "clicks" => "clickCount", "reactions" => "likeCount",
        "comments" => "commentCount", "shares" => "shareCount"
      }.freeze
      MEMBER_QUERY_TYPES = {
        "impressions" => "IMPRESSION", "reactions" => "REACTION", "comments" => "COMMENT", "shares" => "RESHARE",
        "clicks" => "LINK_CLICKS"
      }.freeze
      LINK_CLICKS_SINCE = "202604"
      BATCH = 20

      module_function

      # The five counts as non-negative integers, plus `engagements` —
      # reactions, comments and shares, the deliberate actions. This is the
      # shape the TypeScript extension's `normalisePerformance` produces, so a
      # performance.json written by either surface reads the same.
      def normalize(raw)
        clean = METRICS.to_h { |metric| [metric, [raw.to_h[metric].to_i, 0].max] }
        clean.merge("engagements" => clean["reactions"] + clean["comments"] + clean["shares"])
      end

      def for_organization(client, organization:, urns:)
        raise ArgumentError, "not an organization URN: #{organization.inspect}" unless LinkedIn.author_type(organization) == "organization"

        wanted = urns.map(&:to_s).select { |urn| urn.match?(/\Aurn:li:(share|ugcPost):\d+\z/) }.uniq
        out = {}
        shares, ugc_posts = wanted.partition { |urn| urn.start_with?("urn:li:share:") }
        shares.each_slice(BATCH) { |slice| read_organization(client, organization, "shares", slice, out) }
        ugc_posts.each_slice(BATCH) { |slice| read_organization(client, organization, "ugcPosts", slice, out) }
        wanted.each { |urn| out[urn] ||= normalize({}) }
        out
      end

      def for_member_post(client, urn:)
        match = /\Aurn:li:(share|ugcPost):\d+\z/.match(urn.to_s)
        raise ArgumentError, "not a post URN: #{urn.inspect}" unless match

        entity = Restli.record([[match[1] == "ugcPost" ? "ugc" : "share", urn.to_s]])
        raw = {}
        MEMBER_QUERY_TYPES.each do |metric, query_type|
          next if metric == "clicks" && client.api_version < LINK_CLICKS_SINCE

          data = client.json(:member_post_statistics, query: [["q", "entity"], ["entity", entity],
                                                              ["queryType", query_type], ["aggregation", "TOTAL"]])
          raw[metric] = Array(data["elements"]).sum { |element| element["count"].to_i }
        end
        normalize(raw)
      end

      def read_organization(client, organization, param, slice, out)
        data = client.json(:organization_share_statistics,
                           query: [["q", "organizationalEntity"], ["organizationalEntity", organization],
                                   [param, Restli.list(slice)]])
        Array(data["elements"]).each do |element|
          urn = element["share"] || element["ugcPost"]
          next unless slice.include?(urn)

          totals = element["totalShareStatistics"] || {}
          out[urn] = normalize(ORGANIZATION_FIELDS.to_h { |metric, field| [metric, totals[field]] })
        end
      end
    end
  end
end
