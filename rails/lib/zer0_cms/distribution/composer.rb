# frozen_string_literal: true

module Zer0Cms
  module Distribution
    # A deterministic first draft of a share's commentary — so a draft exists
    # with no model and no API key in the path. A person, or an agent working
    # to a skill, rewrites it before anyone approves it.
    #
    # The seed is the Python publisher's, kept byte-compatible so a site moving
    # lanes sees the same default: the page's sub-title (or excerpt, or
    # description) as the hook — never the title, which the link card already
    # shows — then up to three hashtags from its tags.
    module Composer
      ACRONYMS = %w[ai mcp erp crm bi saas iaas smb it api ci cd kpi roi sql hr].freeze
      HOOK_KEYS = %w[sub-title subtitle excerpt].freeze

      module_function

      # `["mcp", "back-office", "ai"]` → `#MCP #BackOffice #AI`
      def hashtags(tags, limit: 3)
        Array(tags).first(limit).filter_map do |tag|
          parts = tag.to_s.strip.split(/[\s_-]+/).reject(&:empty?).map do |token|
            ACRONYMS.include?(token.downcase) ? token.upcase : token.capitalize
          end
          parts.empty? ? nil : "##{parts.join}"
        end.join(" ")
      end

      def default_commentary(entry, limit: 3)
        data = entry.data.is_a?(Hash) ? entry.data : {}
        hook = HOOK_KEYS.map { |key| data[key] }.find { |value| value.is_a?(String) && !value.empty? }
        hook = (hook || entry.description.to_s).strip
        parts = hook.empty? ? [] : [hook]
        tags = hashtags(entry.tags, limit: limit)
        parts << tags unless tags.empty?
        parts.join("\n\n")[0, LinkedIn::COMMENTARY_MAX]
      end

      # A draft filename stem for a page: its slug without a date prefix.
      def slug(entry)
        stem = File.basename(entry.source_relative.to_s, ".*").sub(/\A\d{2,4}-\d{1,2}-\d{1,2}-/, "")
        text = stem.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/\A-+|-+\z/, "")[0, 80].to_s.sub(/-+\z/, "")
        text.empty? ? "post" : text
      end
    end
  end
end
