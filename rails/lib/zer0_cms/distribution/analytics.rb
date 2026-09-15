# frozen_string_literal: true

require "fileutils"
require "json"
require "securerandom"

module Zer0Cms
  module Distribution
    # Closing the loop: how the author's own posts performed, written back into
    # the site's `.cms/distribution/performance.json`.
    #
    # Statistics arrive keyed by post URN and leave keyed by content path; the
    # ledger is the join table, because it is the only thing that knows which
    # post came from which page. The file is the shape the VS Code extension
    # already reads (`writePerformance` in src/core/contract/contract.ts) —
    # `generated_at`, `note`, and `content` mapping a path to impressions,
    # clicks, reactions, comments, shares and engagements — so the extension's
    # catering worklist ranks subjects from numbers this lane fetched.
    #
    # A refresh merges over what is there: statistics for this week's posts
    # update those rows and leave the history the stale-content lane depends on.
    module Analytics
      NOTE = "Aggregate statistics for the author's own content. No per-reader data."
      POST = /\Aurn:li:(share|ugcPost):\d+\z/

      module_function

      def relative_path(config)
        File.join(config.cms_root, "distribution", "performance.json")
      end

      # { performance: { path => stats }, matched: [urn], skipped: [key] }
      def fetch(pipeline)
        config = pipeline.config
        rows = pipeline.ledger.shares
        own, skipped = rows.partition do |_, entry|
          entry["urn"].to_s.match?(POST) && !entry["source_file"].to_s.empty? &&
            (entry["author"].to_s.empty? || entry["author"] == config.author)
        end
        urns = own.map { |_, entry| entry["urn"] }
        stats = urns.empty? ? {} : read(pipeline, config, urns)
        performance = {}
        own.each do |_, entry|
          counts = stats[entry["urn"]]
          performance[entry["source_file"]] = counts if counts
        end
        { performance: performance, matched: urns.select { |urn| stats.key?(urn) }, skipped: skipped.map(&:first) }
      end

      def read(pipeline, config, urns)
        pipeline.with_client do |client|
          case config.author_type
          when "organization" then LinkedIn::Statistics.for_organization(client, organization: config.author, urns: urns)
          when "person" then urns.to_h { |urn| [urn, LinkedIn::Statistics.for_member_post(client, urn: urn)] }
          else raise ConfigError, "no LinkedIn author configured"
          end
        end
      end

      def load(config)
        path = config.path(relative_path(config))
        return {} unless File.file?(path)

        data = JSON.parse(File.read(path, encoding: "UTF-8"))
        data.is_a?(Hash) && data["content"].is_a?(Hash) ? data["content"] : {}
      rescue JSON::ParserError
        {}
      end

      def write(config, performance, now: Time.now)
        path = config.path(relative_path(config))
        content = load(config).merge(performance).sort.to_h
        payload = { "generated_at" => now.utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "note" => NOTE, "content" => content }
        FileUtils.mkdir_p(File.dirname(path))
        temp = "#{path}.#{SecureRandom.hex(4)}.tmp"
        File.write(temp, "#{PyJson.dump(payload, indent: 2, ensure_ascii: true)}\n")
        File.rename(temp, path)
        relative_path(config)
      ensure
        FileUtils.rm_f(temp) if temp && File.exist?(temp)
      end
    end
  end
end
