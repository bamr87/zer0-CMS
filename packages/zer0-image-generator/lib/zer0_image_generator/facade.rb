# frozen_string_literal: true

# Zer0ImageGenerator::Facade — the stable, Rails-free API for other apps.
#
# zer0-CMS (and any other host) asks the image engine two questions:
#
#   Zer0ImageGenerator::Facade.missing_previews(site_root)
#     # => [MissingPreview(path:, relative:, collection:, title:, preview:), ...]
#
#   Zer0ImageGenerator::Facade.generate_one(site_root, "_posts/2026-01-01-x.md",
#                                          provider: "local", env: {}, dry_run: false)
#     # => Generation(status:, file:, provider:, preview:, image:, stats:,
#     #               exit_code:, error:, log:)
#
# Both are compositions of the engine's own objects — read_config,
# apply_source_root, resolve_settings, Runner#collection_path, Runner#discover,
# Content.parse_front_matter / check_preview_exists, CLI.validate_credentials,
# Runner#run — so "missing" and "generate" mean exactly what they mean to
# `jekyll preview-images --list-missing` and `jekyll preview-images -f FILE`.
# No pipeline logic lives here; the only things this file adds are path
# confinement (every path must resolve inside the site root) and structured
# results in place of printed lines.
#
# Contract (semver-stable from the release that ships this file):
# - A caller error (site root not a directory, file not found, a path, `source:`
#   or `collections_dir:`/`output_dir:` that resolves outside the site root)
#   raises Facade::Error, a Zer0ImageGenerator::Error.
# - An engine outcome (unknown provider, missing credential, a failed render)
#   is returned as a Generation with status :error — never raised.
# - `env:` is the credential environment handed to the providers (the same
#   RunContext env the web app uses); the process ENV is never mutated.
#   Settings precedence is the CLI's own — `preview_images:` config, overridden
#   by the documented env vars (AI_PROVIDER, OUTPUT_DIR, ...) of the process.
# - Thread-safe per call: each call builds its own Runner, logger and
#   RunContext. Slice-level messages (front-matter writes, rasterizer notes)
#   still go to Zer0ImageGenerator::Logging.logger, which this file never
#   swaps, so concurrent callers cannot steal each other's output.
#
# Stdlib only, by policy.

require "pathname"
require "fileutils"

require_relative "all"

module Zer0ImageGenerator
  module Facade
    class Error < Zer0ImageGenerator::Error; end

    # One content file whose preview is absent or points at nothing on disk.
    # `path` is absolute; `relative` is relative to the site root (so it
    # includes a `source:` directory); `preview` is the stale front-matter
    # value, or nil when the key is absent.
    MissingPreview = Struct.new(:path, :relative, :collection, :title, :preview,
                                keyword_init: true)

    # The outcome of generate_one.
    #   status     :generated | :would_generate (dry run) | :skipped | :error
    #   file       absolute path of the content file
    #   provider   the provider the run resolved to
    #   preview    the front-matter value after the run (nil when absent)
    #   image      absolute path of that preview on disk (nil when not found)
    #   stats      { processed:, generated:, enhanced:, skipped:, errors: }
    #   exit_code  the engine's exit status (0 ok, 1 failure)
    #   error      a human-readable reason when status is :error
    #   log        [[level, text], ...] — the run's own log, ANSI stripped
    Generation = Struct.new(:status, :file, :provider, :preview, :image, :stats,
                            :exit_code, :error, :log, keyword_init: true) do
      def ok?
        status != :error
      end
    end

    # Logger sink that records instead of printing (see logging.rb's sink
    # contract: log / say / header).
    class Recorder
      ANSI = /\e\[[0-9;]*m/.freeze

      def initialize
        @entries = []
        @lock = Mutex.new
      end

      def entries
        @lock.synchronize { @entries.dup }
      end

      def log(message, level)
        push(level, message)
      end

      def say(text)
        push(:say, text)
      end

      def header(title)
        push(:header, title)
      end

      private

      def push(level, text)
        @lock.synchronize { @entries << [level.to_sym, text.to_s.gsub(ANSI, "")] }
      end
    end

    # Every content file in the site's configured collections that lacks a
    # valid preview, in the order a run would visit them.
    def self.missing_previews(site_root)
      site = site_root!(site_root)
      config = Zer0ImageGenerator.read_config(site)
      root = project_root!(site, config)
      settings = Zer0ImageGenerator.resolve_settings(Args.build({}), config)
      runner = Runner.new(settings, root,
                          ctx: RunContext.new(project_root: root, env: {}),
                          logger: Logger.new(sink: Recorder.new))

      settings.collections.uniq.flat_map do |name|
        dir = runner.collection_path(name)
        next [] unless dir.directory?
        unless inside?(dir, site)
          raise Error, "collection '#{name}' resolves outside the site root: #{dir}"
        end

        runner.discover(dir).filter_map do |path|
          next unless inside?(path, site) # a symlink out of the site is not ours

          cf = Content.parse_front_matter(path, settings.front_matter_key)
          next if cf.nil?
          next if cf.preview && Content.check_preview_exists(cf.preview, settings, root)

          MissingPreview.new(path: path.to_s, relative: path.relative_path_from(site).to_s,
                             collection: name, title: cf.title, preview: cf.preview)
        end
      end
    end

    # Generate (or, with dry_run, plan) the preview for ONE content file.
    # `file` is absolute, or relative to the content root (`source:`), or
    # relative to the site root — tried in that order, as the CLI does.
    # `provider: nil` uses the site's configured provider.
    def self.generate_one(site_root, file, provider: "local", env: {}, dry_run: false)
      site = site_root!(site_root)
      config = Zer0ImageGenerator.read_config(site)
      root = project_root!(site, config)
      target = content_file!(site, root, file)

      args = Args.build(file: target.to_s, provider: provider, dry_run: dry_run ? true : false)
      settings = Zer0ImageGenerator.resolve_settings(args, config)
      unless inside?(root / settings.output_dir, site)
        raise Error, "output_dir resolves outside the site root: #{settings.output_dir}"
      end

      recorder = Recorder.new
      logger = Logger.new(sink: recorder)
      ctx = RunContext.new(project_root: root, env: string_env(env))
      runner = Runner.new(settings, root, ctx: ctx, logger: logger)
      error = nil
      begin
        CLI.validate_credentials(settings, ctx, logger: logger)
        FileUtils.mkdir_p((root / settings.output_dir).to_s) unless settings.dry_run
        exit_code = runner.run
      rescue ExitError => e
        error = e.message
        exit_code = e.status
      end

      stats = Stats::ATTRS.to_h { |name| [name, runner.stats.public_send(name)] }
      log = recorder.entries
      status =
        if error || stats[:errors].positive? then :error
        elsif stats[:generated].positive? then settings.dry_run ? :would_generate : :generated
        else :skipped
        end
      if status == :error && error.nil?
        error = log.select { |level, _| level == :warning }.map { |_, text| text.strip }.join("\n")
      end

      cf = Content.parse_front_matter(target, settings.front_matter_key)
      preview = cf&.preview
      image = preview && Content.find_preview_image(preview, settings, root)

      Generation.new(status: status, file: target.to_s, provider: settings.provider,
                     preview: preview, image: image && File.expand_path(image.to_s),
                     stats: stats, exit_code: exit_code, error: error, log: log)
    end

    # --- confinement -----------------------------------------------------------

    def self.site_root!(site_root)
      raise Error, "site root is required" if site_root.nil? || site_root.to_s.strip.empty?

      path = Pathname.new(File.expand_path(site_root.to_s))
      raise Error, "site root is not a directory: #{site_root}" unless path.directory?

      path
    end

    # Jekyll's `source:` shifts the content root; it may not leave the site.
    def self.project_root!(site, config)
      root = Zer0ImageGenerator.apply_source_root(site, config)
      raise Error, "source: resolves outside the site root: #{config['source']}" unless inside?(root, site)

      root
    end

    def self.content_file!(site, root, file)
      raise Error, "file is required" if file.nil? || file.to_s.strip.empty?

      raw = Pathname.new(file.to_s)
      candidates = raw.absolute? ? [raw] : [root / raw, site / raw]
      target = candidates.find(&:file?)
      raise Error, "content file not found: #{file}" if target.nil?

      target = Pathname.new(File.expand_path(target.to_s))
      raise Error, "content file is outside the site root: #{file}" unless inside?(target, site)

      target
    end

    # True when `path` — symlinks resolved, even for a not-yet-created tail —
    # is `root` or lies beneath it.
    def self.inside?(path, root)
      resolved = canonical(path).to_s
      base = canonical(root).to_s
      resolved == base || resolved.start_with?(base.end_with?("/") ? base : "#{base}/")
    end

    def self.canonical(path)
      probe = Pathname.new(File.expand_path(path.to_s))
      tail = []
      until probe.exist? || probe.root?
        tail.unshift(probe.basename.to_s)
        probe = probe.dirname
      end
      tail.inject(probe.realpath) { |acc, part| acc + part }
    end

    def self.string_env(env)
      (env || {}).to_h.each_with_object({}) do |(key, value), acc|
        acc[key.to_s] = value.to_s unless value.nil?
      end
    end

    private_class_method :site_root!, :project_root!, :content_file!, :inside?,
                         :canonical, :string_env
  end
end
