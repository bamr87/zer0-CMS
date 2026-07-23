# frozen_string_literal: true

require "pathname"
require "fileutils"

require_relative "logging"
require_relative "stats"

module Zer0ImageGenerator
  # The single seam between this slice (Runner/CLI) and the settings/content/
  # providers/claude slices. Every cross-slice symbol the orchestrator needs is
  # resolved here so that (a) a Rails host or a test can inject fakes and (b)
  # integration wiring touches exactly one class. The Python engine reached
  # these as module-level functions and the PROVIDERS dict; the default
  # implementation below forwards to their Ruby ports. Method bodies resolve
  # the constants lazily (at call time, not load time) so this file loads even
  # before the sibling slices are present.
  #
  # NOTE: the exact Ruby names of the ported symbols are owned by the other
  # slices — see INTEGRATION_NEEDS. Adjust ONLY the forwarding in this class if
  # they differ; nothing above it should change.
  class Collaborators
    # -- content / front matter ------------------------------------------
    def read_authors(project_root, authors_file)
      Zer0ImageGenerator.read_authors(project_root, authors_file)
    end

    # Content-file helpers live under Content; settings/config helpers are
    # module-level (module_function). Route each delegate to its real home so
    # the orchestrator sees one flat collaborator surface.
    def parse_front_matter(path, fm_key)
      Content.parse_front_matter(path, fm_key)
    end

    def check_preview_exists(preview, settings, root)
      Content.check_preview_exists(preview, settings, root)
    end

    def find_preview_image(preview, settings, root)
      Content.find_preview_image(preview, settings, root)
    end

    def generate_filename(title)
      Content.generate_filename(title)
    end

    def file_preview_settings(settings, cf, authors)
      Zer0ImageGenerator.file_preview_settings(settings, cf, authors)
    end

    def build_prompt(cf, settings)
      Prompt.build_prompt(cf, settings)
    end

    def build_enhance_prompt(cf, settings)
      Prompt.build_enhance_prompt(cf, settings)
    end

    def preview_front_matter_path(settings, filename)
      Content.preview_front_matter_path(settings, filename)
    end

    def update_front_matter(path, value, dry_run:, key:)
      Content.update_front_matter(path, value, dry_run: dry_run, key: key)
    end

    # -- claude orchestration --------------------------------------------
    def claude_article_brief(client, cf, settings, base_prompt)
      Orchestration.claude_article_brief(client, cf, settings, base_prompt)
    end

    def claude_review_image(client, image_path, cf, prompt, settings)
      Orchestration.claude_review_image(client, image_path, cf, prompt, settings)
    end

    # -- providers -------------------------------------------------------
    def providers
      Zer0ImageGenerator::PROVIDERS
    end

    def provider_names_sorted
      providers.keys.sort
    end

    # The class raised by a provider that cannot enhance, caught in the
    # --enhance fallback to OpenAI.
    def edit_unsupported
      Zer0ImageGenerator::EditUnsupported
    end

    # -- run context -----------------------------------------------------
    # Per-file copy of the RunContext with a fresh slug. This copy is the
    # thread-safety linchpin: the local provider derives its deterministic
    # seed from ctx.slug, so workers must never share one mutable slug.
    def with_slug(ctx, slug)
      ctx.with_slug(slug)
    end

    def new_run_context(project_root, env)
      Zer0ImageGenerator::RunContext.new(project_root: project_root, env: env)
    end

    # -- constants -------------------------------------------------------
    # Serial-mode pacing between paid API calls. The RUNTIME value is the
    # rebindable module accessor (the test suite sets it to 0); the frozen
    # POST_GENERATION_SLEEP constant is only the published default.
    def post_generation_sleep
      Zer0ImageGenerator.post_generation_sleep
    end

    # -- CLI wiring (main) -----------------------------------------------
    def ensure_yaml
      # Ruby's YAML (Psych) is always in stdlib, so the Python PyYAML guard is
      # a no-op here. Kept as a seam so main() reads the same as the oracle.
      Zer0ImageGenerator.ensure_yaml if Zer0ImageGenerator.respond_to?(:ensure_yaml)
    end

    def load_dotenv
      # config.rb keeps the Python name, underscore and all.
      Zer0ImageGenerator._load_dotenv
    end

    def find_project_root
      Zer0ImageGenerator.find_project_root
    end

    def read_config(project_root)
      Zer0ImageGenerator.read_config(project_root)
    end

    def apply_source_root(project_root, config)
      Zer0ImageGenerator.apply_source_root(project_root, config)
    end

    def resolve_settings(args, config)
      Zer0ImageGenerator.resolve_settings(args, config)
    end

    # Graceful Claude degrade: a copy with prompt_engine/review_engine turned
    # off (Python's `replace(settings, prompt_engine="template", review_engine="none")`).
    # Settings exposes the dataclasses.replace port as dup_with.
    def degrade_settings(settings)
      settings.dup_with(prompt_engine: "template", review_engine: "none")
    end

    def default_model(provider_name)
      providers[provider_name].default_model
    end

    def claude_credential_hint
      Zer0ImageGenerator::CLAUDE_CREDENTIAL_HINT
    end
  end

  class Runner
    attr_reader :settings, :root, :stats, :authors, :ctx

    def initialize(settings, project_root, ctx: nil, deps: nil, logger: nil, interrupt: nil)
      @settings = settings
      @root = Pathname.new(project_root.to_s)
      @deps = deps || Collaborators.new
      @logger = logger || Logging.logger
      @interrupt = interrupt || InterruptFlag.new
      @stats = Stats.new
      @authors = @deps.read_authors(@root, settings.authors_file)
      @ctx = ctx || @deps.new_run_context(@root, ENV.to_h)
    end

    # -- discovery -------------------------------------------------------

    # `<root>/<collections_dir>/_<name>` — collections_dir is Jekyll's own key
    # (default "" = site root; zer0-mistakes sets `pages`).
    def collection_path(name)
      base = @root
      @settings.collections_dir.split("/").each do |part|
        base = base / part unless part.empty?
      end
      base / "_#{name}"
    end

    def discover(collection_path)
      unless collection_path.directory?
        warn("Collection directory not found: #{collection_path}")
        return []
      end
      # Python: sorted(collection_path.rglob("*.md")). rglob descends into and
      # matches dotfiles/dot-dirs (FNM_DOTMATCH) but does NOT follow symlinked
      # dirs — Ruby's `**` matches that default. The sort must be BY PATH
      # COMPONENTS, not by the full string: pathlib compares the parts tuple,
      # where a dir name that is a prefix of a sibling file sorts first
      # ('a'/'c.md' < 'a b.md' < 'a.md'), which a plain String#sort gets wrong
      # because '/' (0x2F) outranks ' ' and '.'.
      base = collection_path.to_s
      Dir.glob("**/*.md", File::FNM_DOTMATCH, base: base)
         .sort_by { |rel| rel.split("/") }
         .map { |rel| collection_path / rel }
    end

    # -- per-file processing --------------------------------------------

    def process_file(path)
      return if @interrupt.tripped?

      settings = @settings
      @stats.inc(:processed)
      debug("Processing file: #{path}")

      cf = @deps.parse_front_matter(path, settings.front_matter_key)
      if cf.nil?
        @stats.inc(:skipped)
        return
      end

      if settings.enhance
        enhance_file(cf)
        return
      end

      # Generate mode ---------------------------------------------------
      if cf.preview && @deps.check_preview_exists(cf.preview, settings, @root)
        unless settings.force
          debug("Preview already exists and is valid: #{cf.preview}")
          @stats.inc(:skipped)
          return
        end
        info("Force mode: regenerating preview for #{cf.title}")
      end

      if settings.list_only
        say("#{Colors::YELLOW}Missing preview:#{Colors::NC} #{path}")
        say("  Title: #{cf.title}")
        say("  Current preview (not found): #{cf.preview}") if cf.preview
        say
        return
      end

      info("Generating preview for: #{cf.title}")

      slug = @deps.generate_filename(cf.title)
      if slug.nil? || slug.empty?
        warn("Cannot derive filename from title in #{path}")
        @stats.inc(:errors)
        return
      end
      out_base = @root / settings.output_dir / slug

      # Style overrides apply only once an image/prompt is actually built.
      file_settings = @deps.file_preview_settings(settings, cf, @authors)

      # ---- Analyze: Claude reads the article and writes the art brief ----
      base_prompt = @deps.build_prompt(cf, file_settings)
      prompt = base_prompt
      orchestrated = settings.provider != "local" # local is deterministic
      if orchestrated && file_settings.prompt_engine == "claude" && !settings.dry_run
        prompt = @deps.claude_article_brief(@ctx.claude, cf, file_settings, base_prompt)
      end
      debug("Generated prompt: #{prompt[0, 500]}...")

      if settings.dry_run
        info("[DRY RUN] Would generate image:")
        say("  Provider: #{settings.provider}")
        if orchestrated && file_settings.prompt_engine == "claude"
          say("  Prompt engine: claude (article analysis runs at generation time)")
        end
        if orchestrated && file_settings.review_engine == "claude"
          say("  Review: claude (image review runs at generation time)")
        end
        say("  Output: #{out_base.sub_ext('.png')}")
        say("  Preview path: #{@deps.preview_front_matter_path(file_settings, slug + '.png')}")
        say("  Prompt: #{prompt[0, 400]}...")
        say
        @stats.inc(:generated)
        return
      end

      provider = @deps.providers[settings.provider]
      # Per-file context copy: workers must not share a mutable slug (the local
      # provider derives its deterministic seed from it). The copy carries the
      # shared AnthropicClient reference, which is stateless after init and
      # therefore thread-safe.
      file_ctx = @deps.with_slug(@ctx, slug)
      # ---- Produce: the selected raster model renders the brief ----
      result = provider.generate(prompt, file_settings, out_base, file_ctx)

      # ---- Review: Claude inspects the render; at most ONE regeneration ----
      if orchestrated && file_settings.review_engine == "claude" &&
         result.ok && result.path && result.kind == "png"
        approved, critique, revised =
          @deps.claude_review_image(@ctx.claude, result.path, cf, prompt, file_settings)
        if approved
          debug("Claude review: #{critique}") if critique && !critique.empty?
        else
          info("  ↳ Claude review requested a revision: #{critique}")
          debug("Revised prompt: #{revised[0, 300]}...")
          retry_result = provider.generate(revised, file_settings, out_base, file_ctx)
          if retry_result.ok && retry_result.path
            result = retry_result
            success("  ↳ Regenerated with Claude's revised brief")
          else
            warn("  ↳ Revision render failed " \
                 "(#{retry_result.error || 'unknown'}); keeping the first image")
          end
        end
      end

      if result.ok && result.path
        fm_value = @deps.preview_front_matter_path(file_settings, result.path.basename.to_s)
        if @deps.update_front_matter(path, fm_value, dry_run: false, key: settings.front_matter_key)
          @stats.inc(:generated)
          # Serial-mode pacing between paid API calls (historical behavior). In
          # parallel mode a per-worker sleep throttles nothing — it only burns
          # worker capacity — so skip it.
          sleep_secs = @deps.post_generation_sleep
          sleep(sleep_secs) if sleep_secs && !sleep_secs.zero? && settings.parallel <= 1
        else
          @stats.inc(:errors)
        end
      else
        warn("Failed to generate image for: #{cf.title}")
        warn("  #{result.error}") if result.error
        @stats.inc(:errors)
      end
    end

    def enhance_file(cf)
      settings = @settings
      existing = @deps.find_preview_image(cf.preview, settings, @root)
      if existing.nil?
        warn("No existing preview image found for: #{cf.title}")
        warn("  Expected at: #{cf.preview}")
        warn("  Use without --enhance to generate a new image first.")
        @stats.inc(:skipped)
        return
      end

      info("Enhancing preview for: #{cf.title}")
      file_settings = @deps.file_preview_settings(settings, cf, @authors)
      prompt = @deps.build_enhance_prompt(cf, file_settings)
      debug("Enhancement prompt: #{prompt[0, 400]}...")

      if settings.dry_run
        info("[DRY RUN] Would enhance image:")
        say("  Source: #{existing}")
        say("  Model: #{settings.enhance_model}")
        say("  Prompt: #{prompt[0, 400]}...")
        say
        @stats.inc(:enhanced)
        return
      end

      # --enhance-format other than the current extension writes a NEW file
      # (content and extension must agree) and repoints the front matter; the
      # default png-onto-png flow enhances in place with a backup.
      out_path = existing.sub_ext("." + settings.enhance_format)
      in_place = out_path == existing

      if in_place
        backup = existing.dirname / "#{existing.basename(existing.extname)}_pre-enhance#{existing.extname}"
        if !backup.exist?
          FileUtils.cp(existing.to_s, backup.to_s, preserve: true)
          info("Original backed up to: #{backup.basename}")
        else
          debug("Backup already exists: #{backup}")
        end
      else
        backup = existing # original file is untouched and acts as the fallback
      end

      # Capability-driven routing: the active provider's edit() runs when it
      # has one; EditUnsupported falls back to OpenAI (historical behavior).
      provider = @deps.providers[settings.provider]
      begin
        result = provider.edit(existing, prompt, file_settings, @ctx, out_path)
      rescue @deps.edit_unsupported
        warn("Enhancement not supported for provider: #{settings.provider} " \
             "(falling back to OpenAI)")
        openai_provider = @deps.providers["openai"]
        unless openai_provider.is_configured(@ctx.env)
          warn("Enhance requires OPENAI_API_KEY (the images/edits API is OpenAI-only).")
          @stats.inc(:errors)
          return
        end
        result = openai_provider.edit(existing, prompt, file_settings, @ctx, out_path)
      end

      if result.ok
        if !in_place && result.path && result.path != existing
          old_value = cf.preview || ""
          new_value =
            if old_value.include?("/")
              old_value.rpartition("/")[0] + "/" + result.path.basename.to_s
            else
              result.path.basename.to_s
            end
          @deps.update_front_matter(cf.path, new_value, dry_run: false,
                                    key: settings.front_matter_key)
          info("Preview extension changed: #{existing.basename} → #{result.path.basename}")
        end
        success("Enhanced image saved to: #{result.path || existing}")
        @stats.inc(:enhanced)
      else
        warn("Failed to enhance image for: #{cf.title}")
        warn("  #{result.error}") if result.error
        info("Original preserved at: #{backup}")
        @stats.inc(:errors)
      end
    end

    # -- collection / run loop ------------------------------------------

    def process_collection(collection_path)
      files = discover(collection_path)
      files = files[0, @settings.batch] if @settings.batch.positive?
      return if files.nil? || files.empty?

      serial = @settings.list_only || @settings.dry_run || @settings.parallel <= 1
      if serial
        files.each do |file_path|
          if @interrupt.tripped?
            warn("Interrupted! Stopping...")
            break
          end
          process_file(file_path)
        end
        return
      end

      run_parallel(files)
    end

    def run
      settings = @settings
      if settings.file && !settings.file.empty?
        target = Pathname.new(settings.file)
        unless target.absolute?
          # Source-relative first; then cwd-relative, so repo-root paths like
          # pages/_notes/x.md still work on `source:` sites.
          target = @root / settings.file
          if !target.file? && (Pathname.pwd / settings.file).file?
            target = Pathname.pwd / settings.file
          end
        end
        error_exit("File not found: #{settings.file}") unless target.file?
        process_file(target)
      elsif settings.collection && !settings.collection.empty? && settings.collection != "all"
        path = collection_path(settings.collection)
        unless path.directory?
          available = settings.collections.join(", ")
          error_exit("Unknown collection: #{settings.collection}. " \
                     "Available: #{available}, all")
        end
        step("Processing #{settings.collection} collection...")
        process_collection(path)
      else
        step("Processing all configured collections...")
        settings.collections.each do |name|
          path = collection_path(name)
          if path.directory?
            step("Processing #{name} collection...")
            process_collection(path)
          else
            warn("Collection directory not found: #{path}")
          end
        end
      end

      say
      print_header("📊 Summary")
      say("  Files processed: #{@stats.processed}")
      say("  Images generated: #{@stats.generated}")
      say("  Images enhanced: #{@stats.enhanced}")
      say("  Files skipped: #{@stats.skipped}")
      say("  Errors: #{@stats.errors}")
      say

      info("This was a dry run. No actual changes were made.") if settings.dry_run
      if @stats.errors.positive?
        warn("Some files had errors. Check the output above.")
        return 1
      end
      success("Preview image generation complete!")
      0
    end

    private

    # Fixed pool of `parallel` worker threads draining a shared queue. This
    # mirrors the Python ThreadPoolExecutor(max_workers=parallel): at most N
    # concurrent process_file calls, each file handled once. A tripped
    # interrupt stops the pool from claiming NEW work (in-flight files finish),
    # matching process_file's own `if _interrupted: return` guard plus the
    # as_completed cancel/break. A worker exception is caught here (as the
    # Python surfaced it via future.exception()) → warn + errors++.
    def run_parallel(files)
      queue = Queue.new
      files.each { |f| queue << f }
      workers = [@settings.parallel, files.length].min
      threads = Array.new(workers) do
        Thread.new do
          loop do
            file_path = begin
              queue.pop(true)
            rescue ThreadError
              break # queue drained
            end
            break if @interrupt.tripped?

            begin
              process_file(file_path)
            rescue StandardError => e
              warn("Worker failed on #{file_path}: #{e}")
              @stats.inc(:errors)
            end
          end
        end
      end
      # First interrupt observed during the join drains the queue so no idle
      # worker picks up more — the Python cancels pending futures for the same
      # effect.
      announced = false
      until threads.all? { |t| !t.alive? }
        if @interrupt.tripped? && !announced
          queue.clear
          warn("Interrupted! Cancelling remaining tasks...")
          announced = true
        end
        threads.each { |t| t.join(0.05) }
      end
    end

    # -- log delegation (injectable sink) --------------------------------

    def info(message)
      @logger.info(message)
    end

    def step(message)
      @logger.step(message)
    end

    def success(message)
      @logger.success(message)
    end

    def warn(message)
      @logger.warn(message)
    end

    def debug(message)
      @logger.debug(message)
    end

    def say(text = "")
      @logger.say(text)
    end

    def print_header(title)
      @logger.print_header(title)
    end

    def error_exit(message, status = 1)
      @logger.error_exit(message, status)
    end
  end
end
