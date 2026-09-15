# frozen_string_literal: true

require "json"

module Zer0Cms
  module Distribution
    # `zer0-cms linkedin mcp` — the distribution lane as Model Context Protocol
    # tools, over newline-delimited JSON-RPC on stdio, for Claude Code or any
    # MCP client.
    #
    # Reads and previews are always available. `linkedin_draft` writes a
    # pending draft — the doctrine-preferred path: a model drafts, a person
    # approves. There is deliberately no approve tool: approval is a person's
    # decision, recorded in the file by a person.
    #
    # `linkedin_publish` needs three things, none of which a model can supply:
    # `ZER0_LINKEDIN_MCP_PUBLISH=1` in the server's environment,
    # `ZER0_LINKEDIN_PUBLISH=1` (the lane's own arming switch), and
    # `confirm: true` on the call. It then runs the same `Pipeline#publish` as
    # every other surface, so a draft nobody approved is still refused.
    #
    # Every call re-reads the configuration and the queue from disk.
    class Mcp
      PROTOCOLS = %w[2025-06-18 2025-03-26 2024-11-05].freeze
      ARM_VARIABLE = "ZER0_LINKEDIN_MCP_PUBLISH"
      READ = { "readOnlyHint" => true, "openWorldHint" => false }.freeze

      TOOLS = [
        { "name" => "linkedin_status",
          "description" => "The site's LinkedIn distribution state: author, API version health, queue counts, ledger, which credentials are present (never their values). With check: true, asks LinkedIn whether the token is active and when it expires.",
          "inputSchema" => { "type" => "object", "properties" => { "check" => { "type" => "boolean" } } },
          "annotations" => READ.merge("openWorldHint" => true) },
        { "name" => "linkedin_plan",
          "description" => "Every LinkedIn API call this CMS can make — verb, path, scopes, and what comes back. Nothing outside it can be called.",
          "inputSchema" => { "type" => "object", "properties" => {} }, "annotations" => READ },
        { "name" => "linkedin_sources",
          "description" => "Pages that can be shared (live, titled, described, with a public URL). all: true includes pages already shared.",
          "inputSchema" => { "type" => "object", "properties" => { "all" => { "type" => "boolean" } } }, "annotations" => READ },
        { "name" => "linkedin_queue",
          "description" => "The draft queue: every draft with its status (pending, approved, published) and type.",
          "inputSchema" => { "type" => "object", "properties" => {} }, "annotations" => READ },
        { "name" => "linkedin_preview",
          "description" => "The exact LinkedIn payload a draft would send, the brand guard's findings, and every blocker. No network call, no write.",
          "inputSchema" => { "type" => "object", "properties" => { "draft" => { "type" => "string" } }, "required" => ["draft"] },
          "annotations" => READ },
        { "name" => "linkedin_draft",
          "description" => "Write a pending draft into the queue: an article share of a page (source, optional commentary) or a text update (update: true, message, slug). A person must approve it before it can publish.",
          "inputSchema" => { "type" => "object", "properties" => {
            "source" => { "type" => "string" }, "commentary" => { "type" => "string" }, "update" => { "type" => "boolean" },
            "message" => { "type" => "string" }, "slug" => { "type" => "string" }
          } },
          "annotations" => { "readOnlyHint" => false, "destructiveHint" => false, "openWorldHint" => false } },
        { "name" => "linkedin_posts",
          "description" => "The configured author's own recent LinkedIn posts.",
          "inputSchema" => { "type" => "object", "properties" => { "count" => { "type" => "integer", "minimum" => 1, "maximum" => 100 } } },
          "annotations" => READ.merge("openWorldHint" => true) },
        { "name" => "linkedin_publish",
          "description" => "Publish one approved draft to LinkedIn. OFF unless the server was started with ZER0_LINKEDIN_MCP_PUBLISH=1 and ZER0_LINKEDIN_PUBLISH=1; needs confirm: true; refuses any draft the site's approval gate does not accept.",
          "inputSchema" => { "type" => "object", "properties" => { "draft" => { "type" => "string" }, "confirm" => { "type" => "boolean" } },
                             "required" => %w[draft confirm] },
          "annotations" => { "readOnlyHint" => false, "destructiveHint" => false, "openWorldHint" => true } }
      ].freeze

      def initialize(site, env: ENV, transport: nil, input: $stdin, output: $stdout)
        @site = site
        @env = env
        @transport = transport
        @input = input
        @output = output
      end

      def run
        @input.each_line do |line|
          next if line.strip.empty?

          begin
            message = JSON.parse(line)
          rescue JSON::ParserError
            write(error(nil, -32_700, "parse error"))
            next
          end
          response = handle(message)
          write(response) if response
        end
        0
      end

      def handle(message)
        return error(nil, -32_600, "invalid request") unless message.is_a?(Hash)

        id = message["id"]
        method = message["method"].to_s
        return nil if id.nil?

        case method
        when "initialize"
          requested = message.dig("params", "protocolVersion")
          result(id, "protocolVersion" => PROTOCOLS.include?(requested) ? requested : PROTOCOLS.first,
                     "capabilities" => { "tools" => { "listChanged" => false } },
                     "serverInfo" => { "name" => "zer0-linkedin", "version" => Zer0Cms::VERSION },
                     "instructions" => "Draft LinkedIn posts for this site with linkedin_draft; a person approves them. " \
                                       "Preview before anything else. Publishing is off unless the operator armed it.")
        when "ping" then result(id, {})
        when "tools/list" then result(id, "tools" => TOOLS)
        when "tools/call"
          params = message["params"].is_a?(Hash) ? message["params"] : {}
          arguments = params["arguments"].is_a?(Hash) ? params["arguments"] : {}
          result(id, call_tool(params["name"].to_s, arguments))
        else
          error(id, -32_601, "method not found: #{method}")
        end
      end

      def call_tool(name, args)
        config = Config.load(@site, env: @env)
        pipeline = Pipeline.new(config, transport: @transport)
        text(dispatch(name, args, config, pipeline), error: false)
      rescue ArgumentError, KeyError, ConfigError, LinkedIn::Error, Cms::UnsafePath => e
        text("error: #{e.message}", error: true)
      end

      private

      def dispatch(name, args, config, pipeline)
        case name
        when "linkedin_status" then pipeline.status(check: args["check"] == true)
        when "linkedin_plan" then { "calls" => LinkedIn::Plan::CALLS.map(&:to_h) }
        when "linkedin_sources" then pipeline.sources.select { |s| args["all"] == true || !s.shared? }.map(&:to_h)
        when "linkedin_queue"
          pipeline.drafts.map { |d| { "id" => d.id, "path" => d.relative, "status" => d.status, "type" => d.type, "source" => d.source } }
        when "linkedin_preview" then pipeline.preview(pipeline.draft(args.fetch("draft"))).to_h(root: config.root)
        when "linkedin_draft" then draft(pipeline, args, config)
        when "linkedin_posts" then pipeline.posts(count: (args["count"] || 10).to_i)
        when "linkedin_publish" then publish(pipeline, args)
        else raise ArgumentError, "unknown tool #{name}"
        end
      end

      def draft(pipeline, args, config)
        created = if args["update"] == true
                    pipeline.compose_update(args.fetch("message").to_s, slug: args.fetch("slug").to_s)
                  else
                    pipeline.compose(args.fetch("source"), commentary: args["commentary"])
                  end
        { "created" => created.relative, "status" => created.status,
          "preview" => pipeline.preview(created).to_h(root: config.root) }
      end

      def publish(pipeline, args)
        unless Config::TRUTHY.include?(@env[ARM_VARIABLE].to_s.strip.downcase)
          raise ArgumentError, "linkedin_publish is off: the operator must start this server with #{ARM_VARIABLE}=1"
        end
        raise ArgumentError, "linkedin_publish needs confirm: true" unless args["confirm"] == true

        pipeline.publish(pipeline.draft(args.fetch("draft")), live: true).to_h
      end

      def text(data, error:)
        body = data.is_a?(String) ? data : JSON.pretty_generate(data)
        { "content" => [{ "type" => "text", "text" => body }], "isError" => error }
      end

      def result(id, value)
        { "jsonrpc" => "2.0", "id" => id, "result" => value }
      end

      def error(id, code, message)
        { "jsonrpc" => "2.0", "id" => id, "error" => { "code" => code, "message" => message } }
      end

      def write(message)
        @output.write("#{JSON.generate(message)}\n")
        @output.flush
      end
    end
  end
end
