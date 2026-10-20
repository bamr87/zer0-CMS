# frozen_string_literal: true

# The single seam between the Rails app and the ported image engine.
#
# Everything the app does with the engine goes through here, so the coupling to
# the engine's internal module layout lives in one file. The engine is pure
# Ruby (loaded off $LOAD_PATH in config/application.rb), so these are ordinary
# in-process calls — no shelling out, no subprocess, no drift between a CLI
# engine and a web engine because there is only one engine.
module EngineBridge
  class Error < StandardError; end

  # Require the whole engine once, lazily, so a failure to load surfaces as a
  # clear app-level error rather than a boot crash, and so the app boots even
  # in environments where the engine tree is absent (e.g. asset precompile).
  def self.load!
    @loaded ||= begin
      require "zer0_image_generator/all"
      true
    end
  rescue LoadError => e
    raise Error, "image engine failed to load: #{e.message}"
  end

  # Read a site's full _config.yml as the engine sees it. Returns {} for a
  # missing or empty file — never raises for absence, so callers can treat an
  # unconfigured site the same as a default-configured one.
  def self.read_config(root)
    load!
    Zer0ImageGenerator.read_config(Pathname.new(root.to_s))
  rescue Zer0ImageGenerator::Error => e
    raise Error, e.message
  end

  # Apply Jekyll's top-level `source:` key: content and assets live under
  # <root>/<source> while _config.yml stays at the root. The engine shifts the
  # project root here before handing it to the Runner, so every path (Runner,
  # output dir, artifact scan) has to be derived from the SAME shifted root.
  def self.project_root(site_root, config)
    load!
    Zer0ImageGenerator.apply_source_root(Pathname.new(site_root.to_s), config || {})
  end

  # Merge CLI-style args + the site config into a resolved Settings object,
  # applying the engine's own precedence (CLI > env > config > defaults).
  def self.resolve_settings(args_hash, config)
    load!
    args = Zer0ImageGenerator::Args.build(args_hash || {})
    Zer0ImageGenerator.resolve_settings(args, config || {})
  end

  # Build a Runner wired to a log sink, an interrupt flag, and an environment.
  # The Runner is the same object the CLI drives; only its output, cancellation,
  # and credential source are redirected.
  #
  # `env` is passed as the RunContext's environment rather than mutating the
  # process ENV, because jobs run concurrently and a shared mutable ENV would
  # leak one run's keys into another. The RunContext env is read-only to the
  # engine, so sharing it across a run's worker threads is safe.
  def self.runner(settings, root, sink:, interrupt:, env: ENV.to_h, verbose: false)
    load!
    logger = Zer0ImageGenerator::Logger.new(sink: sink, verbose: verbose)
    root_path = Pathname.new(root.to_s)
    ctx = Zer0ImageGenerator::RunContext.new(project_root: root_path, env: env)
    Zer0ImageGenerator::Runner.new(settings, root_path, ctx: ctx, logger: logger, interrupt: interrupt)
  end

  # A fresh interrupt flag (the engine's own cooperative-cancel primitive).
  def self.interrupt
    load!
    Zer0ImageGenerator::InterruptFlag.new
  end

  def self.provider_names
    load!
    Zer0ImageGenerator::PROVIDERS.keys
  end

  # Which providers can actually run given the current environment. The ENGINE
  # owns that question — xAI, for one, is reachable through a Grok OAuth token
  # (env var or credentials file) as well as its API key — so ask each provider
  # instead of mapping a provider to one env var here. `local` needs nothing and
  # answers true on its own.
  def self.available_providers(env = ENV)
    load!
    Zer0ImageGenerator::PROVIDERS.select { |_name, provider| provider.is_configured(env) }.keys
  end
end
