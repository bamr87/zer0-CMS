# frozen_string_literal: true

require "json"
require "optparse"

module Zer0Cms
  module Distribution
    # `zer0-cms linkedin COMMAND` — the lane from a terminal and from CI.
    #
    # Exit status: 0 when the command did what it says, 1 when something was
    # refused or failed (a blocker, a LinkedIn error, a bad configuration),
    # 2 on bad usage. `preview` and a rehearsed `publish` exit 1 when a draft
    # has a blocker that arming would not lift, so a dry run in CI fails on a
    # guard error rather than passing silently.
    module CLI
      USAGE = <<~TEXT
        zer0-cms linkedin — LinkedIn distribution for a zer0 site

        Usage: zer0-cms linkedin COMMAND [--site PATH] [--json] [options]

          status [--check] [--warn-days N]   settings, queue and ledger; --check asks LinkedIn about the token
          plan                               every LinkedIn call this CMS can make, and nothing else
          sources [--all]                    pages that can be shared (--all includes shared ones)
          queue                              drafts and their status
          draft SOURCE [--commentary TEXT | --commentary-file FILE]
          draft --update --slug SLUG (--message TEXT | --message-file FILE)
                                             write a pending draft
          approve DRAFT                      pending -> approved: a person's decision
          preview [DRAFT]                    the exact payload, the guard and every blocker; no network
          publish [DRAFT] [--live]           rehearse; with --live and ZER0_LINKEDIN_PUBLISH=1, post
          publish DRAFT --live --force       post past a guard error, a ledger entry or an unconfirmed attempt
          record DRAFT URN                   record a post a person found on LinkedIn
          posts [--count N]                  the author's own recent posts
          verify URN                         read one post back
          organizations                      pages the token's member may post to
          stats [--write]                    aggregate statistics for published posts
          connect [--port N] [--redirect-uri URL] [--write-env FILE | --print-token]
                                             three-legged OAuth through a loopback callback
          mcp                                the same tools over MCP (stdio)

        Credentials come from the environment only: LINKEDIN_ACCESS_TOKEN, and optionally
        LINKEDIN_REFRESH_TOKEN with LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET.
        Settings: zer0.json "distribution": { "linkedin": { ... } } (docs/DISTRIBUTION.md).
      TEXT

      module_function

      def main(argv, out: $stdout, err: $stderr, env: ENV, transport: nil, input: $stdin)
        argv = argv.dup
        command = argv.shift
        if command.nil? || %w[-h --help help].include?(command)
          out.puts USAGE
          return 0
        end

        opts = parse(argv)
        config = Config.load(opts[:site], env: env)
        pipeline = Pipeline.new(config, transport: transport)
        runner = Runner.new(pipeline, opts, argv, out: out, err: err, env: env, transport: transport, input: input)
        raise OptionParser::InvalidArgument, "unknown command #{command}" unless Runner::COMMANDS.include?(command)

        runner.public_send(command.to_sym)
      rescue OptionParser::ParseError => e
        err.puts "error: #{e.message}\n\n#{USAGE}"
        2
      rescue ConfigError, ArgumentError, KeyError, Cms::UnsafePath => e
        err.puts "error: #{e.message}"
        1
      rescue LinkedIn::Error => e
        err.puts "LinkedIn: #{e.message}"
        1
      end

      def parse(argv)
        opts = { site: ".", json: false, count: 10, warn_days: 7, port: 8765 }
        OptionParser.new do |o|
          o.on("--site PATH") { |v| opts[:site] = v }
          o.on("--json") { opts[:json] = true }
          o.on("--check") { opts[:check] = true }
          o.on("--warn-days N", Integer) { |v| opts[:warn_days] = v }
          o.on("--all") { opts[:all] = true }
          o.on("--commentary TEXT") { |v| opts[:commentary] = v }
          o.on("--commentary-file FILE") { |v| opts[:commentary] = File.read(v, encoding: "UTF-8") }
          o.on("--update") { opts[:update] = true }
          o.on("--slug SLUG") { |v| opts[:slug] = v }
          o.on("--message TEXT") { |v| opts[:message] = v }
          o.on("--message-file FILE") { |v| opts[:message] = File.read(v, encoding: "UTF-8") }
          o.on("--live") { opts[:live] = true }
          o.on("--force") { opts[:force] = true }
          o.on("--count N", Integer) { |v| opts[:count] = v }
          o.on("--write") { opts[:write] = true }
          o.on("--port N", Integer) { |v| opts[:port] = v }
          o.on("--redirect-uri URL") { |v| opts[:redirect_uri] = v }
          o.on("--write-env FILE") { |v| opts[:write_env] = v }
          o.on("--print-token") { opts[:print_token] = true }
        end.parse!(argv)
        opts
      end

      # One method per command, so `main` can dispatch by name and a test can
      # drive a command without a subprocess.
      class Runner
        COMMANDS = %w[status plan sources queue draft approve preview publish record posts verify organizations stats connect mcp].freeze

        def initialize(pipeline, opts, args, out:, err:, env:, transport:, input:)
          @pipeline = pipeline
          @config = pipeline.config
          @opts = opts
          @args = args
          @out = out
          @err = err
          @env = env
          @transport = transport
          @input = input
        end

        def status
          report = @pipeline.status(check: @opts[:check], warn_days: @opts[:warn_days])
          if @opts[:json]
            emit(report)
          else
            print_status(report)
          end
          failed = report["errors"].any? || (@opts[:check] && !report.dig("token", "ok"))
          failed ? 1 : 0
        end

        def plan
          @opts[:json] ? emit("calls" => LinkedIn::Plan::CALLS.map(&:to_h)) : @out.puts(LinkedIn::Plan.describe)
          0
        end

        def sources
          list = @pipeline.sources.select { |source| @opts[:all] || !source.shared? }
          if @opts[:json]
            emit(list.map(&:to_h))
          elsif list.empty?
            @out.puts(@opts[:all] ? "No shareable pages." : "Every shareable page has been shared.")
          else
            list.each do |source|
              @out.puts "#{source.shared? ? "shared  " : "        "} #{source.entry.relative}"
              @out.puts "          #{source.url}#{source.shared? ? "  (#{source.urn})" : ""}"
            end
          end
          0
        end

        def queue
          drafts = @pipeline.drafts
          if @opts[:json]
            emit(drafts.map { |d| { "id" => d.id, "path" => d.relative, "status" => d.status, "type" => d.type, "source" => d.source } })
          elsif drafts.empty?
            @out.puts "The queue (#{@config.queue}) is empty."
          else
            drafts.each { |d| @out.puts "#{d.status.ljust(10)} #{d.type.ljust(8)} #{d.relative}#{d.source.empty? ? "" : "  <- #{d.source}"}" }
          end
          0
        end

        def draft
          created = if @opts[:update]
                      raise ArgumentError, "an update needs --slug and --message (or --message-file)" unless @opts[:slug] && @opts[:message]

                      @pipeline.compose_update(@opts[:message], slug: @opts[:slug])
                    else
                      source = @args.shift || raise(ArgumentError, "draft needs a SOURCE page (or --update)")
                      @pipeline.compose(source, commentary: @opts[:commentary])
                    end
          preview = @pipeline.preview(created)
          if @opts[:json]
            emit("created" => created.relative, "preview" => preview.to_h(root: @config.root))
          else
            @out.puts "wrote #{created.relative} (status: pending — a person approves it)"
            print_preview(preview)
          end
          0
        end

        def approve
          outcome = @pipeline.approve(@pipeline.draft(required_arg("DRAFT")))
          report(outcome)
        end

        def preview
          drafts = @args.empty? ? @pipeline.drafts.reject { |d| d.status == "published" } : [@pipeline.draft(@args.shift)]
          previews = drafts.map { |d| @pipeline.preview(d) }
          if @opts[:json]
            emit(previews.map { |p| p.to_h(root: @config.root) })
          elsif previews.empty?
            @out.puts "Nothing to preview: no unpublished drafts in #{@config.queue}."
          else
            previews.each { |p| print_preview(p) }
          end
          previews.any? { |p| p.problems.any? } ? 1 : 0
        end

        def record
          draft = @pipeline.draft(required_arg("DRAFT"))
          report(@pipeline.record_post(draft, required_arg("URN")))
        end

        def publish
          outcomes = if @args.empty?
                       @pipeline.publish_queue(live: @opts[:live], force: @opts[:force])
                     else
                       [@pipeline.publish(@pipeline.draft(@args.shift), live: @opts[:live], force: @opts[:force])]
                     end
          if @opts[:json]
            emit(outcomes.map { |o| o.to_h.merge("preview" => o.preview&.to_h(root: @config.root)) })
          elsif outcomes.empty?
            @out.puts "Nothing to publish: no draft in #{@config.queue} has an accepted status (#{@config.accept_statuses.join(", ")})."
          else
            outcomes.each do |outcome|
              print_preview(outcome.preview) if outcome.preview && !@opts[:live]
              print_outcome(outcome)
            end
          end
          outcomes.all?(&:ok?) ? 0 : 1
        end

        def posts
          list = @pipeline.posts(count: @opts[:count])
          @opts[:json] ? emit(list) : list.each { |post| @out.puts "#{post["id"]}  #{post["commentary"].to_s.lines.first.to_s.strip[0, 90]}" }
          0
        end

        def verify
          emit(@pipeline.verify(required_arg("URN")))
          0
        end

        def organizations
          pages = @pipeline.organizations
          if pages.nil?
            @err.puts "This token may not read page roles (it needs r_organization_admin or rw_organization_admin)."
            return 1
          end
          if @opts[:json]
            emit(pages.map { |page| page.to_h.transform_keys(&:to_s) })
          elsif pages.empty?
            @out.puts "The token's member holds no posting role on any page."
          else
            pages.each { |page| @out.puts "#{page.urn.ljust(36)} #{page.role.ljust(24)} #{page.name}" }
          end
          0
        end

        def stats
          result = @pipeline.statistics(write: @opts[:write])
          if @opts[:json]
            emit("performance" => result[:performance], "matched" => result[:matched], "skipped" => result[:skipped],
                 "written" => result[:path])
          else
            result[:performance].each do |path, counts|
              @out.puts "#{path}\n  #{counts.map { |k, v| "#{k} #{v}" }.join(", ")}"
            end
            @out.puts "no published posts with statistics" if result[:performance].empty?
            @out.puts "wrote #{result[:path]}" if result[:path]
          end
          0
        end

        def connect
          credentials = @config.credentials
          raise ConfigError, "connect needs LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in the environment" unless credentials.client?

          redirect = @opts[:redirect_uri] || "http://127.0.0.1:#{@opts[:port]}/callback"
          callback = URI.parse(redirect)
          unless %w[127.0.0.1 localhost [::1]].include?(callback.host.to_s) && callback.port
            raise ArgumentError, "--redirect-uri must be a loopback URL with a port, e.g. http://127.0.0.1:8765/callback"
          end
          scopes = @config.scopes.empty? ? LinkedIn::OAuth.scopes_for(@config.author_type) : @config.scopes
          oauth = @pipeline.oauth
          state = LinkedIn::OAuth.new_state
          @out.puts "Add #{redirect} to the app's authorized redirect URLs, then open this URL as the member who"
          @out.puts "owns the account (or administers the page) and approve:\n\n#{oauth.authorize_url(redirect_uri: redirect, state: state, scopes: scopes)}\n\n"
          @out.puts "Waiting for LinkedIn's redirect on #{redirect} …"
          params = Callback.wait(port: callback.port, path: callback.path)
          raise LinkedIn::Error, "LinkedIn answered #{params["error"]}: #{params["error_description"]}" if params["error"]
          raise LinkedIn::Error, "the callback's state does not match — refusing its code" unless LinkedIn::OAuth.state_matches?(state, params["state"])

          token = oauth.exchange(code: params["code"], redirect_uri: redirect)
          @out.puts "Connected. Scopes: #{token.scopes.join(" ")}. Access token expires #{token.expires_at&.utc&.iso8601} (#{token.days_left} days)."
          @out.puts "Refresh token expires #{token.refresh_expires_at.utc.iso8601}." if token.refresh_expires_at
          if token.scopes.include?("openid")
            member = LinkedIn::OAuth.member(LinkedIn::Client.new(token: token.access_token, api_version: @config.api_version, transport: @transport || LinkedIn::NetHttpTransport.new))
            @out.puts "Member: #{member["name"]} — #{member["urn"]} (use it as distribution.linkedin.author for a profile)"
          end
          store_token(token)
          0
        end

        def mcp
          $stdout = @err if @out.equal?($stdout)
          Mcp.new(@config.root, env: @env, transport: @transport, input: @input, output: @out).run
        end

        private

        def store_token(token)
          if @opts[:write_env]
            file = File.expand_path(@opts[:write_env], @config.root)
            unless system("git", "-C", @config.root, "check-ignore", "-q", file, out: File::NULL, err: File::NULL)
              raise ConfigError, "#{@opts[:write_env]} is not ignored by git — refusing to write a token into it"
            end

            write_env(file, "LINKEDIN_ACCESS_TOKEN" => token.access_token, "LINKEDIN_REFRESH_TOKEN" => token.refresh_token)
            @out.puts "Wrote the token to #{@opts[:write_env]} (mode 600)."
          elsif @opts[:print_token]
            @out.puts "LINKEDIN_ACCESS_TOKEN=#{token.access_token}"
            @out.puts "LINKEDIN_REFRESH_TOKEN=#{token.refresh_token}" if token.refresh_token
          else
            @out.puts "The token was not stored. Re-run with --write-env .env (a gitignored file) or --print-token to copy it into a secret."
          end
        end

        def write_env(file, pairs)
          pairs = pairs.compact
          lines = File.file?(file) ? File.readlines(file, chomp: true) : []
          seen = []
          lines = lines.map do |line|
            key = line.split("=", 2).first.to_s.strip
            next line unless pairs.key?(key)

            seen << key
            "#{key}=#{pairs[key]}"
          end
          (pairs.keys - seen).each { |key| lines << "#{key}=#{pairs[key]}" }
          File.write(file, "#{lines.join("\n")}\n")
          File.chmod(0o600, file)
        end

        def required_arg(name)
          @args.shift || raise(ArgumentError, "missing #{name}")
        end

        def emit(data)
          @out.puts JSON.pretty_generate(data)
        end

        def report(outcome)
          @opts[:json] ? emit(outcome.to_h) : print_outcome(outcome)
          outcome.ok? ? 0 : 1
        end

        def print_outcome(outcome)
          @out.puts "#{outcome.state.to_s.upcase.ljust(9)} #{outcome.draft&.relative}"
          outcome.messages.each { |message| @out.puts "  #{message}" }
        end

        def print_status(report)
          @out.puts "LinkedIn distribution — #{report["site"]}"
          @out.puts "  configured   #{report["configured"] ? "yes (zer0.json distribution.linkedin)" : "no"}"
          @out.puts "  author       #{report["author"] || "(none)"}#{report["author_type"] ? " [#{report["author_type"]}]" : ""}"
          @out.puts "  site URL     #{report["site_url"].to_s.empty? ? "(none)" : report["site_url"]}"
          @out.puts "  API version  #{report["api_version"]} (#{report["api_version_status"]})"
          @out.puts "  queue        #{report["queue"]} — #{report["drafts"].map { |k, v| "#{v} #{k}" }.join(", ")}"
          @out.puts "  ledger       #{report["ledger"]} — #{report["published"]} published#{report["ledger_readable"] ? "" : " (UNREADABLE)"}"
          @out.puts "  accepts      #{report["accept_statuses"].join(", ")} (in this run: #{report["publishable_statuses"].join(", ").then { |s| s.empty? ? "none" : s }})"
          @out.puts "  armed        #{report["armed"] ? "yes" : "no (#{Config::ARM_VARIABLE} is not set)"}"
          @out.puts "  credentials  #{report["credentials"].select { |_, v| v }.keys.join(", ").then { |s| s.empty? ? "(none)" : s }}"
          report["errors"].each { |message| @out.puts "  ERROR    #{message}" }
          report["warnings"].each { |message| @out.puts "  warning  #{message}" }
          token = report["token"]
          return unless token

          @out.puts "  token        #{token["ok"] ? "ok" : "NOT OK"}#{token["days_left"] ? " — #{token["days_left"]} day(s) left" : ""}"
          Array(token["problems"]).each { |message| @out.puts "    problem  #{message}" }
          Array(token["notes"]).each { |message| @out.puts "    note     #{message}" }
        end

        def print_preview(preview)
          draft = preview.draft
          @out.puts "\n#{draft.relative}  [#{draft.status}, #{preview.kind}]"
          @out.puts "  key        #{preview.key || "(none)"}"
          @out.puts "  source     #{preview.entry.relative}" if preview.entry
          @out.puts "  image      #{preview.thumbnail ? preview.thumbnail.delete_prefix("#{@config.root}/") : "(none)"}"
          escaped = LinkedIn::Posts.commentary_length(preview.commentary)
          @out.puts "  commentary #{escaped} chars as sent (LinkedIn folds at #{Guard::FOLD}):"
          preview.commentary.each_line { |line| @out.puts "    | #{line.chomp}" }
          preview.notes.each { |note| @out.puts "  note       #{note}" }
          preview.guard.reject { |f| f.level == "info" }.each { |f| @out.puts "  #{f.level.upcase.ljust(10)} #{f.message}" }
          if preview.blockers.empty?
            @out.puts "  blockers   none"
          else
            preview.blockers.each { |b| @out.puts "  blocked    #{b.kind}: #{b.message}" }
          end
          @out.puts "  payload    POST https://api.linkedin.com/rest/posts (LinkedIn-Version #{@config.api_version})"
          JSON.pretty_generate(preview.payload).each_line { |line| @out.puts "    #{line.chomp}" } if preview.payload
        end
      end
    end
  end
end
