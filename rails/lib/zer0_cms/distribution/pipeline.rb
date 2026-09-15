# frozen_string_literal: true

require "date"
require "json"

module Zer0Cms
  module Distribution
    # The governed path from a page to a LinkedIn post, and the only one.
    #
    #   page ──▶ draft (pending) ──▶ approve ──▶ preview ──▶ publish ──▶ ledger
    #                                  a person   no network   gated      keyed by URL
    #
    # The CLI, the reusable workflow, the MCP server and the Rails CMS all call
    # these methods, so there is one gate to audit.
    #
    # `preview` is pure: it reads files and computes, and makes no network call
    # and no write. What a reviewer sees — the exact payload, the guard's
    # findings, every blocker — is the artifact `publish` sends, not a
    # description of it.
    #
    # `publish` re-reads the draft from disk, rebuilds the preview and refuses on
    # any blocker, in a fixed order:
    #
    #   config_error, no_author, source_missing, ledger_unreadable, guard_error,
    #   already_published, publish_unconfirmed, status_not_accepted,
    #   publish_disabled, no_credential
    #
    # `force` overrides exactly three, and only for one named draft — a guard
    # error a person has read, a ledger entry they mean to post past, and an
    # unconfirmed earlier attempt they have checked did not post. It never
    # overrides the status gate
    # (approval is a person's act, recorded in the file) or the arming gate
    # (`ZER0_LINKEDIN_PUBLISH=1` plus `live`), which no file and no flag can set.
    class Pipeline
      ORDER = %i[config_error no_author source_missing ledger_unreadable guard_error already_published
                 publish_unconfirmed status_not_accepted publish_disabled no_credential].freeze
      FORCEABLE = %i[guard_error already_published publish_unconfirmed].freeze
      LIVE_ONLY = %i[publish_disabled no_credential].freeze
      # Gates that say a draft is not cleared to go yet, not that anything is
      # wrong with it. A preview or a rehearsal passes with only these.
      WAITING = %i[status_not_accepted publish_disabled no_credential].freeze

      Blocker = Struct.new(:kind, :message) do
        def to_h
          { "kind" => kind.to_s, "message" => message }
        end
      end

      Source = Struct.new(:entry, :url, :urn, keyword_init: true) do
        def shared?
          !urn.nil?
        end

        def to_h
          { "path" => entry.relative, "collection" => entry.collection.to_s, "title" => entry.title,
            "date" => entry.date_raw.to_s, "url" => url, "linkedin_urn" => urn }
        end
      end

      Preview = Struct.new(:draft, :kind, :key, :entry, :commentary, :payload, :thumbnail, :notes, :guard, :blockers,
                           keyword_init: true) do
        def blocked?(live: true)
          relevant(live).any?
        end

        def relevant(live)
          live ? blockers : blockers.reject { |b| LIVE_ONLY.include?(b.kind) }
        end

        # What is wrong with the draft, as opposed to what it is waiting for.
        def problems
          blockers.reject { |b| WAITING.include?(b.kind) }
        end

        def to_h(root: nil)
          {
            "draft" => draft.relative, "status" => draft.status, "type" => kind, "key" => key,
            "source" => entry&.relative, "commentary" => commentary,
            "commentary_length" => LinkedIn::Posts.commentary_length(commentary), "fold" => Guard::FOLD,
            "payload" => payload,
            "thumbnail" => thumbnail && root ? thumbnail.delete_prefix("#{root}/") : thumbnail,
            "notes" => notes, "guard" => guard.map(&:to_h), "blockers" => blockers.map(&:to_h)
          }
        end
      end

      Outcome = Struct.new(:state, :draft, :key, :urn, :messages, :preview, keyword_init: true) do
        def ok?
          %i[published skipped rehearsed approved recorded].include?(state)
        end

        def to_h
          { "state" => state.to_s, "draft" => draft&.relative, "key" => key, "linkedin_urn" => urn,
            "messages" => messages }
        end
      end

      attr_reader :config

      def initialize(config, transport: nil, sleeper: ->(seconds) { sleep(seconds) }, clock: -> { Time.now.utc },
                     credentials: nil)
        @config = config
        @transport = transport || LinkedIn::NetHttpTransport.new
        @sleeper = sleeper
        @clock = clock
        @credentials = credentials || config.credentials
        @refreshed = false
      end

      def catalog
        @catalog ||= Cms::Catalog.scan(@config.root)
      end

      def ledger
        @ledger ||= Ledger.new(@config.path(@config.ledger))
      end

      def drafts
        Drafts.list(@config)
      end

      def draft(ref)
        Drafts.find!(@config, ref)
      end

      # ---------------------------------------------------------------------
      # What can be shared
      # ---------------------------------------------------------------------

      def canonical_url(entry)
        return nil if @config.site_url.empty?

        path = Permalink.path_for(catalog.config, entry)
        path && "#{@config.site_url}#{path}"
      end

      # Live content with a title, a description and a public URL, in the
      # configured collections — each with the post URN if it was shared.
      def sources
        data = ledger.load
        catalog.entries.filter_map do |entry|
          next unless shareable?(entry)

          url = canonical_url(entry)
          url && Source.new(entry: entry, url: url, urn: Ledger.urn_of(data[url]))
        end
      end

      # A section index (`index.md`, or a dated `2000-01-01-index.md` the way
      # zer0 sites keep one per post section) is structure, not something to
      # put in a feed.
      def shareable?(entry)
        entry.live? && entry.error.nil? && entry.kind != :draft && !structural?(entry) &&
          (@config.sources.empty? || @config.sources.include?(entry.collection.to_s)) &&
          !entry.title.to_s.strip.empty? && !entry.description.to_s.strip.empty?
      end

      def structural?(entry)
        File.basename(entry.source_relative.to_s, ".*").sub(/\A\d{2,4}-\d{1,2}-\d{1,2}-/, "") == "index"
      end

      # A page by repository path, source path, `section/YYYY-MM-DD-slug`
      # suffix, or a slug that names exactly one page.
      def resolve_source(ref)
        wanted = ref.to_s.strip.delete_prefix("./").delete_prefix("/")
        return nil if wanted.empty? || wanted.match?(%r{\A[a-z][a-z0-9+.-]*://}i)

        stem = ->(path) { path.to_s.sub(%r{\.[^./]+\z}, "") }
        target = stem.call(wanted)
        candidates = catalog.entries.reject { |entry| entry.kind == :draft }
        exact = candidates.find do |entry|
          [entry.relative, entry.source_relative].include?(wanted) ||
            [stem.call(entry.relative), stem.call(entry.source_relative)].include?(target)
        end
        return exact if exact

        suffix = candidates.select { |entry| stem.call(entry.source_relative).end_with?("/#{target}") }
        return suffix.first if suffix.size == 1

        slug = File.basename(target).sub(/\A\d{2,4}-\d{1,2}-\d{1,2}-/, "")
        by_slug = candidates.select do |entry|
          File.basename(stem.call(entry.source_relative)).sub(/\A\d{2,4}-\d{1,2}-\d{1,2}-/, "") == slug
        end
        by_slug.size == 1 ? by_slug.first : nil
      end

      # ---------------------------------------------------------------------
      # Drafting and approving
      # ---------------------------------------------------------------------

      # A pending article draft for a page, seeded with the default commentary
      # unless `commentary` is given.
      def compose(ref, commentary: nil, date: @clock.call.to_date)
        entry = resolve_source(ref) || raise(ArgumentError, "no page on this site matches #{ref.inspect}")
        raise ArgumentError, "#{entry.relative} is not live content (draft, unpublished or future)" unless entry.live?

        url = canonical_url(entry) || raise(ArgumentError, "#{entry.relative} has no public URL — set the site URL")
        if (urn = ledger.urn_for(url))
          raise ArgumentError, "#{entry.relative} was already shared as #{urn}"
        end

        body = commentary.to_s.strip.empty? ? Composer.default_commentary(entry, limit: @config.hashtag_limit) : commentary
        Drafts.create(@config, type: "article", slug: "#{date.strftime("%Y-%m-%d")}-#{Composer.slug(entry)}", body: body,
                               meta: { "source" => entry.relative, "title" => entry.title, "url" => url })
      end

      def compose_update(message, slug:, date: @clock.call.to_date)
        Drafts.create(@config, type: "update", slug: "#{date.strftime("%Y-%m-%d")}-#{slug}", body: message)
      end

      # pending → approved. The guard's errors block it; nothing else about
      # publishing is in play yet.
      def approve(draft)
        draft = Drafts.read(@config, draft.path)
        unless draft.status == "pending"
          return Outcome.new(state: :blocked, draft: draft, messages: ["draft is already #{draft.status}"])
        end

        errors = Guard.check(draft.commentary, extra: Guard.patterns_for(@config)).select(&:error?).map(&:message)
        return Outcome.new(state: :blocked, draft: draft, messages: ["brand guard: #{errors.join("; ")}"]) unless errors.empty?

        Drafts.set_status(draft, "approved")
        Outcome.new(state: :approved, draft: Drafts.read(@config, draft.path), messages: ["approved #{draft.relative}"])
      end

      # ---------------------------------------------------------------------
      # Preview: the exact artifact, no network, no writes
      # ---------------------------------------------------------------------

      def preview(draft)
        blockers = []
        notes = []
        @config.errors.each { |message| blockers << Blocker.new(:config_error, message) }
        author = @config.author.to_s
        author_ok = !LinkedIn.author_type(author).nil?
        unless author_ok
          blockers << Blocker.new(:no_author, author.empty? ? "no LinkedIn author configured (distribution.linkedin.author)" : "author is not a person or organization URN: #{author}")
        end

        commentary = draft.commentary
        entry = nil
        key = nil
        payload = nil
        thumbnail = nil

        case draft.type
        when "update"
          key = "draft:#{draft.relative}"
          blockers << Blocker.new(:source_missing, "an update needs a body") if commentary.empty?
          payload = LinkedIn::Posts.text_payload(author: author, commentary: commentary) if author_ok && !commentary.empty?
        when "article"
          entry = draft.source.empty? ? nil : resolve_source(draft.source)
          url = entry ? canonical_url(entry) : nil
          url ||= draft.link unless draft.link.empty?
          title = entry ? entry.title.to_s : draft.title
          description = entry ? entry.description.to_s : draft.description
          if !draft.source.empty? && entry.nil?
            blockers << Blocker.new(:source_missing, "source #{draft.source} does not match a page on this site")
          elsif url.nil?
            blockers << Blocker.new(:source_missing, entry ? "#{entry.relative} has no public URL — set the site URL" : "an article needs a source page or a link")
          elsif title.strip.empty? || description.strip.empty?
            blockers << Blocker.new(:source_missing, "the link card needs a title and a description")
          end
          if commentary.empty? && entry
            commentary = Composer.default_commentary(entry, limit: @config.hashtag_limit)
            notes << "the draft has no body; the page's default commentary will publish"
          end
          thumbnail = thumbnail_for(entry, notes) unless draft.no_thumbnail?
          key = url
          if author_ok && url && !title.strip.empty?
            begin
              payload = LinkedIn::Posts.article_payload(author: author, commentary: commentary, source: url, title: title,
                                                        description: description)
            rescue ArgumentError => e
              blockers << Blocker.new(:source_missing, e.message)
            end
          end
        else
          blockers << Blocker.new(:source_missing, "unknown draft type #{draft.type.inspect} (article or update)")
        end

        guard = Guard.check(commentary, extra: Guard.patterns_for(@config))
        escaped = LinkedIn::Posts.commentary_length(commentary)
        if escaped > LinkedIn::COMMENTARY_MAX && commentary.length <= Guard::MAX_LEN
          guard.insert(-2, Guard::Finding.new("error", "commentary is #{escaped} chars once escaped for LinkedIn (max #{LinkedIn::COMMENTARY_MAX})"))
        end
        errors = guard.select(&:error?).map(&:message)
        blockers << Blocker.new(:guard_error, "brand guard: #{errors.join("; ")}") unless errors.empty?

        if !ledger.readable?
          blockers << Blocker.new(:ledger_unreadable, "#{@config.ledger} is not valid JSON — fix it before publishing")
        elsif key && (urn = ledger.urn_for(key))
          blockers << Blocker.new(:already_published, "already published as #{urn}")
        elsif key && (attempt = ledger.unconfirmed(key))
          blockers << Blocker.new(:publish_unconfirmed, "an attempt on #{attempt["attempted_at"]} may have posted this " \
                                                        "(#{attempt["error"]}): check the author's LinkedIn posts, then run " \
                                                        "`zer0-cms linkedin record #{draft.id} URN` if it did, or publish it with --force if it did not")
        end

        accepted = @config.publishable_statuses
        if draft.status == "published"
          blockers << Blocker.new(:status_not_accepted, "draft is already published")
        elsif draft.status == "pending" && @config.accept_statuses.include?("pending") && !accepted.include?("pending")
          blockers << Blocker.new(:status_not_accepted, "draft is pending: this site publishes a pending draft only once it is merged " \
                                                        "(#{Config::MERGED_VARIABLE}=1, set by the workflow on the default branch); approve it to publish here")
        elsif !accepted.include?(draft.status)
          blockers << Blocker.new(:status_not_accepted, "draft status is #{draft.status} (accepted here: #{accepted.empty? ? "none" : accepted.join(", ")})")
        end
        unless @config.publish_armed?
          blockers << Blocker.new(:publish_disabled, "publishing is not armed (#{Config::ARM_VARIABLE}=1 in the environment, and a live run)")
        end
        unless @credentials.access? || @credentials.refresh?
          blockers << Blocker.new(:no_credential, "no LinkedIn credential (LINKEDIN_ACCESS_TOKEN, or a refresh token with the app credentials)")
        end

        ordered = blockers.each_with_index.sort_by { |blocker, index| [ORDER.index(blocker.kind), index] }.map(&:first)
        Preview.new(draft: draft, kind: draft.type, key: key, entry: entry, commentary: commentary, payload: payload,
                    thumbnail: thumbnail, notes: notes, guard: guard, blockers: ordered)
      end

      # ---------------------------------------------------------------------
      # Publish
      # ---------------------------------------------------------------------

      # Without `live` this is a rehearsal: the full preview and its blockers,
      # nothing sent, nothing written.
      def publish(draft, live: false, force: false)
        draft = Drafts.read(@config, draft.path)
        preview = preview(draft)
        blockers = force ? preview.blockers.reject { |b| FORCEABLE.include?(b.kind) } : preview.blockers

        unless live
          real = blockers.reject { |b| WAITING.include?(b.kind) }
          return Outcome.new(state: real.empty? ? :rehearsed : :blocked, draft: draft, key: preview.key,
                             messages: blockers.map(&:message), preview: preview)
        end

        # The post went out on an earlier run but the draft never learned it
        # (the run died between the ledger and the file). Finish that run.
        if blockers.map(&:kind) == [:already_published] && @config.publishable_statuses.include?(draft.status)
          urn = ledger.urn_for(preview.key)
          Drafts.set_status(draft, "published", "linkedin_urn" => urn)
          return Outcome.new(state: :skipped, draft: draft, key: preview.key, urn: urn, preview: preview,
                             messages: ["already published as #{urn}; marked #{draft.relative} published"])
        end
        return Outcome.new(state: :blocked, draft: draft, key: preview.key, messages: blockers.map(&:message), preview: preview) if blockers.any?

        send_post(draft, preview)
      rescue LinkedIn::Error, ConfigError, ArgumentError => e
        messages = [e.message]
        if preview&.key && ledger.unconfirmed(preview.key)
          messages << "LinkedIn did not confirm the post, so it may exist: #{@config.ledger} marks it unconfirmed and no run " \
                      "will send it again until a person checks (`zer0-cms linkedin record #{draft.id} URN`, or --force)"
        end
        Outcome.new(state: :failed, draft: draft, key: preview&.key, messages: messages, preview: preview)
      end

      # A live run publishes every draft this process may publish; a rehearsal
      # shows every draft the site accepts, so a laptop sees what CI will send.
      # `force` is for one named draft, never a queue.
      def publish_queue(live: false, force: false)
        raise ArgumentError, "--force applies to one draft: name it" if force

        statuses = live ? @config.publishable_statuses : @config.accept_statuses
        drafts.select { |d| d.status != "published" && statuses.include?(d.status) }
              .map { |d| publish(d, live: live) }
      end

      # A person found the post on LinkedIn — after an unconfirmed attempt, or
      # one made by hand — and records it as publishing would have.
      def record_post(draft, urn)
        raise ArgumentError, "not a post URN: #{urn.inspect}" unless urn.to_s.match?(/\Aurn:li:(share|ugcPost):\d+\z/)

        draft = Drafts.read(@config, draft.path)
        preview = preview(draft)
        raise ArgumentError, "#{draft.relative} has no ledger key: #{preview.blockers.first&.message}" unless preview.key
        raise ConfigError, "#{@config.ledger} is not valid JSON — fix it first" unless ledger.readable?

        ledger.record(preview.key, urn: urn, kind: draft.update? ? "update" : "article", author: @config.author,
                                   source_file: preview.entry&.relative, now: @clock.call)
        Drafts.set_status(draft, "published", "linkedin_urn" => urn)
        Outcome.new(state: :recorded, draft: draft, key: preview.key, urn: urn, preview: preview,
                    messages: ["recorded #{urn} for #{preview.key}"])
      end

      # ---------------------------------------------------------------------
      # Reads
      # ---------------------------------------------------------------------

      def posts(count: 10)
        with_client { |client| LinkedIn::Posts.by_author(client, author: @config.author, count: count) }
      end

      def verify(urn)
        with_client { |client| LinkedIn::Posts.get(client, urn) }
      end

      def organizations
        with_client do |client|
          pages = LinkedIn::Organizations.administered(client)
          pages&.each { |page| page.name = LinkedIn::Organizations.name(client, page.urn) }
        end
      end

      def statistics(write: false)
        result = Analytics.fetch(self)
        result[:path] = Analytics.write(@config, result[:performance], now: @clock.call) if write
        result
      end

      # Local state, and — with `check` — what LinkedIn says about the token.
      def status(check: false, warn_days: 7)
        queue = drafts
        report = {
          "site" => @config.root, "configured" => @config.configured?, "author" => @config.author,
          "author_type" => @config.author_type, "site_url" => @config.site_url, "api_version" => @config.api_version,
          "api_version_status" => LinkedIn.version_status(@config.api_version).to_s, "queue" => @config.queue,
          "ledger" => @config.ledger, "performance" => Analytics.relative_path(@config),
          "accept_statuses" => @config.accept_statuses, "publishable_statuses" => @config.publishable_statuses,
          "merged" => @config.merged?, "armed" => @config.publish_armed?,
          "credentials" => @credentials.present,
          "drafts" => Drafts::STATUSES.to_h { |s| [s, queue.count { |d| d.status == s }] },
          "published" => ledger.shares.size, "ledger_readable" => ledger.readable?,
          "errors" => @config.errors, "warnings" => @config.warnings
        }
        report["token"] = check_token(warn_days: warn_days) if check
        report
      end

      def check_token(warn_days: 7)
        return { "ok" => false, "problems" => ["no LinkedIn credential in the environment"] } unless @credentials.access? || @credentials.refresh?

        out = { "ok" => true, "problems" => [], "notes" => [] }
        if @credentials.client?
          info = oauth.introspect(current_token)
          out.merge!("active" => info.active, "status" => info.status, "scopes" => info.scopes,
                     "expires_at" => info.expires_at&.iso8601, "days_left" => info.days_left(@clock.call))
          out["problems"] << "the token is #{info.status.empty? ? "not active" : info.status}" unless info.active
          if info.days_left(@clock.call) && info.days_left(@clock.call) <= warn_days
            out["problems"] << "the token expires in #{info.days_left(@clock.call)} day(s)"
          end
        else
          out["notes"] << "no LINKEDIN_CLIENT_ID/SECRET: expiry cannot be read, only whether the token works"
        end
        probe(out)
        out["ok"] = out["problems"].empty?
        out
      rescue LinkedIn::Error => e
        { "ok" => false, "problems" => [e.message] }
      end

      # ---------------------------------------------------------------------
      # Clients
      # ---------------------------------------------------------------------

      # Yield a client; on a 401, refresh once (when the refresh credentials
      # exist) and run the block again. A 401 means LinkedIn did nothing, so
      # repeating the block cannot duplicate a write.
      def with_client
        yield client
      rescue LinkedIn::HTTPError => e
        raise unless e.unauthorized? && @credentials.refresh? && !@refreshed

        refresh_token!
        retry
      end

      def client
        refresh_token! if !@credentials.access? && @credentials.refresh? && !@refreshed
        LinkedIn::Client.new(token: current_token, api_version: @config.api_version, transport: @transport, sleeper: @sleeper,
                             secrets: [@credentials.refresh_token, @credentials.client_secret])
      end

      def oauth
        LinkedIn::OAuth.new(client_id: @credentials.client_id, client_secret: @credentials.client_secret,
                            transport: @transport, sleeper: @sleeper)
      end

      private

      def current_token
        @credentials.access_token.to_s
      end

      def refresh_token!
        token = oauth.refresh(refresh_token: @credentials.refresh_token, now: @clock.call)
        @credentials = @credentials.dup.tap { |c| c.access_token = token.access_token }
        @refreshed = true
        token
      end

      def probe(out)
        with_client do |c|
          if @config.author_type == "person"
            out["member"] = LinkedIn::OAuth.member(c)
          else
            LinkedIn::Posts.by_author(c, author: @config.author, count: 1)
          end
        end
        out["probe"] = "ok"
      rescue LinkedIn::HTTPError => e
        if e.forbidden?
          out["probe"] = "forbidden"
          out["notes"] << "the token authenticates but may not read #{@config.author}'s posts (#{e.message}); publishing may still work"
        else
          out["probe"] = "failed"
          out["problems"] << e.message
        end
      end

      def send_post(draft, preview)
        with_client do |client|
          image_urn = nil
          if preview.thumbnail
            begin
              image_urn = LinkedIn::Images.upload(client, owner: @config.author, path: preview.thumbnail, sleeper: @sleeper)
            rescue LinkedIn::Refused
              raise
            rescue LinkedIn::Error => e
              preview.notes << "thumbnail upload failed (#{e.message}); posting without a card image"
            end
          end
          payload = JSON.parse(JSON.generate(preview.payload))
          payload["content"]["article"]["thumbnail"] = image_urn if image_urn && payload.dig("content", "article")
          urn = create_or_mark_unconfirmed(client, draft, preview, payload)
          record(draft, preview, urn, image_urn)
        end
      end

      # A 5xx, a dropped connection or a 2xx without an id may mean the post
      # exists; so does nothing else (a refusal before a socket, a 4xx, a 429
      # LinkedIn sends before acting). Write the doubt down first, so neither
      # this run's retry-on-401 nor the next run can send the post again.
      def create_or_mark_unconfirmed(client, draft, preview, payload)
        LinkedIn::Posts.create(client, payload)
      rescue LinkedIn::Refused
        raise
      rescue LinkedIn::HTTPError => e
        mark_unconfirmed(draft, preview, e) if e.status.zero? || e.status >= 500
        raise
      rescue LinkedIn::Error => e
        mark_unconfirmed(draft, preview, e)
        raise
      end

      def mark_unconfirmed(draft, preview, error)
        ledger.mark_unconfirmed(preview.key, error: error.message, kind: draft.update? ? "update" : "article",
                                             author: @config.author, source_file: preview.entry&.relative, now: @clock.call)
      rescue StandardError
        nil
      end

      def record(draft, preview, urn, image_urn)
        ledger.record(preview.key, urn: urn, kind: draft.update? ? "update" : "article", author: @config.author,
                                   source_file: preview.entry&.relative, image_urn: image_urn, now: @clock.call)
        Drafts.set_status(draft, "published", "linkedin_urn" => urn)
        Outcome.new(state: :published, draft: draft, key: preview.key, urn: urn, preview: preview,
                    messages: preview.notes + ["published #{urn}", LinkedIn::Posts.feed_url(urn)])
      rescue StandardError => e
        # The post exists. Losing its URN is how the next run posts it again.
        Outcome.new(state: :failed, draft: draft, key: preview.key, urn: urn, preview: preview,
                    messages: ["PUBLISHED #{urn} but could not record it (#{e.message}). Add \"#{preview.key}\" => " \
                               "{\"linkedin_urn\": \"#{urn}\"} to #{@config.ledger} and set the draft's status to " \
                               "published before running again."])
      end

      def thumbnail_for(entry, notes)
        value = entry&.preview.to_s.strip
        unless value.empty? || value.match?(%r{\A[a-z][a-z0-9+.-]*://}i)
          relative = value.delete_prefix("/")
          found = [File.join(catalog.source.to_s, relative), File.join(catalog.source.to_s, "assets", relative),
                   File.join(@config.root, relative)].find { |path| File.file?(path) && inside_root?(path) }
          if found
            ok, reason = LinkedIn::Images.uploadable?(found)
            return found if ok

            notes << "preview image not uploadable: #{reason}"
          else
            notes << "preview image #{value} is not on disk"
          end
        end
        if @config.fallback_image
          fallback = @config.path(@config.fallback_image)
          ok, reason = LinkedIn::Images.uploadable?(fallback)
          if ok && inside_root?(fallback)
            notes << "using the fallback card image #{@config.fallback_image}"
            return fallback
          end

          notes << "fallback image not uploadable: #{reason || "outside the repository"}"
        end
        notes << "posting without a card image" if entry
        nil
      end

      def inside_root?(path)
        File.realpath(path).start_with?("#{@config.root}/")
      rescue SystemCallError
        false
      end
    end
  end
end
