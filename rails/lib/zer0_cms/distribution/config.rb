# frozen_string_literal: true

require "json"
require "pathname"
require "yaml"

module Zer0Cms
  module Distribution
    class ConfigError < StandardError; end

    # The four LinkedIn credentials, from the environment and nowhere else.
    Credentials = Struct.new(:access_token, :refresh_token, :client_id, :client_secret, keyword_init: true) do
      def self.from_env(env)
        new(access_token: env["LINKEDIN_ACCESS_TOKEN"].to_s.strip, refresh_token: env["LINKEDIN_REFRESH_TOKEN"].to_s.strip,
            client_id: env["LINKEDIN_CLIENT_ID"].to_s.strip, client_secret: env["LINKEDIN_CLIENT_SECRET"].to_s.strip)
      end

      def access?
        !access_token.to_s.empty?
      end

      def client?
        !client_id.to_s.empty? && !client_secret.to_s.empty?
      end

      def refresh?
        client? && !refresh_token.to_s.empty?
      end

      # Names only — the values never leave this struct through a report.
      def present
        { "LINKEDIN_ACCESS_TOKEN" => access?, "LINKEDIN_REFRESH_TOKEN" => !refresh_token.to_s.empty?,
          "LINKEDIN_CLIENT_ID" => !client_id.to_s.empty?, "LINKEDIN_CLIENT_SECRET" => !client_secret.to_s.empty? }
      end
    end

    # A site's LinkedIn distribution settings, resolved once per operation.
    #
    # Three layers, most specific first: the environment (an operator's
    # override — `LINKEDIN_AUTHOR_URN`, the older `LINKEDIN_ORG_URN`,
    # `LINKEDIN_BASE_URL`, `LINKEDIN_API_VERSION`), the site's `zer0.json`
    # `distribution.linkedin` block, then `_config.yml` (`url` + `baseurl` for
    # the site URL, `linkedin.org_urn` for the author).
    #
    # The file layers describe; they never arm. Nothing a repository ships —
    # not `zer0.json`, not `_config.yml` — can make a live publish happen.
    # That takes `ZER0_LINKEDIN_PUBLISH=1` in the environment of the process
    # doing it, the same rule the extension applies to `publishAllow`: a cloned
    # repository must not be able to switch on its own publishing.
    class Config
      DEFAULT_QUEUE = ".zer0/drafts/linkedin"
      DEFAULT_LEDGER = ".zer0/ledger.json"
      DEFAULT_ACCEPT = %w[approved].freeze
      ACCEPTABLE = %w[pending approved].freeze
      ARM_VARIABLE = "ZER0_LINKEDIN_PUBLISH"
      # Set by the reusable workflow for a run on the default branch: the drafts
      # it reads were merged, so a `pending` one counts as approved.
      MERGED_VARIABLE = "ZER0_LINKEDIN_MERGED"
      TRUTHY = %w[1 true yes on].freeze
      KEYS = %w[author siteUrl apiVersion queue ledger acceptStatuses sources fallbackImage hashtagLimit
                bannedPatternsFile scopes].freeze

      attr_reader :root, :block, :site_config, :author, :site_url, :api_version, :queue, :ledger, :accept_statuses,
                  :sources, :fallback_image, :hashtag_limit, :banned_patterns_file, :scopes, :cms_root, :env, :problems

      def self.load(root, env: ENV)
        new(root, env: env)
      end

      def initialize(root, env: ENV)
        @root = realpath!(root)
        @env = env
        @problems = []
        zer0 = read_zer0
        linkedin = zer0.dig("distribution", "linkedin") if zer0["distribution"].is_a?(Hash)
        @block = linkedin.is_a?(Hash) ? linkedin : {}
        @site_config = read_site_config
        resolve
        validate
      end

      def configured?
        !@block.empty?
      end

      def author_type
        LinkedIn.author_type(@author)
      end

      def credentials
        Credentials.from_env(@env)
      end

      def publish_armed?
        TRUTHY.include?(@env[ARM_VARIABLE].to_s.strip.downcase)
      end

      def merged?
        TRUTHY.include?(@env[MERGED_VARIABLE].to_s.strip.downcase)
      end

      # The statuses this process may publish. `pending` in acceptStatuses
      # means "a merge to the default branch is the approval", so it counts only
      # where the environment says the run is on that branch; on a laptop, in
      # the MCP server and in the CMS a draft must be `approved`.
      def publishable_statuses
        merged? ? @accept_statuses : @accept_statuses - ["pending"]
      end

      def path(relative)
        File.join(@root, relative)
      end

      def errors
        @problems.select { |severity, _| severity == :error }.map(&:last)
      end

      def warnings
        @problems.select { |severity, _| severity == :warning }.map(&:last)
      end

      private

      def resolve
        jekyll_linkedin = @site_config["linkedin"].is_a?(Hash) ? @site_config["linkedin"] : {}
        @author = first(@env["LINKEDIN_AUTHOR_URN"], @env["LINKEDIN_ORG_URN"], @block["author"], jekyll_linkedin["org_urn"])
        @site_url = first(@env["LINKEDIN_BASE_URL"], @block["siteUrl"], jekyll_url).to_s.chomp("/")
        @api_version = first(@env["LINKEDIN_API_VERSION"], @block["apiVersion"], LinkedIn::DEFAULT_API_VERSION).to_s
        @queue = confined(@block["queue"] || DEFAULT_QUEUE, "queue")
        @ledger = confined(@block["ledger"] || DEFAULT_LEDGER, "ledger")
        @accept_statuses = Array(@block["acceptStatuses"] || DEFAULT_ACCEPT).map { |s| s.to_s.strip.downcase }
        @sources = Array(@block["sources"]).map(&:to_s)
        @fallback_image = @block["fallbackImage"] ? confined(@block["fallbackImage"], "fallbackImage") : nil
        @hashtag_limit = (@block["hashtagLimit"] || 3).to_i.clamp(0, 10)
        @banned_patterns_file = @block["bannedPatternsFile"] ? confined(@block["bannedPatternsFile"], "bannedPatternsFile") : nil
        @scopes = Array(@block["scopes"]).map(&:to_s)
        @cms_root = confined(@zer0_cms_root || ".cms", "cms.root")
      end

      def validate
        (@block.keys - KEYS).each { |key| warn_problem("distribution.linkedin.#{key} is not a setting (known: #{KEYS.join(", ")})") }
        if @author.to_s.empty?
          warn_problem("no LinkedIn author: set distribution.linkedin.author in zer0.json")
        elsif author_type.nil?
          error("author must be urn:li:organization:{id} or urn:li:person:{id}, got #{@author.inspect}")
        end
        case LinkedIn.version_status(@api_version)
        when :invalid then error("apiVersion must be YYYYMM, got #{@api_version.inspect}")
        when :sunset then error("LinkedIn-Version #{@api_version} is past LinkedIn's twelve-month support window; LinkedIn rejects it")
        when :aging then warn_problem("LinkedIn-Version #{@api_version} leaves LinkedIn's support window within two months; bump apiVersion")
        when :future then error("LinkedIn-Version #{@api_version} is in the future")
        end
        if @site_url.empty?
          warn_problem("no site URL: set url in _config.yml or distribution.linkedin.siteUrl — article shares need one")
        elsif !@site_url.match?(%r{\Ahttps?://[^\s/]+})
          error("siteUrl must be an absolute http(s) URL, got #{@site_url.inspect}")
        end
        (@accept_statuses - ACCEPTABLE).each { |status| error("acceptStatuses may hold pending and approved, not #{status.inspect}") }
        error("acceptStatuses is empty — nothing could ever publish") if @accept_statuses.empty?
        if !@accept_statuses.empty? && !@accept_statuses.include?("approved")
          warn_problem("acceptStatuses has no approved: nothing can publish outside a merged run on the default branch")
        end
      end

      def read_zer0
        file = File.join(@root, "zer0.json")
        return {} unless File.file?(file)

        data = Doctor::Jsonc.parse(File.read(file, encoding: "UTF-8"))
        @zer0_cms_root = data.dig("cms", "root") if data["cms"].is_a?(Hash)
        data.is_a?(Hash) ? data : {}
      rescue JSON::ParserError => e
        error("zer0.json does not parse: #{e.message.lines.first.to_s.strip}")
        {}
      end

      def read_site_config
        file = File.join(@root, "_config.yml")
        return {} unless File.file?(file)

        data = YAML.safe_load(File.read(file, encoding: "UTF-8"), permitted_classes: [Date, Time], aliases: true)
        data.is_a?(Hash) ? data : {}
      rescue Psych::Exception => e
        error("_config.yml does not parse: #{e.message.lines.first.to_s.strip}")
        {}
      end

      def jekyll_url
        url = @site_config["url"].to_s.strip
        return nil if url.empty?

        "#{url.chomp("/")}#{@site_config["baseurl"].to_s.strip.chomp("/")}"
      end

      # A repository-relative path that stays inside the repository.
      def confined(value, key)
        text = value.to_s.strip.tr("\\", "/")
        if text.empty? || text.start_with?("/") || text.split("/").include?("..") || text.match?(/\A[A-Za-z]:/)
          raise ConfigError, "distribution.linkedin.#{key} must be a path inside the repository, got #{value.inspect}"
        end

        Pathname.new(text).cleanpath.to_s
      end

      def realpath!(root)
        File.realpath(root.to_s)
      rescue SystemCallError
        raise ConfigError, "#{root} is not a directory"
      end

      def first(*values)
        values.map { |v| v.to_s.strip }.find { |v| !v.empty? }
      end

      def error(message)
        @problems << [:error, message]
      end

      def warn_problem(message)
        @problems << [:warning, message]
      end
    end
  end
end
