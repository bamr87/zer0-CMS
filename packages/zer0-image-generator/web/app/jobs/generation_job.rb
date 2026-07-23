# frozen_string_literal: true

# Executes one preview-generation Run against a site.
#
# This is the web equivalent of `jekyll preview-images`: it resolves settings
# exactly as the CLI would (site config + the run's parameters), drives the
# same Runner, streams the log into the Run, and records the images that landed
# on disk. Because the engine is pure Ruby, "drive the engine" is a method call
# in this process — there is no second engine to keep in sync.
class GenerationJob < ApplicationJob
  queue_as :default

  def perform(run_id)
    run = Run.find(run_id)
    # A run cancelled while still queued should never start.
    return if run.status == "cancelled"

    site = run.site
    run.start!

    sink = RunLogSink.new(run)
    interrupt = DbInterrupt.new(run)
    config = EngineBridge.read_config(site.root)
    settings = EngineBridge.resolve_settings(engine_args(run), config)
    env = ENV.to_h.merge(Credential.environment)

    # _config.yml lives at the site root, but Jekyll's `source:` key shifts
    # where content and assets are. The engine applies that shift before the
    # Runner sees the root; every path below is derived from this ONE root so
    # the Runner, the output-dir creation, and the artifact scan never disagree.
    project_root = EngineBridge.project_root(site.root, config)

    runner = EngineBridge.runner(
      settings, project_root,
      sink: sink, interrupt: interrupt, env: env, verbose: run.params["verbose"]
    )

    # The engine creates the output directory at its CLI entry point, not in
    # the Runner — so a second driver (this job) has to do the same. Only the
    # write modes create it; dry_run and list_missing must touch nothing on
    # disk (CI asserts the output dir is never even created by a dry run).
    write_mode = %w[generate enhance].include?(run.kind)
    ensure_output_dir(project_root, settings) if write_mode

    before = output_snapshot(project_root, settings)
    exit_code = runner.run
    sink.flush!

    record_artifacts(run, project_root, settings, before) if write_mode

    stats = stats_hash(runner.stats)
    if Run.where(id: run.id).pick(:status) == "cancelled"
      run.update!(stats: stats, finished_at: Time.current)
    elsif exit_code.zero?
      run.finish!(stats: stats)
    else
      run.update!(status: "failed", stats: stats,
                  error: "Engine reported #{stats["errors"]} error(s) — see log.",
                  finished_at: Time.current)
    end

    site.update_column(:last_scanned_at, Time.current)
    broadcast_done(run)
  rescue EngineBridge::Error, StandardError => e
    sink&.flush!
    run&.fail!("#{e.class}: #{e.message}")
    broadcast_done(run) if run
    raise unless e.is_a?(EngineBridge::Error)
  end

  private

  # The engine's Stats exposes counters as accessors, not a hash — read the
  # five it tracks into plain strings for JSON storage on the Run.
  def stats_hash(stats)
    %i[processed generated enhanced skipped errors].to_h { |k| [k.to_s, stats.public_send(k)] }
  end

  # Translate a Run's stored parameters into the engine's Args shape. Only keys
  # the run actually set are passed, so the engine's own precedence fills the
  # rest from config and defaults.
  def engine_args(run)
    p = run.params
    args = {}
    args[:dry_run] = true if run.kind == "dry_run"
    args[:list_missing] = true if run.kind == "list_missing"
    args[:enhance] = true if run.kind == "enhance"
    args[:force] = true if p["force"]
    args[:verbose] = true if p["verbose"]
    args[:file] = p["file"] if p["file"].present?
    args[:collection] = p["collection"] if p["collection"].present?
    args[:provider] = p["provider"] if p["provider"].present?
    args[:model] = p["model"] if p["model"].present?
    args[:style] = p["style"] if p["style"].present?
    args[:parallel] = p["parallel"].to_i if p["parallel"].present?
    args[:batch] = p["batch"].to_i if p["batch"].present?
    args[:prompt_engine] = p["prompt_engine"] if p["prompt_engine"].present?
    args[:review] = p["review"] if p["review"].present?
    args[:rasterizer] = p["rasterizer"] if p["rasterizer"].present?
    args
  end

  # Files present in the output directory before the run, so afterward we can
  # tell which images this run wrote or changed rather than re-recording the
  # whole directory every time.
  def output_snapshot(project_root, settings)
    dir = output_dir(project_root, settings)
    return {} unless dir.directory?

    dir.glob("**/*.{png,svg}").to_h { |f| [f.to_s, f.mtime.to_f] }
  end

  def record_artifacts(run, project_root, settings, before)
    dir = output_dir(project_root, settings)
    return unless dir.directory?

    dir.glob("**/*.{png,svg}").each do |file|
      key = file.to_s
      # New file, or an existing one this run rewrote (mtime advanced).
      next if before[key] && before[key] >= file.mtime.to_f

      run.artifacts.create!(
        kind: file.extname.delete(".").downcase,
        path: key,
        byte_size: file.size,
        metadata: { provider: settings.provider }
      )
    end
  end

  def output_dir(project_root, settings)
    Pathname.new(project_root.to_s).join(settings.output_dir)
  end

  def ensure_output_dir(project_root, settings)
    FileUtils.mkdir_p(output_dir(project_root, settings).to_s)
  end

  def broadcast_done(run)
    Turbo::StreamsChannel.broadcast_replace_to(
      run, target: "run-header",
      partial: "runs/header", locals: { run: run.reload }
    )
  rescue StandardError
    nil
  end
end
