# frozen_string_literal: true

require "optparse"
require "pathname"
require "fileutils"

require_relative "logging"
require_relative "stats"
require_relative "runner"

module Zer0ImageGenerator
  # Argument parsing + `main`. Ported from the Python engine's argparse CLI so
  # the flag surface, defaults, and exit codes match exactly:
  #   0 = success, 1 = validation failure / per-file errors, 2 = usage error.
  # OptionParser stands in for argparse; parse errors are normalized to the
  # argparse exit code (2) and --help to 0, both raised as ExitError so a Rails
  # host is never taken down by a bad request — CLI.start turns it back into a
  # process status for command-line use.
  module CLI
    PROG = "zer0-image-generator"

    # Must equal sorted(PROVIDERS.keys()); see INTEGRATION_NEEDS. Argparse
    # derived this from the registry — kept as a literal so parse_args stays
    # runnable without the providers slice loaded.
    PROVIDER_CHOICES = %w[gemini local openai stability xai].freeze
    ENHANCE_QUALITY_CHOICES = %w[low medium high auto].freeze
    ENHANCE_FIDELITY_CHOICES = %w[high low].freeze
    ENHANCE_FORMAT_CHOICES = %w[png jpeg webp].freeze
    PROMPT_ENGINE_CHOICES = %w[template claude].freeze
    REVIEW_CHOICES = %w[claude none].freeze
    RASTERIZER_CHOICES = %w[auto rsvg inkscape magick playwright none].freeze

    # The argparse Namespace, field-for-field. Booleans default false, parallel
    # defaults nil (resolve_settings then falls back to MAX_PARALLEL/4), batch
    # defaults 0, everything else nil — the exact shape resolve_settings reads.
    Args = Struct.new(
      :dry_run, :verbose, :file, :collection, :provider, :model, :output_dir,
      :force, :list_missing, :parallel, :enhance, :enhance_prompt,
      :enhance_model, :enhance_quality, :enhance_fidelity, :enhance_format,
      :prompt_engine, :review, :rasterizer, :style, :assets_prefix,
      :no_auto_prefix, :collections_dir, :front_matter_key, :authors_file,
      :batch, :log_file, :rate_limit,
      keyword_init: true
    ) do
      def to_h_sorted
        to_h.transform_keys(&:to_s).sort.to_h
      end
    end

    module_function

    def default_args
      Args.new(
        dry_run: false, verbose: false, file: nil, collection: nil,
        provider: nil, model: nil, output_dir: nil, force: false,
        list_missing: false, parallel: nil, enhance: false, enhance_prompt: nil,
        enhance_model: nil, enhance_quality: nil, enhance_fidelity: nil,
        enhance_format: nil, prompt_engine: nil, review: nil, rasterizer: nil,
        style: nil, assets_prefix: nil, no_auto_prefix: false,
        collections_dir: nil, front_matter_key: nil, authors_file: nil,
        batch: 0, log_file: nil, rate_limit: nil
      )
    end

    # Builds the OptionParser bound to `args`. Kept separate (as the Python's
    # build_arg_parser) so callers can render --help without parsing.
    # OptionParser token for base-10 integer flags. Python argparse's
    # `type=int` calls int(), which is base-10 and rejects 0x/0o/0b prefixes;
    # OptionParser's built-in Integer accepts those prefixes, so `--parallel 010`
    # would be octal 8 in Ruby but decimal 10 in Python. Parse base-10 to match.
    Base10Int = Object.new

    def build_arg_parser(args)
      OptionParser.new do |o|
        o.program_name = PROG
        o.banner = "usage: #{PROG} [options]"
        o.accept(Base10Int, /\A\s*[-+]?\d+\s*\z/) { |s| Integer(s.strip, 10) }
        o.separator ""
        o.separator "AI preview/social-image generator for Jekyll sites — " \
                    "Claude analyzes & reviews, a renderer produces " \
                    "(openai [default], xai, stability, gemini, local)"

        o.on("-d", "--dry-run", "Preview what would be generated (no changes)") { args.dry_run = true }
        o.on("-v", "--verbose", "Enable verbose output") { args.verbose = true }
        o.on("-f", "--file FILE", "Process a specific file only") { |v| args.file = v }
        o.on("-c", "--collection NAME",
             "Process one collection by name, or 'all' for every configured collection") { |v| args.collection = v }
        o.on("-p", "--provider PROVIDER", "AI provider (default: claude, via _config.yml)") do |v|
          args.provider = choice!("-p/--provider", v, PROVIDER_CHOICES)
        end
        o.on("--model MODEL", "Override the image/SVG model for the provider") { |v| args.model = v }
        o.on("--output-dir DIR", "Output directory for images (default: assets/images/previews)") { |v| args.output_dir = v }
        o.on("--force", "Regenerate images even if preview exists") { args.force = true }
        o.on("--list-missing", "Only list files with missing previews") { args.list_missing = true }
        o.on("-j", "-w", "--parallel N", "--workers N", Base10Int,
             "Concurrent workers (default 4; serial for dry-run/list)") { |v| args.parallel = v }
        o.on("-e", "--enhance", "Enhance existing preview images (OpenAI images/edits)") { args.enhance = true }
        o.on("--enhance-prompt PROMPT", "Custom enhancement prompt (implies --enhance)") { |v| args.enhance_prompt = v }
        o.on("--enhance-model MODEL", "Model for enhancement (default: gpt-image-2)") { |v| args.enhance_model = v }
        o.on("--enhance-quality Q", "Enhancement quality (default: auto)") do |v|
          args.enhance_quality = choice!("--enhance-quality", v, ENHANCE_QUALITY_CHOICES)
        end
        o.on("--enhance-fidelity F", "Input fidelity (implies --enhance)") do |v|
          args.enhance_fidelity = choice!("--enhance-fidelity", v, ENHANCE_FIDELITY_CHOICES)
        end
        o.on("--enhance-format FMT", "Enhanced output format (implies --enhance)") do |v|
          args.enhance_format = choice!("--enhance-format", v, ENHANCE_FORMAT_CHOICES)
        end
        o.on("--prompt-engine ENGINE",
             "Art-direction brief: claude analyzes the article (default) or template") do |v|
          args.prompt_engine = choice!("--prompt-engine", v, PROMPT_ENGINE_CHOICES)
        end
        o.on("--review ENGINE",
             "Post-render review: claude inspects the image and may request one regeneration (default: claude)") do |v|
          args.review = choice!("--review", v, REVIEW_CHOICES)
        end
        o.on("--rasterizer TOOL",
             "SVG→PNG tool for claude/local providers (default: auto; `none` keeps the .svg and writes no PNG)") do |v|
          args.rasterizer = choice!("--rasterizer", v, RASTERIZER_CHOICES)
        end
        o.on("--style STYLE", "Override image style prompt") { |v| args.style = v }
        o.on("--assets-prefix PREFIX", "Assets prefix for path normalization") { |v| args.assets_prefix = v }
        # store_true; the yielded value is irrelevant (OptionParser passes false
        # for a bare --no-… switch), the flag's mere presence sets it.
        o.on("--no-auto-prefix", "Disable automatic assets prefix prepending") { args.no_auto_prefix = true }
        o.on("--collections-dir DIR",
             "Directory holding _<collection> dirs (default: Jekyll's top-level collections_dir, else the site root)") { |v| args.collections_dir = v }
        o.on("--front-matter-key KEY",
             "Front-matter key to read/write (default: preview; jekyll-seo-tag sites typically use image)") { |v| args.front_matter_key = v }
        o.on("--authors-file FILE",
             "Author-overrides YAML relative to the site root (default: _data/authors.yml; pass '' to disable)") { |v| args.authors_file = v }
        o.on("--batch N", Base10Int, "Limit number of files processed (0 = no limit)") { |v| args.batch = v }
        o.on("--log-file FILE", "Also write log output to a file") { |v| args.log_file = v }
        # Back-compat no-op (argparse.SUPPRESS in the oracle): accepted, ignored.
        o.on("--rate-limit N", Base10Int) { |v| args.rate_limit = v }
        o.on("-h", "--help", "Show this help message and exit") do
          # argparse prints help to stdout and exits 0.
          $stdout.puts o
          raise ExitError.new("", 0)
        end
      end
    end

    # Parses argv into an Args. Mirrors the Python parse_args, including the
    # historical rule that --enhance-prompt/-fidelity/-format imply --enhance
    # (but --enhance-model does NOT). Raises ExitError(2) on any usage error,
    # ExitError(0) on --help.
    def parse_args(argv = ARGV)
      args = default_args
      parser = build_arg_parser(args)
      begin
        rest = parser.parse(argv.dup)
      rescue OptionParser::ParseError => e
        # argparse: usage error → stderr + exit 2.
        $stderr.puts "#{parser.banner}"
        $stderr.puts "#{PROG}: error: #{e.message}"
        raise ExitError.new(e.message, 2)
      end
      unless rest.empty?
        $stderr.puts "#{parser.banner}"
        $stderr.puts "#{PROG}: error: unrecognized arguments: #{rest.join(' ')}"
        raise ExitError.new("unrecognized arguments: #{rest.join(' ')}", 2)
      end

      if args.enhance_prompt || args.enhance_fidelity || args.enhance_format
        args.enhance = true
      end
      args
    end

    # argparse rejects an out-of-set choice with exit 2; OptionParser would
    # otherwise silently prefix-match a value, so validate exactly.
    def choice!(flag, value, choices)
      return value if choices.include?(value)

      raise OptionParser::InvalidArgument, value
    end

    # Credential checks are skipped for --list-missing/--dry-run (historical
    # behavior), but an unknown provider name (from AI_PROVIDER / _config.yml —
    # argparse already constrains -p) errors in every mode.
    def validate_credentials(settings, ctx, deps: Collaborators.new, logger: Logging.logger)
      provider = deps.providers[settings.provider]
      if provider.nil?
        logger.error_exit("Unknown AI provider: #{settings.provider}. " \
                          "Available: #{deps.provider_names_sorted.join(', ')}")
      end
      return if settings.list_only || settings.dry_run

      if provider.name == "local"
        logger.info("Using local provider - no API key required")
        return
      end
      logger.error_exit(provider.missing_hint(ctx.env)) unless provider.is_configured(ctx.env)
      # Providers with more than one way in (xAI: OAuth token, then API key) say
      # which one this run picked, so a silent fallback is never a surprise.
      if provider.respond_to?(:auth_description)
        description = provider.auth_description(ctx.env)
        logger.info("#{provider.name} auth: #{description}") if description
      end
    end

    # Full run. Returns the process exit code (0/1). Usage errors and
    # error_exit escape as ExitError(status); CLI.start converts those for a
    # command-line binary.
    def main(argv = ARGV, deps: Collaborators.new, logger: Logging.logger,
             interrupt: InterruptFlag.new, install_signals: true)
      # The whole engine (including the settings/content slices) logs through
      # the module-level Logging helpers; point them at this run's sink so a
      # web UI streams config resolution too, not just the Runner.
      Logging.logger = logger

      install_signal_handlers(interrupt) if install_signals

      args = parse_args(argv)
      deps.ensure_yaml
      deps.load_dotenv

      project_root = deps.find_project_root
      site_config = deps.read_config(project_root)
      project_root = deps.apply_source_root(project_root, site_config)
      settings = deps.resolve_settings(args, site_config)
      logger.verbose = settings.verbose

      if args.log_file && logger.open_log_file(args.log_file)
        logger.info("Logging to: #{args.log_file}")
      end

      explicitly_targeted =
        !settings.file.to_s.empty? || !settings.collection.to_s.empty? ||
        settings.enhance || settings.provider_explicit
      if !settings.enabled && !explicitly_targeted
        logger.info("preview_images.enabled is false in _config.yml — nothing to do " \
                    "(pass --provider, --file or --collection to override).")
        return 0
      end

      logger.print_header("🎨 Preview Image Generator")
      ctx = deps.new_run_context(project_root, ENV.to_h)
      validate_credentials(settings, ctx, deps: deps, logger: logger)

      # Claude orchestration (analyze/review) degrades gracefully: without a
      # Claude credential the run continues on template prompts, unreviewed.
      wants_claude =
        settings.provider != "local" &&
        (settings.prompt_engine == "claude" || settings.review_engine == "claude") &&
        !(settings.dry_run || settings.list_only)
      if wants_claude
        if ctx.claude.available?
          logger.info("Claude orchestration: #{ctx.claude.describe}")
        else
          logger.warn(deps.claude_credential_hint)
          settings = deps.degrade_settings(settings)
        end
      end

      output_dir = Pathname.new(project_root.to_s) / settings.output_dir
      unless settings.dry_run || settings.list_only
        FileUtils.mkdir_p(output_dir.to_s)
      end

      logger.info("Configuration:")
      model = settings.model.to_s.empty? ? deps.default_model(settings.provider) : settings.model
      logger.say("  AI Provider: #{settings.provider}")
      logger.say("  Image Model: #{model}")
      logger.say("  Output Dir: #{settings.output_dir}")
      logger.say("  Image Size: #{settings.size}")
      logger.say("  Parallel Workers: #{settings.parallel}")
      logger.say("  Dry Run: #{settings.dry_run}")
      logger.say("  Force: #{settings.force}")
      logger.say("  List Only: #{settings.list_only}")
      logger.say("  Prompt Engine: #{settings.prompt_engine}")
      logger.say("  Review: #{settings.review_engine}")
      if settings.enhance
        logger.say("  Mode: ENHANCE (improve existing images)")
        logger.say("  Enhance Model: #{settings.enhance_model}")
        logger.say("  Enhance Quality: #{settings.enhance_quality}")
        logger.say("  Input Fidelity: #{settings.enhance_fidelity}")
        logger.say("  Output Format: #{settings.enhance_format}")
        if settings.enhance_prompt && !settings.enhance_prompt.empty?
          logger.say("  Custom Prompt: #{settings.enhance_prompt[0, 80]}...")
        else
          logger.say("  Prompt: (default improvement prompt)")
        end
      end
      logger.say

      runner = Runner.new(settings, project_root, ctx: ctx, deps: deps,
                          logger: logger, interrupt: interrupt)
      exit_code = runner.run

      logger.close_log_file
      exit_code
    end

    # Convenience wrapper for a command-line binary: run main and turn an
    # ExitError (usage error, --help, error_exit) into a plain exit status.
    def start(argv = ARGV, **kwargs)
      main(argv, **kwargs)
    rescue ExitError => e
      e.status
    end

    def install_signal_handlers(interrupt)
      # Graceful SIGINT/SIGTERM: flip the flag so the run stops SCHEDULING new
      # work and let in-flight files finish. Trap context forbids mutex use, so
      # this writes to stdout directly (as the Python handler's bare print did)
      # and Interrupt is deliberately lock-free.
      handler = proc do
        interrupt.trip
        $stdout.write("\n#{Colors::YELLOW}⚠️  Interrupt received. " \
                      "Finishing current tasks...#{Colors::NC}\n")
      end
      Signal.trap("INT", &handler)
      Signal.trap("TERM", &handler)
    end
  end
end
