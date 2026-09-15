# frozen_string_literal: true

require "minitest/autorun"
require "digest"
require "fileutils"
require "json"
require "stringio"
require "tmpdir"
require_relative "../../lib/zer0_cms/distribution"

# The distribution lane end to end, against a site built in a temp directory
# and a ScriptedTransport — no network, and an unscripted call fails the test.
class TestDistribution < Minitest::Test
  D = Zer0Cms::Distribution
  L = Zer0Cms::LinkedIn
  NOSLEEP = ->(_seconds) {}
  NOW = Time.utc(2026, 9, 14, 12, 0, 0)
  AUTHOR = "urn:li:organization:64517157"
  TOKEN = "tok-SECRET-123456"
  PNG = ["89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201a5f3b9a90000000049454e44ae426082"].pack("H*")
  MCP_POST = "pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md"
  MCP_URL = "https://example.test/posts/2026/07/06/mcp-for-the-back-office/"

  # --- fixtures -----------------------------------------------------------------

  def site(linkedin: {}, zer0: nil)
    Dir.mktmpdir do |dir|
      root = File.realpath(dir)
      write(root, "_config.yml", <<~YAML)
        title: Test
        url: &url https://example.test
        baseurl: ""
        collections_dir: pages
        permalink: pretty
        collections:
          posts:
            output: true
            permalink: /:collection/:year/:month/:day/:slug/
          docs:
            output: true
        defaults:
          - scope: { path: "pages/_docs/guides", type: docs }
            values: { permalink: "/guides/:name/" }
      YAML
      write(root, MCP_POST, <<~MD)
        ---
        title: MCP for the back office
        description: What the Model Context Protocol changes for the systems that close your books
        sub-title: A standard plug between the assistant your team uses and the systems your business runs on
        date: 2026-07-06T10:00:00.000Z
        tags: [mcp, ai, integration]
        preview: /images/previews/mcp-for-the-back-office.png
        ---
        Body.
      MD
      write(root, "pages/_posts/tech/2026-07-10-moved.md", "---\ntitle: Moved\ndescription: Somewhere else\npermalink: /news/moved-elsewhere/\n---\nx\n")
      write(root, "pages/_posts/2000-01-01-index.md", "---\ntitle: News\ndescription: All the news\npermalink: /news/\n---\n")
      write(root, "pages/_posts/tech/2026-08-01-not-yet.md", "---\ntitle: Not yet\ndescription: A draft\ndraft: true\n---\n")
      write(root, "pages/_docs/guides/setup.md", "---\ntitle: Setup\ndescription: How to set up\n---\n")
      write(root, "pages/_docs/intro.md", "---\ntitle: Intro\ndescription: Hello\n---\n")
      write(root, "about.md", "---\ntitle: About\ndescription: Us\n---\n")
      write(root, "assets/images/previews/mcp-for-the-back-office.png", PNG)
      block = { "author" => AUTHOR, "queue" => "drafts/linkedin", "ledger" => ".github/linkedin-log.json",
                "acceptStatuses" => ["approved"], "sources" => ["posts"] }.merge(linkedin)
      write(root, "zer0.json", JSON.generate(zer0 || { "distribution" => { "linkedin" => block } }))
      yield root
    end
  end

  def write(root, relative, content)
    path = File.join(root, relative)
    FileUtils.mkdir_p(File.dirname(path))
    File.binwrite(path, content)
    path
  end

  def credentials(**values)
    D::Credentials.new(**{ access_token: TOKEN, refresh_token: "", client_id: "", client_secret: "" }.merge(values))
  end

  def pipeline(root, env: {}, transport: L::ScriptedTransport.new, creds: credentials)
    D::Pipeline.new(D::Config.load(root, env: env), transport: transport, sleeper: NOSLEEP, clock: -> { NOW }, credentials: creds)
  end

  def armed
    { "ZER0_LINKEDIN_PUBLISH" => "1" }
  end

  def tree(root)
    Dir.glob("**/*", File::FNM_DOTMATCH, base: root).reject { |p| p.end_with?(".") }.sort.map do |path|
      full = File.join(root, path)
      [path, File.file?(full) ? Digest::SHA256.file(full).hexdigest : :dir]
    end
  end

  def script_publish(transport, urn: "urn:li:share:7000")
    transport.on("POST", "https://api.linkedin.com/rest/images?action=initializeUpload",
                 { "value" => { "uploadUrl" => "https://www.linkedin.com/dms-uploads/abc/0", "image" => "urn:li:image:IMG" } })
    transport.on("PUT", "https://www.linkedin.com/dms-uploads/", nil, status: 201)
    transport.on("GET", "https://api.linkedin.com/rest/images/", { "status" => "AVAILABLE" })
    transport.on("POST", "https://api.linkedin.com/rest/posts", nil, status: 201, headers: { "x-restli-id" => urn })
    transport
  end

  def approved_draft(pipe)
    draft = pipe.compose("tech/2026-07-06-mcp-for-the-back-office")
    assert_equal :approved, pipe.approve(draft).state
    pipe.draft(draft.id)
  end

  # --- Python json.dump parity ---------------------------------------------

  def test_ledger_bytes_match_python_json_dump
    data = {
      "https://bash-365.com/posts/2026/07/08/when-the-numbers/" => {
        "linkedin_urn" => "urn:li:share:7488646927748829184", "urn" => "urn:li:share:7488646927748829184",
        "posted_at" => "2026-07-30T17:29:20Z", "type" => "article", "source_file" => "pages/_posts/corp/x.md",
        "image_urn" => "urn:li:image:D5610AQEvxKjg_zaDpg", "target" => "linkedin"
      },
      "_meta" => { "b" => [1, 2.5, nil, true], "a" => {} }
    }
    expected = <<~JSON
      {
        "_meta": {
          "a": {},
          "b": [
            1,
            2.5,
            null,
            true
          ]
        },
        "https://bash-365.com/posts/2026/07/08/when-the-numbers/": {
          "image_urn": "urn:li:image:D5610AQEvxKjg_zaDpg",
          "linkedin_urn": "urn:li:share:7488646927748829184",
          "posted_at": "2026-07-30T17:29:20Z",
          "source_file": "pages/_posts/corp/x.md",
          "target": "linkedin",
          "type": "article",
          "urn": "urn:li:share:7488646927748829184"
        }
      }
    JSON
    assert_equal expected, D::Ledger.serialize(data)
  end

  def test_py_json_escapes_and_floats_match_python
    bs = "\\"
    value = { "caf\u{e9}" => "\u{7f} \u{1f680} \"q\" #{bs} \n\t\u{1}", "z" => [], "e" => 1e-05, "big" => 1e16, "f" => 5.0 }
    expected = [
      "{",
      '  "big": 1e+16,',
      "  \"caf#{bs}u00e9\": \"#{bs}u007f #{bs}ud83d#{bs}ude80 #{bs}\"q#{bs}\" #{bs}#{bs} #{bs}n#{bs}t#{bs}u0001\",",
      '  "e": 1e-05,',
      '  "f": 5.0,',
      '  "z": []',
      "}"
    ].join("\n")
    assert_equal expected, D::PyJson.dump(value, indent: 2, sort_keys: true)
    assert_equal "{\"caf\u{e9}\": \"\u{7f}\u{1f680}\"}", D::PyJson.dump({ "caf\u{e9}" => "\u{7f}\u{1f680}" }, ensure_ascii: false)
    assert_equal '{"a": [1, "two", true, null], "b": 1}', D::PyJson.dump({ "b" => 1, "a" => [1, "two", true, nil] }, sort_keys: true)
  end

  # --- config -----------------------------------------------------------------

  def test_config_layers_and_what_a_file_cannot_do
    site do |root|
      config = D::Config.load(root, env: {})
      assert_equal AUTHOR, config.author
      assert_equal "organization", config.author_type
      assert_equal "https://example.test", config.site_url
      assert_equal L::DEFAULT_API_VERSION, config.api_version
      assert_equal ["drafts/linkedin", ".github/linkedin-log.json"], [config.queue, config.ledger]
      assert_empty config.problems
      refute config.publish_armed?

      override = D::Config.load(root, env: { "LINKEDIN_ORG_URN" => "urn:li:organization:1", "LINKEDIN_API_VERSION" => "202607" })
      assert_equal ["urn:li:organization:1", "202607"], [override.author, override.api_version]
      assert D::Config.load(root, env: armed).publish_armed?
    end
  end

  def test_a_file_cannot_arm_publishing
    site(linkedin: { "publishAllow" => true, "armed" => true }) do |root|
      config = D::Config.load(root, env: {})
      refute config.publish_armed?
      assert config.warnings.any? { |w| w.include?("publishAllow is not a setting") }
    end
  end

  def test_config_falls_back_to_config_yml_and_refuses_paths_outside_the_repository
    site(zer0: {}) do |root|
      File.write(File.join(root, "_config.yml"), "#{File.read(File.join(root, "_config.yml"))}linkedin:\n  org_urn: \"urn:li:organization:42\"\n")
      config = D::Config.load(root, env: {})
      refute config.configured?
      assert_equal "urn:li:organization:42", config.author
      assert_equal ".zer0/drafts/linkedin", config.queue
      assert_equal ["approved"], config.accept_statuses
    end
    site(linkedin: { "queue" => "../elsewhere" }) { |root| assert_raises(D::ConfigError) { D::Config.load(root, env: {}) } }
    site(linkedin: { "ledger" => "/etc/ledger.json" }) { |root| assert_raises(D::ConfigError) { D::Config.load(root, env: {}) } }
  end

  def test_config_errors
    site(linkedin: { "author" => "urn:li:company:5", "apiVersion" => "202401", "acceptStatuses" => ["published"] }) do |root|
      errors = D::Config.load(root, env: {}).errors.join("\n")
      assert_includes errors, "author must be"
      assert_includes errors, "support window"
      assert_includes errors, "acceptStatuses may hold pending and approved"
    end
  end

  # --- ledger -------------------------------------------------------------------

  def test_the_ledger_reads_either_urn_name_and_writes_both
    Dir.mktmpdir do |dir|
      path = File.join(dir, "log.json")
      File.write(path, JSON.generate("https://a.test/x/" => { "linkedin_urn" => "urn:li:share:1" }, "_token" => { "expires_at" => "z" },
                                     "https://a.test/y/" => { "type" => "article" }, "_schema" => 2))
      ledger = D::Ledger.new(path)
      assert_equal "urn:li:share:1", ledger.urn_for("https://a.test/x/")
      refute ledger.published?("https://a.test/y/")
      assert_equal ["https://a.test/x/"], ledger.shares.map(&:first)

      ledger.record("https://a.test/z/", urn: "urn:li:share:2", kind: "article", author: AUTHOR, source_file: "p.md", now: NOW)
      entry = JSON.parse(File.read(path))["https://a.test/z/"]
      assert_equal({ "linkedin_urn" => "urn:li:share:2", "urn" => "urn:li:share:2", "posted_at" => "2026-09-14T12:00:00Z",
                     "target" => "linkedin", "type" => "article", "author" => AUTHOR, "source_file" => "p.md" }, entry)
      assert_equal D::Ledger.serialize(JSON.parse(File.read(path))), File.read(path), "the file is python-formatted"
      assert JSON.parse(File.read(path)).key?("_token"), "other lanes' metadata survives a rewrite"
      assert_equal 2, JSON.parse(File.read(path))["_schema"], "so does a key that is not an object"
    end
  end

  def test_an_unreadable_ledger_is_never_read_as_empty_or_rewritten
    Dir.mktmpdir do |dir|
      path = File.join(dir, "log.json")
      File.write(path, "{ not json")
      ledger = D::Ledger.new(path)
      refute ledger.readable?
      assert_raises(D::ConfigError) { ledger.record("https://a.test/", urn: "urn:li:share:1", kind: "article") }
      assert_equal "{ not json", File.read(path)
    end
  end

  def test_concurrent_records_keep_every_entry
    Dir.mktmpdir do |dir|
      ledger = D::Ledger.new(File.join(dir, "log.json"))
      10.times.map { |i| Thread.new { ledger.record("https://a.test/#{i}/", urn: "urn:li:share:#{i}", kind: "article") } }.each(&:join)
      assert_equal 10, ledger.shares.size
    end
  end

  # --- drafts -------------------------------------------------------------------

  def test_a_new_draft_is_always_pending_and_never_overwrites
    site do |root|
      config = D::Config.load(root, env: {})
      first = D::Drafts.create(config, type: "article", slug: "2026-09-14-hello", body: "Commentary.\n",
                                       meta: { "status" => "approved", "source" => MCP_POST, "title" => "Hello: world" })
      assert_equal "pending", first.status
      assert_equal "---\ntype: article\nstatus: pending\nsource: #{MCP_POST}\ntitle: \"Hello: world\"\n---\n\nCommentary.\n", File.read(first.path)
      second = D::Drafts.create(config, type: "update", slug: "2026-09-14-hello", body: "Text")
      assert_equal "drafts/linkedin/2026-09-14-hello-2.md", second.relative
      assert_raises(ArgumentError) { D::Drafts.create(config, type: "article", slug: "../escape", body: "x") }
    end
  end

  def test_the_queue_skips_readmes_and_nested_folders_and_status_changes_one_line
    site do |root|
      config = D::Config.load(root, env: {})
      write(root, "drafts/linkedin/README.md", "# The queue\n")
      write(root, "drafts/linkedin/examples/2026-01-01-example.md", "---\nstatus: pending\n---\nx\n")
      path = write(root, "drafts/linkedin/2026-01-02-b.md", "---\n# reviewer: amr\ntype: text\nstatus: pending\nsource: x\n---\nBody status: ok\n")
      assert_equal ["2026-01-02-b"], D::Drafts.list(config).map(&:id)
      draft = D::Drafts.find!(config, "2026-01-02-b.md")
      assert_equal "update", draft.type
      D::Drafts.set_status(draft, "published", "linkedin_urn" => "urn:li:share:9")
      assert_equal "---\n# reviewer: amr\ntype: text\nstatus: published\nsource: x\nlinkedin_urn: urn:li:share:9\n---\nBody status: ok\n", File.read(path)
      assert_nil D::Drafts.find(config, "../../zer0.json"), "a reference is reduced to a name inside the queue"
      assert_raises(ArgumentError) { D::Drafts.find(config, "..") }
    end
  end

  # --- guard (the extension's cases) -------------------------------------------

  def test_guard_rule_tables_and_a_clean_string
    assert_equal [13, 9, 140, 3000], [D::Guard::BANNED.size, D::Guard::FILLER.size, D::Guard::FOLD, D::Guard::MAX_LEN]
    findings = D::Guard.check("A short, plain sentence that says a real thing and then stops.")
    assert_equal ["info"], findings.map(&:level)
    assert_match(/\Afold at 140 chars: /, findings.first.message)
  end

  def test_all_thirteen_bans_fire_under_their_own_names
    samples = [
      ["cutting-edge", "The cutting edge release lands on Thursday for everyone."],
      ["next-generation", "A next-generation approach to the same filing problem."],
      ["disruptive", "They describe the pricing model as disruptive, which it is not."],
      ["revolutionary", "A revolutionary way to keep the same three spreadsheets."],
      ["in today's ... world/age/era", "In today's connected world the invoices still need chasing."],
      ["leverage synergies", "We leverage synergies across the two back-office teams."],
      ["unlock value", "The migration will unlock value for the finance team."],
      ["best-of-breed", "A best of breed stack assembled from four vendors."],
      ["world-class", "A world class support desk answering in under a minute."],
      ["solutioning", "Half the meeting was solutioning rather than deciding."],
      ["ideate", "The workshop asked us to ideate before lunch."],
      ["circle back", "Let us circle back once the numbers are in."],
      ["low-hanging fruit", "Start with the low hanging fruit and measure it."]
    ]
    samples.each do |name, sample|
      assert D::Guard.check(sample).any? { |f| f.error? && f.message.end_with?("(#{name})") }, sample
    end
    assert D::Guard.check("In today’s connected landscape the invoices still need chasing.").any?(&:error?)
  end

  def test_guard_dedupe_exclamation_length_and_hook_match_the_extension
    both = D::Guard.check("We leverage synergies across the estate to make the numbers work.")
    assert_equal %w[error warning info], both.map(&:level)
    assert_equal "reads as filler: synergy", both[1].message
    assert_equal %w[error info], D::Guard.check("Our cutting-edge platform is here for the whole operations group.").map(&:level)
    assert_equal %w[warning info], D::Guard.check("This is a fine sentence about the work, and it has energy!").map(&:level)
    assert_equal 1, D::Guard.check("Really!! Truly!!! A sentence that goes on for a while afterwards.").count { |f| f.message.include?("exclamation") }
    assert_equal "commentary is 3001 chars (max 3000)", D::Guard.check("x" * 3001).first.message
    refute D::Guard.check("x" * 3000).any?(&:error?)
    assert D::Guard.check("Short.\nThen a much longer second line that explains the thing at hand.").any? { |f| f.message.start_with?("weak hook") }
    refute D::Guard.check("A first line long enough to have actually said something before it ends.\nThen more.").any? { |f| f.message.start_with?("weak hook") }
  end

  def test_a_patterns_file_adds_rules_and_a_broken_one_degrades_to_none
    site(linkedin: { "bannedPatternsFile" => "brand/bans.json" }) do |root|
      write(root, "brand/bans.json", '[{ "name": "synergize", "pattern": "\\\\bsynergi[sz]e\\\\b", "flags": "i" }]')
      config = D::Config.load(root, env: {})
      assert D::Guard.check("We Synergize.", extra: D::Guard.patterns_for(config)).any? { |f| f.message.end_with?("(synergize)") }
      write(root, "brand/bans.json", '[{ "name": "broken", "pattern": "(" }]')
      assert_equal [], D::Guard.patterns_for(config)
    end
  end

  # --- permalinks and sources ---------------------------------------------------

  def test_permalinks_follow_jekyll
    site do |root|
      pipe = pipeline(root)
      urls = pipe.catalog.entries.to_h { |e| [e.relative, D::Permalink.path_for(pipe.catalog.config, e)] }
      assert_equal "/posts/2026/07/06/mcp-for-the-back-office/", urls[MCP_POST]
      assert_equal "/news/moved-elsewhere/", urls["pages/_posts/tech/2026-07-10-moved.md"]
      assert_equal "/news/", urls["pages/_posts/2000-01-01-index.md"]
      assert_equal "/guides/setup/", urls["pages/_docs/guides/setup.md"], "a front-matter default"
      assert_equal "/docs/intro.html", urls["pages/_docs/intro.md"], "the collection default"
      assert_equal "/about/", urls["about.md"], "a page under permalink: pretty"
      assert_equal "the-value-of-x", D::Permalink.slugify("The Value of  X!")
      assert_equal "hello-wörld", D::Permalink.slugify("Hello Wörld")
    end
  end

  def test_sources_are_live_titled_non_structural_pages_in_the_configured_collections
    site do |root|
      pipe = pipeline(root)
      assert_equal ["pages/_posts/tech/2026-07-10-moved.md", MCP_POST].sort, pipe.sources.map { |s| s.entry.relative }.sort
      assert_equal MCP_URL, pipe.sources.find { |s| s.entry.relative == MCP_POST }.url
      %w[tech/2026-07-06-mcp-for-the-back-office pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md mcp-for-the-back-office].each do |ref|
        assert_equal MCP_POST, pipe.resolve_source(ref)&.relative, ref
      end
      assert_nil pipe.resolve_source("https://elsewhere.test/")
    end
  end

  def test_the_default_commentary_is_the_python_lanes
    assert_equal "#MCP #BackOffice #AI", D::Composer.hashtags(["mcp", "back-office", "ai", "extra"])
    site do |root|
      entry = pipeline(root).resolve_source(MCP_POST)
      assert_equal "A standard plug between the assistant your team uses and the systems your business runs on\n\n#MCP #AI #Integration",
                   D::Composer.default_commentary(entry)
    end
  end

  # --- preview, approve, publish --------------------------------------------------

  def test_preview_is_the_exact_payload_and_touches_nothing
    site do |root|
      pipe = pipeline(root)
      draft = pipe.compose("tech/2026-07-06-mcp-for-the-back-office")
      assert_equal "drafts/linkedin/2026-09-14-mcp-for-the-back-office.md", draft.relative
      before = tree(root)
      transport = L::ScriptedTransport.new
      preview = pipeline(root, transport: transport, creds: credentials(access_token: "")).preview(draft)
      assert_equal before, tree(root)
      assert_empty transport.requests

      assert_equal MCP_URL, preview.key
      assert_equal File.join(root, "assets/images/previews/mcp-for-the-back-office.png"), preview.thumbnail
      article = preview.payload["content"]["article"]
      assert_equal [MCP_URL, "MCP for the back office"], [article["source"], article["title"]]
      assert_equal %i[status_not_accepted publish_disabled no_credential], preview.blockers.map(&:kind)
      assert preview.blocked?(live: false), "a pending draft is blocked whatever arming says"
      assert_empty preview.problems, "but it is waiting for approval, not broken"
    end
  end

  def test_approval_is_pending_only_and_the_guard_can_refuse_it
    site do |root|
      pipe = pipeline(root)
      draft = pipe.compose(MCP_POST)
      assert_equal :approved, pipe.approve(draft).state
      assert_equal "approved", pipe.draft(draft.id).status
      assert_equal ["draft is already approved"], pipe.approve(pipe.draft(draft.id)).messages
      bad = pipe.compose_update("Our world-class team.", slug: "bad")
      assert_equal :blocked, pipe.approve(bad).state
      assert_equal "pending", pipe.draft(bad.id).status
    end
  end

  def test_a_rehearsal_and_an_unarmed_live_run_send_nothing
    site do |root|
      transport = L::ScriptedTransport.new
      draft = approved_draft(pipeline(root))
      before = tree(root)
      assert_equal :rehearsed, pipeline(root, transport: transport).publish(draft).state
      outcome = pipeline(root, transport: transport).publish(draft, live: true)
      assert_equal :blocked, outcome.state
      assert_includes outcome.messages.join, "not armed"
      assert_empty transport.requests
      assert_equal before, tree(root)
    end
  end

  def test_a_live_armed_publish_uploads_posts_records_and_marks_the_draft
    site do |root|
      transport = script_publish(L::ScriptedTransport.new)
      draft = approved_draft(pipeline(root))
      outcome = pipeline(root, env: armed, transport: transport).publish(draft, live: true)
      assert_equal :published, outcome.state, outcome.messages.inspect
      assert_equal "urn:li:share:7000", outcome.urn
      assert_equal %w[POST PUT GET POST], transport.requests.map(&:verb)

      payload = transport.requests.last.json
      assert_equal "urn:li:image:IMG", payload["content"]["article"]["thumbnail"]
      assert_equal AUTHOR, payload["author"]
      assert_equal "A standard plug between the assistant your team uses and the systems your business runs on\n\n#MCP #AI #Integration",
                   payload["commentary"]

      entry = JSON.parse(File.read(File.join(root, ".github/linkedin-log.json")))[MCP_URL]
      assert_equal %w[urn:li:share:7000 urn:li:share:7000 pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md urn:li:image:IMG],
                   entry.values_at("linkedin_urn", "urn", "source_file", "image_urn")
      published = pipeline(root).draft(draft.id)
      assert_equal ["published", "urn:li:share:7000"], [published.status, published.meta["linkedin_urn"]]

      again = pipeline(root, env: armed, transport: transport).publish(published, live: true)
      assert_equal :blocked, again.state
      assert_equal 4, transport.requests.size, "a published draft never posts twice"
      assert_raises(ArgumentError) { pipeline(root).compose(MCP_POST) }
    end
  end

  def test_a_run_that_died_after_the_ledger_is_finished_not_repeated
    site do |root|
      draft = approved_draft(pipeline(root))
      D::Ledger.new(File.join(root, ".github/linkedin-log.json")).record(MCP_URL, urn: "urn:li:share:55", kind: "article")
      transport = L::ScriptedTransport.new
      outcome = pipeline(root, env: armed, transport: transport).publish(draft, live: true)
      assert_equal [:skipped, "urn:li:share:55"], [outcome.state, outcome.urn]
      assert_empty transport.requests
      assert_equal "published", pipeline(root).draft(draft.id).status
    end
  end

  def test_an_unconfirmed_create_blocks_every_later_run_until_a_person_looks
    site do |root|
      transport = L::ScriptedTransport.new.on("POST", "https://api.linkedin.com/rest/posts", { "message" => "down" }, status: 503)
      pipe = pipeline(root)
      draft = pipe.compose(MCP_POST)
      D::Drafts.set_status(draft, "approved", "no_thumbnail" => true)
      outcome = pipeline(root, env: armed, transport: transport).publish(pipe.draft(draft.id), live: true)
      assert_equal :failed, outcome.state
      assert_includes outcome.messages.join, "HTTP 503"
      assert_includes outcome.messages.join, "may exist"
      assert_equal 1, transport.requests.size
      ledger = D::Ledger.new(File.join(root, ".github/linkedin-log.json"))
      refute ledger.published?(MCP_URL)
      assert_equal "unconfirmed", ledger.unconfirmed(MCP_URL)["state"]
      assert_equal "approved", pipe.draft(draft.id).status

      again = pipeline(root, env: armed, transport: transport).publish(pipe.draft(draft.id), live: true)
      assert_equal [:blocked, 1], [again.state, transport.requests.size]
      assert_includes again.messages.join, "may have posted"
      queue = pipeline(root, env: armed, transport: transport).publish_queue(live: true)
      assert_equal [:blocked], queue.map(&:state)
      assert_equal 1, transport.requests.size, "no run sends an unconfirmed post again"

      recorded = pipeline(root).record_post(pipe.draft(draft.id), "urn:li:share:42")
      assert_equal :recorded, recorded.state
      assert_equal "urn:li:share:42", ledger.urn_for(MCP_URL)
      assert_nil ledger.unconfirmed(MCP_URL)
      assert_equal "published", pipe.draft(draft.id).status
    end
  end

  def test_a_success_without_a_post_id_is_unconfirmed_and_force_lifts_it
    site do |root|
      pipe = pipeline(root)
      draft = pipe.compose(MCP_POST)
      D::Drafts.set_status(draft, "approved", "no_thumbnail" => true)
      no_id = L::ScriptedTransport.new.on("POST", "https://api.linkedin.com/rest/posts", nil, status: 201)
      assert_equal :failed, pipeline(root, env: armed, transport: no_id).publish(pipe.draft(draft.id), live: true).state
      assert D::Ledger.new(File.join(root, ".github/linkedin-log.json")).unconfirmed(MCP_URL)

      rejected = L::ScriptedTransport.new.on("POST", "https://api.linkedin.com/rest/posts", { "message" => "bad" }, status: 422)
      assert_equal :failed, pipeline(root, env: armed, transport: rejected).publish(pipe.draft(draft.id), live: true, force: true).state
      assert_equal 1, rejected.requests.size, "force lifts the unconfirmed gate for a person who checked"
      assert_raises(ArgumentError) { pipeline(root, env: armed, transport: rejected).publish_queue(live: true, force: true) }
    end
  end

  def test_pending_publishes_only_as_a_merged_draft
    site(linkedin: { "acceptStatuses" => %w[pending approved] }) do |root|
      draft = pipeline(root).compose(MCP_POST)
      local = pipeline(root, env: armed).preview(draft).blockers.find { |b| b.kind == :status_not_accepted }
      assert_includes local.message, "merged"
      merged = pipeline(root, env: armed.merge("ZER0_LINKEDIN_MERGED" => "1")).preview(draft)
      refute_includes merged.blockers.map(&:kind), :status_not_accepted
      assert_equal %w[approved], D::Config.load(root, env: {}).publishable_statuses
      assert_equal 1, pipeline(root, env: armed).publish_queue.size, "a rehearsal still shows what CI would send"
      assert_empty pipeline(root, env: armed).publish_queue(live: true), "a live run here sends nothing pending"
    end
  end

  def test_a_401_refreshes_once_and_repeats
    site do |root|
      transport = L::ScriptedTransport.new
      transport.on("POST", "https://www.linkedin.com/oauth/v2/accessToken", { "access_token" => "new-token-123456", "expires_in" => 5_184_000 })
      transport.on("POST", "https://api.linkedin.com/rest/posts", lambda do |request|
        if request.headers["Authorization"] == "Bearer new-token-123456"
          L::Response.new(status: 201, headers: { "x-restli-id" => "urn:li:share:8" }, body: "")
        else
          L::Response.new(status: 401, headers: {}, body: '{"message":"expired"}')
        end
      end)
      pipe = pipeline(root)
      draft = pipe.compose_update("A plain update that says a real thing.", slug: "note")
      D::Drafts.set_status(draft, "approved")
      creds = credentials(access_token: "old-token-123456", refresh_token: "RT-123456789", client_id: "cid", client_secret: "csecret-abcdef")
      outcome = pipeline(root, env: armed, transport: transport, creds: creds).publish(pipe.draft(draft.id), live: true)
      assert_equal [:published, "urn:li:share:8"], [outcome.state, outcome.urn]
      assert_equal ["POST posts", "POST accessToken", "POST posts"], transport.requests.map { |r| "#{r.verb} #{r.url.split("/").last}" }
      assert_equal "refresh_token", transport.requests[1].form["grant_type"]
      assert D::Ledger.new(File.join(root, ".github/linkedin-log.json")).published?("draft:drafts/linkedin/2026-09-14-note.md")
    end
  end

  def test_force_lifts_the_guard_but_never_the_approval_or_arming_gates
    site do |root|
      transport = L::ScriptedTransport.new.on("POST", "https://api.linkedin.com/rest/posts", nil, status: 201,
                                                                                               headers: { "x-restli-id" => "urn:li:share:3" })
      pipe = pipeline(root)
      draft = pipe.compose_update("Our world-class desk.", slug: "loud")
      assert_equal :blocked, pipeline(root, env: armed, transport: transport).publish(draft, live: true, force: true).state
      D::Drafts.set_status(draft, "approved")
      assert_equal :blocked, pipeline(root, transport: transport).publish(pipe.draft(draft.id), live: true, force: true).state
      assert_empty transport.requests
      assert_equal :blocked, pipeline(root, env: armed, transport: transport).publish(pipe.draft(draft.id), live: true).state
      assert_equal :published, pipeline(root, env: armed, transport: transport).publish(pipe.draft(draft.id), live: true, force: true).state
    end
  end

  def test_an_unreadable_ledger_blocks_publishing
    site do |root|
      draft = approved_draft(pipeline(root))
      write(root, ".github/linkedin-log.json", "{ broken")
      preview = pipeline(root, env: armed).preview(draft)
      assert_includes preview.blockers.map(&:kind), :ledger_unreadable
    end
  end

  # --- analytics ------------------------------------------------------------------

  def test_statistics_join_onto_content_paths_and_merge_into_performance_json
    site do |root|
      ledger = D::Ledger.new(File.join(root, ".github/linkedin-log.json"))
      ledger.record(MCP_URL, urn: "urn:li:share:1", kind: "article", source_file: MCP_POST, author: AUTHOR)
      ledger.record("https://example.test/other/", urn: "urn:li:share:2", kind: "article", source_file: "x.md", author: "urn:li:organization:9")
      write(root, ".cms/distribution/performance.json", JSON.generate("content" => { "old.md" => { "impressions" => 1 } }))
      transport = L::ScriptedTransport.new.on("GET", "https://api.linkedin.com/rest/organizationalEntityShareStatistics?", { "elements" => [
        { "share" => "urn:li:share:1", "totalShareStatistics" => { "impressionCount" => 90, "clickCount" => 4, "likeCount" => 5, "commentCount" => 1, "shareCount" => 0 } }
      ] })
      result = pipeline(root, transport: transport).statistics(write: true)
      assert_equal({ MCP_POST => { "impressions" => 90, "clicks" => 4, "reactions" => 5, "comments" => 1, "shares" => 0, "engagements" => 6 } },
                   result[:performance])
      assert_equal ["https://example.test/other/"], result[:skipped], "another author's post is not read as this author's"
      text = File.read(File.join(root, ".cms/distribution/performance.json"))
      data = JSON.parse(text)
      assert_equal %w[generated_at note content], data.keys
      assert_equal ["old.md", MCP_POST].sort, data["content"].keys
      assert_equal "Aggregate statistics for the author's own content. No per-reader data.", data["note"]
    end
  end

  # --- CLI ---------------------------------------------------------------------------

  def cli(args, env: {}, transport: L::ScriptedTransport.new)
    out = StringIO.new
    err = StringIO.new
    code = D::CLI.main(args, out: out, err: err, env: env, transport: transport)
    [code, out.string, err.string]
  end

  def test_cli_walks_the_governed_path
    site do |root|
      code, out, = cli(["draft", "tech/2026-07-06-mcp-for-the-back-office", "--site", root])
      assert_equal 0, code
      assert_includes out, "status: pending"
      id = D::Drafts.list(D::Config.load(root, env: {})).first.id
      assert_match(/\A\d{4}-\d{2}-\d{2}-mcp-for-the-back-office\z/, id, "the CLI dates a draft with the real clock")

      assert_equal 0, cli(["preview", id, "--site", root]).first, "a pending draft is waiting, not broken"
      assert_equal 1, cli(["publish", "--site", root, "--force"]).first, "--force needs a draft"
      assert_equal 0, cli(["approve", id, "--site", root]).first
      assert_equal 0, cli(["preview", "--site", root]).first
      code, out, = cli(["publish", "--site", root])
      assert_equal 0, code
      assert_includes out, "REHEARSED"
      code, out, = cli(["publish", "--site", root, "--live"])
      assert_equal 1, code
      assert_includes out, "not armed"

      code, out, = cli(["status", "--site", root, "--json"])
      report = JSON.parse(out)
      assert_equal [0, 1, false], [code, report["drafts"]["approved"], report["armed"]]
      refute_includes out, TOKEN
    end
  end

  def test_cli_plan_usage_and_errors
    code, out, = cli(["plan"])
    assert_equal 0, code
    assert_includes out, "returns   aggregate counts for the member's own post"
    assert_equal 2, cli(["frobnicate"]).first
    assert_equal 0, cli(["--help"]).first
    site { |root| assert_equal 1, cli(["approve", "missing", "--site", root]).first }
  end

  # --- MCP -----------------------------------------------------------------------------

  def test_mcp_lists_tools_previews_and_keeps_publish_off
    site do |root|
      draft = approved_draft(pipeline(root))
      lines = [
        { "jsonrpc" => "2.0", "id" => 1, "method" => "initialize", "params" => { "protocolVersion" => "2025-03-26" } },
        { "jsonrpc" => "2.0", "method" => "notifications/initialized" },
        { "jsonrpc" => "2.0", "id" => 2, "method" => "tools/list" },
        { "jsonrpc" => "2.0", "id" => 3, "method" => "tools/call", "params" => { "name" => "linkedin_preview", "arguments" => { "draft" => draft.id } } },
        { "jsonrpc" => "2.0", "id" => 4, "method" => "tools/call", "params" => { "name" => "linkedin_publish", "arguments" => { "draft" => draft.id, "confirm" => true } } },
        { "jsonrpc" => "2.0", "id" => 5, "method" => "nope" }
      ].map { |m| JSON.generate(m) }
      output = StringIO.new
      transport = L::ScriptedTransport.new
      D::Mcp.new(root, env: armed, transport: transport, input: StringIO.new("#{lines.join("\n")}\nnot json\n"), output: output).run
      responses = output.string.lines.map { |line| JSON.parse(line) }

      assert_equal [1, 2, 3, 4, 5, nil], responses.map { |r| r["id"] }
      assert_equal "2025-03-26", responses[0]["result"]["protocolVersion"]
      names = responses[1]["result"]["tools"].map { |t| t["name"] }
      assert_includes names, "linkedin_publish"
      refute names.any? { |n| n.include?("approve") }, "approval is not a tool"
      preview = JSON.parse(responses[2]["result"]["content"].first["text"])
      assert_equal MCP_URL, preview["key"]
      assert_equal true, responses[3]["result"]["isError"]
      assert_includes responses[3]["result"]["content"].first["text"], "ZER0_LINKEDIN_MCP_PUBLISH"
      assert_equal(-32_601, responses[4]["error"]["code"])
      assert_equal(-32_700, responses[5]["error"]["code"])
      assert_empty transport.requests
    end
  end

  def test_the_oauth_callback_request_line
    assert_equal({ "code" => "abc", "state" => "s1" }, D::Callback.parse_request_line("GET /callback?code=abc&state=s1 HTTP/1.1\r\n"))
    assert_nil D::Callback.parse_request_line("GET /favicon.ico HTTP/1.1\r\n")
    assert_nil D::Callback.parse_request_line("POST /callback?code=abc HTTP/1.1\r\n")
  end
end
