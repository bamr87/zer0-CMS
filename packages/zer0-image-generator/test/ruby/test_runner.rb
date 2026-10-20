# frozen_string_literal: true

# Runner orchestration tests: the review loop's one-regeneration cap, stats
# accounting, dry-run writing nothing, --list-missing output shape, idempotent
# skipping, discover() ordering (differential vs pathlib.rglob), and
# thread-safety of the per-file RunContext copy under parallel workers.
#
#     ruby -Ilib test/ruby/test_runner.rb

require "minitest/autorun"
require "stringio"
require "tmpdir"
require "pathname"

require "zer0_image_generator/runner"
require_relative "fakes"

module RunnerHelpers
  # A sink that records everything for assertions instead of printing.
  class CaptureSink
    attr_reader :logs, :lines, :headers

    def initialize
      @logs = []
      @lines = []
      @headers = []
      @lock = Mutex.new
    end

    def log(message, level)
      @lock.synchronize { @logs << [level, message] }
    end

    def say(text)
      @lock.synchronize { @lines << text }
    end

    def header(title)
      @lock.synchronize { @headers << title }
    end

    def all_text
      (@logs.map { |_l, m| m } + @lines).join("\n")
    end
  end

  def capture_logger
    Zer0ImageGenerator::Logger.new(sink: CaptureSink.new)
  end

  def build_runner(settings, deps, root, ctx: nil, logger: nil, interrupt: nil)
    Zer0ImageGenerator::Runner.new(
      settings, root,
      ctx: ctx || Fakes::Ctx.new,
      deps: deps,
      logger: logger || capture_logger,
      interrupt: interrupt
    )
  end
end

class TestRunnerReviewLoop < Minitest::Test
  include RunnerHelpers

  # Drives Runner.process_file with a mocked renderer + reviewer, returning the
  # prompts seen, the stats, and the final on-disk PNG bytes. Ports
  # test/test_preview_generator.py::TestRunnerReviewLoop.
  def run_loop(review_replies, generate_results)
    Dir.mktmpdir do |tmp|
      root = Pathname.new(tmp)
      (root / "assets" / "images" / "previews").mkpath
      post = root / "post.md"
      post.write("---\ntitle: Test Post\ndescription: D\n---\nBody\n")

      settings = Fakes.settings(provider: "openai", prompt_engine: "template",
                                review_engine: "claude", parallel: 1)
      cf = Fakes::ContentFile.new(path: post, title: "Test Post", description: "D",
                                  categories: "", preview: nil, author: nil,
                                  content: "Body", front_matter: {})

      prompts = []
      prov = Fakes::Provider.new(name: "openai") do |prompt, _fs, out_base, _fctx|
        prompts << prompt
        ok = generate_results[prompts.length - 1]
        if ok
          png = out_base.sub_ext(".png")
          png.binwrite(Fakes::PNG_SIGNATURE + prompt.b)
          Fakes::ImageResult.new(ok: true, kind: "png", path: png)
        else
          Fakes::ImageResult.new(ok: false, error: "render failed")
        end
      end

      deps = Fakes::Deps.new(providers: { "openai" => prov })
      deps.stub_parse(post, cf)
      deps.review_replies = review_replies.dup

      runner = build_runner(settings, deps, root)
      runner.process_file(post)

      png = root / "assets" / "images" / "previews" / "test-post.png"
      content = png.exist? ? png.binread : "".b
      [prompts, runner.stats, content]
    end
  end

  def test_approved_image_generates_once
    prompts, stats, _ = run_loop([[true, "fine", ""]], [true])
    assert_equal 1, prompts.length
    assert_equal 1, stats.generated
    assert_equal 0, stats.errors
  end

  def test_revision_regenerates_with_claude_prompt
    prompts, stats, content = run_loop([[false, "wrong subject", "REVISED BRIEF"]], [true, true])
    assert_equal 2, prompts.length
    assert_equal "REVISED BRIEF", prompts[1]
    assert_includes content, "REVISED BRIEF".b # second render kept
    assert_equal 1, stats.generated
  end

  def test_failed_revision_keeps_first_image
    prompts, stats, content = run_loop([[false, "meh", "REVISED BRIEF"]], [true, false])
    assert_equal 2, prompts.length
    refute_includes content, "REVISED BRIEF".b # first render kept
    assert_equal 1, stats.generated
    assert_equal 0, stats.errors
  end

  def test_review_never_regenerates_twice
    # The cost cap: even a rejecting review only ever triggers ONE retry.
    # A second scripted reply must go untouched.
    prompts, _stats, _ = run_loop(
      [[false, "no", "SECOND"], [false, "still no", "THIRD"]], [true, true]
    )
    assert_equal 2, prompts.length # not 3
    refute_includes prompts, "THIRD"
  end
end

class TestStatsAccounting < Minitest::Test
  include RunnerHelpers

  def cf(path, title, preview: nil)
    Fakes::ContentFile.new(path: path, title: title, description: "", categories: "",
                           preview: preview, author: nil, content: "", front_matter: {})
  end

  def test_skips_are_counted_and_summarized
    Dir.mktmpdir do |tmp|
      root = Pathname.new(tmp)
      coll = root / "_posts"
      coll.mkpath
      a = coll / "a.md"
      b = coll / "b.md"
      a.write("---\ntitle: A\npreview: /x/a.png\n---\n")
      b.write("---\ntitle: B\npreview: /x/b.png\n---\n")

      settings = Fakes.settings(provider: "local", collection: "posts",
                                collections: ["posts"], parallel: 1)
      deps = Fakes::Deps.new(providers: { "local" => Fakes::Provider.new(name: "local") { nil } })
      deps.stub_parse(a, cf(a, "A", preview: "/x/a.png"))
      deps.stub_parse(b, cf(b, "B", preview: "/x/b.png"))
      deps.preview_exists = true # both previews already valid → skipped

      logger = capture_logger
      runner = build_runner(settings, deps, root, logger: logger)
      code = runner.run

      assert_equal 0, code
      assert_equal 2, runner.stats.skipped
      assert_equal 2, runner.stats.processed
      # CI greps this exact line.
      assert_includes logger.sink.lines, "  Files skipped: 2"
    end
  end

  def test_no_front_matter_counts_as_skip
    Dir.mktmpdir do |tmp|
      root = Pathname.new(tmp)
      post = root / "p.md"
      post.write("no front matter\n")
      settings = Fakes.settings(provider: "local", parallel: 1)
      deps = Fakes::Deps.new(providers: { "local" => Fakes::Provider.new(name: "local") { nil } })
      deps.stub_parse(post, nil) # parse_front_matter → nil
      runner = build_runner(settings, deps, root)
      runner.process_file(post)
      assert_equal 1, runner.stats.skipped
      assert_equal 1, runner.stats.processed
    end
  end
end

class TestDryRunWritesNothing < Minitest::Test
  include RunnerHelpers

  def test_dry_run_creates_no_output_and_no_fm_writes
    Dir.mktmpdir do |tmp|
      root = Pathname.new(tmp)
      coll = root / "_posts"
      coll.mkpath
      post = coll / "hello.md"
      original = "---\ntitle: Hello World\ndescription: D\n---\nBody\n"
      post.write(original)

      settings = Fakes.settings(provider: "openai", dry_run: true, parallel: 1,
                                collection: "posts", collections: ["posts"])
      cf = Fakes::ContentFile.new(path: post, title: "Hello World", description: "D",
                                  categories: "", preview: nil, author: nil,
                                  content: "Body", front_matter: {})
      # A provider that would explode if ever called in a dry run.
      prov = Fakes::Provider.new(name: "openai") { raise "provider must not run in dry-run" }
      deps = Fakes::Deps.new(providers: { "openai" => prov })
      deps.stub_parse(post, cf)

      runner = build_runner(settings, deps, root)
      runner.run

      refute (root / "assets" / "images" / "previews").exist?,
             "dry run must not create the previews directory"
      assert_equal original, post.read, "dry run must not rewrite the file"
      assert_empty deps.fm_updates, "dry run must not write front matter"
      assert_equal 1, runner.stats.generated # counted, but nothing written
    end
  end
end

class TestListMissing < Minitest::Test
  include RunnerHelpers

  def process(cf, preview_exists: false)
    root = Pathname.new(Dir.mktmpdir)
    settings = Fakes.settings(provider: "openai", list_only: true, parallel: 1)
    deps = Fakes::Deps.new(providers: { "openai" => Fakes::Provider.new(name: "openai") { nil } })
    deps.stub_parse(cf.path, cf)
    deps.preview_exists = preview_exists
    logger = capture_logger
    runner = build_runner(settings, deps, root, logger: logger)
    runner.process_file(cf.path)
    [logger.sink.lines, runner.stats]
  ensure
    FileUtils.remove_entry(root) if root
  end

  def test_missing_without_preview_key
    path = Pathname.new("/tmp/site/_posts/x.md")
    cf = Fakes::ContentFile.new(path: path, title: "My Title", description: "",
                                categories: "", preview: nil, author: nil,
                                content: "", front_matter: {})
    lines, stats = process(cf)
    assert_equal "#{Zer0ImageGenerator::Colors::YELLOW}Missing preview:" \
                 "#{Zer0ImageGenerator::Colors::NC} #{path}", lines[0]
    assert_equal "  Title: My Title", lines[1]
    assert_equal "", lines[2] # trailing blank; no "current preview" line
    assert_equal 0, stats.generated
    assert_equal 0, stats.skipped
  end

  def test_missing_with_stale_preview_key
    path = Pathname.new("/tmp/site/_posts/y.md")
    cf = Fakes::ContentFile.new(path: path, title: "Y", description: "",
                                categories: "", preview: "/old/y.png", author: nil,
                                content: "", front_matter: {})
    lines, = process(cf, preview_exists: false)
    assert_equal "  Title: Y", lines[1]
    assert_equal "  Current preview (not found): /old/y.png", lines[2]
    assert_equal "", lines[3]
  end
end

class TestIdempotency < Minitest::Test
  include RunnerHelpers

  def test_existing_valid_preview_is_skipped
    root = Pathname.new(Dir.mktmpdir)
    post = root / "p.md"
    post.write("---\ntitle: P\npreview: /x/p.png\n---\n")
    settings = Fakes.settings(provider: "openai", force: false, parallel: 1)
    cf = Fakes::ContentFile.new(path: post, title: "P", description: "", categories: "",
                                preview: "/x/p.png", author: nil, content: "", front_matter: {})
    called = false
    prov = Fakes::Provider.new(name: "openai") { called = true; nil }
    deps = Fakes::Deps.new(providers: { "openai" => prov })
    deps.stub_parse(post, cf)
    deps.preview_exists = true

    runner = build_runner(settings, deps, root)
    runner.process_file(post)

    assert_equal 1, runner.stats.skipped
    refute called, "renderer must not run when a valid preview already exists"
  ensure
    FileUtils.remove_entry(root)
  end

  def test_force_regenerates_even_when_preview_exists
    root = Pathname.new(Dir.mktmpdir)
    (root / "assets" / "images" / "previews").mkpath
    post = root / "p.md"
    post.write("---\ntitle: P\npreview: /x/p.png\n---\n")
    settings = Fakes.settings(provider: "openai", force: true, review_engine: "none",
                              prompt_engine: "template", parallel: 1)
    cf = Fakes::ContentFile.new(path: post, title: "P", description: "", categories: "",
                                preview: "/x/p.png", author: nil, content: "", front_matter: {})
    prov = Fakes::Provider.new(name: "openai") do |_p, _fs, out_base, _c|
      png = out_base.sub_ext(".png")
      png.binwrite(Fakes::PNG_SIGNATURE)
      Fakes::ImageResult.new(ok: true, kind: "png", path: png)
    end
    deps = Fakes::Deps.new(providers: { "openai" => prov })
    deps.stub_parse(post, cf)
    deps.preview_exists = true

    runner = build_runner(settings, deps, root)
    runner.process_file(post)

    assert_equal 0, runner.stats.skipped
    assert_equal 1, runner.stats.generated
  ensure
    FileUtils.remove_entry(root)
  end
end

class TestDiscoverOrdering < Minitest::Test
  include RunnerHelpers

  # pathlib.rglob sorts by PATH COMPONENTS, not by the raw string — a directory
  # whose name is a prefix of a sibling file sorts first. Verify the Ruby port
  # reproduces that, differentially against python3 when present.
  def build_tree(root)
    coll = root / "_posts"
    (coll / "a").mkpath
    (coll / ".hidden").mkpath
    (coll / "a" / "x.md").write("x")
    (coll / "a b.md").write("x")
    (coll / "a.md").write("x")
    (coll / "z.md").write("x")
    (coll / ".hidden" / "h.md").write("x")   # dotfiles are included by rglob
    (coll / "note.txt").write("x")           # non-md ignored
    coll
  end

  def test_component_wise_order_and_dotfiles
    Dir.mktmpdir do |tmp|
      root = Pathname.new(tmp)
      coll = build_tree(root)
      settings = Fakes.settings(provider: "local")
      deps = Fakes::Deps.new(providers: {})
      runner = build_runner(settings, deps, root)
      got = runner.discover(coll).map { |p| p.relative_path_from(coll).to_s }
      expected = [".hidden/h.md", "a/x.md", "a b.md", "a.md", "z.md"]
      assert_equal expected, got
    end
  end

  def test_matches_python_rglob
    skip "python3 unavailable" unless system("python3", "--version",
                                             out: File::NULL, err: File::NULL)
    Dir.mktmpdir do |tmp|
      root = Pathname.new(tmp)
      coll = build_tree(root)
      settings = Fakes.settings(provider: "local")
      runner = build_runner(settings, Fakes::Deps.new(providers: {}), root)
      got = runner.discover(coll).map { |p| p.relative_path_from(coll).to_s }

      py = IO.popen(["python3", "-c", <<~PY, coll.to_s], &:read)
        import sys
        from pathlib import Path
        base = Path(sys.argv[1])
        for p in sorted(base.rglob("*.md")):
            print(p.relative_to(base).as_posix())
      PY
      assert_equal py.split("\n"), got
    end
  end
end

class TestThreadSafety < Minitest::Test
  include RunnerHelpers

  # The per-file RunContext copy is what keeps parallel local rendering
  # deterministic: each worker must see its OWN ctx carrying its OWN slug, never
  # a shared mutable one. Run many files through the real thread pool and assert
  # every generate() saw the right, distinct slug.
  def test_each_worker_gets_its_own_slug_context
    Dir.mktmpdir do |tmp|
      root = Pathname.new(tmp)
      coll = root / "_posts"
      coll.mkpath
      titles = (0...40).map { |i| "Post Number #{i}" }
      files = titles.each_with_index.map do |t, i|
        f = coll / format("p%02d.md", i)
        f.write("---\ntitle: #{t}\n---\n")
        [f, t]
      end

      settings = Fakes.settings(provider: "openai", review_engine: "none",
                                prompt_engine: "template", parallel: 8,
                                collection: "posts", collections: ["posts"])

      seen = []
      seen_lock = Mutex.new
      shared_ctx = Fakes::Ctx.new(env: {}, slug: "SHARED")
      prov = Fakes::Provider.new(name: "openai") do |_p, _fs, out_base, fctx|
        # Record what THIS worker's context carried. If the slug were shared,
        # these would collide / mismatch out_base.
        seen_lock.synchronize do
          seen << { slug: fctx.slug, oid: fctx.object_id, base: out_base.basename.to_s }
        end
        Fakes::ImageResult.new(ok: true, kind: "png", path: out_base.sub_ext(".png"))
      end

      deps = Fakes::Deps.new(providers: { "openai" => prov })
      files.each { |f, t| deps.stub_parse(f, cf_for(f, t)) }

      runner = build_runner(settings, deps, root, ctx: shared_ctx)
      runner.process_collection(coll)

      expected_slugs = titles.map { |t| deps.generate_filename(t) }
      assert_equal expected_slugs.sort, seen.map { |s| s[:slug] }.sort
      # No worker ever saw the shared context's slug…
      refute_includes seen.map { |s| s[:slug] }, "SHARED"
      # …each file got a DISTINCT context object (the per-file copy)…
      assert_equal seen.length, seen.map { |s| s[:oid] }.uniq.length
      # …and the slug always matched the output base for that file.
      seen.each { |s| assert_equal s[:slug], s[:base] }
      assert_equal 40, runner.stats.generated
    end
  end

  def cf_for(path, title)
    Fakes::ContentFile.new(path: path, title: title, description: "", categories: "",
                           preview: nil, author: nil, content: "", front_matter: {})
  end
end

class TestInterrupt < Minitest::Test
  include RunnerHelpers

  def test_serial_stops_scheduling_after_interrupt
    Dir.mktmpdir do |tmp|
      root = Pathname.new(tmp)
      coll = root / "_posts"
      coll.mkpath
      files = (0...5).map do |i|
        f = coll / format("p%d.md", i)
        f.write("---\ntitle: T#{i}\n---\n")
        f
      end
      settings = Fakes.settings(provider: "openai", review_engine: "none",
                                prompt_engine: "template", parallel: 1,
                                collection: "posts", collections: ["posts"])
      interrupt = Zer0ImageGenerator::InterruptFlag.new
      processed = []
      lock = Mutex.new
      prov = Fakes::Provider.new(name: "openai") do |_p, _fs, out_base, _c|
        lock.synchronize { processed << out_base.basename.to_s }
        interrupt.trip # trip after the very first file
        Fakes::ImageResult.new(ok: true, kind: "png", path: out_base.sub_ext(".png"))
      end
      deps = Fakes::Deps.new(providers: { "openai" => prov })
      files.each_with_index { |f, i| deps.stub_parse(f, cf_for(f, "T#{i}")) }

      runner = build_runner(settings, deps, root, interrupt: interrupt)
      runner.process_collection(coll)

      # First file ran; the loop stopped scheduling the rest.
      assert_equal 1, processed.length
    end
  end

  def cf_for(path, title)
    Fakes::ContentFile.new(path: path, title: title, description: "", categories: "",
                           preview: nil, author: nil, content: "", front_matter: {})
  end
end
