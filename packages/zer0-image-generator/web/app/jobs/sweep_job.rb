# frozen_string_literal: true

# Renders a generator across N seeds, saving each as a StudioRender and
# rasterizing a PNG so the run page can show a contact sheet.
#
# This is queued rather than synchronous because rasterizing dozens of frames
# (through the engine's rasterizer chain) is the slow part; a single live
# preview stays synchronous in the controller.
class SweepJob < ApplicationJob
  queue_as :default

  def perform(run_id)
    run = Run.find(run_id)
    return if run.status == "cancelled"

    run.start!
    sink = RunLogSink.new(run)
    params = run.params
    generator = params["generator"]
    count = params.fetch("count", 12).to_i.clamp(1, 48)
    base_seed = params.fetch("seed", 1).to_i
    knobs = params["knobs"] || {}

    sweep_dir = Rails.application.config.repo_root.join(".sweep", "studio", "run-#{run.id}")
    FileUtils.mkdir_p(sweep_dir)

    saved = 0
    count.times do |i|
      break if DbInterrupt.new(run).tripped?

      seed = base_seed + i
      sink.say("rendering #{generator} seed #{seed} (#{i + 1}/#{count})")
      result = StudioRenderer.new(generator: generator, seed: seed, knobs: knobs).render
      png_path = rasterize(result.svg, sweep_dir.join("#{generator}-#{seed}.svg"))

      render = StudioRender.create!(
        run: run, generator: generator, params: result.meta[:params],
        seed: seed, svg: result.svg, lint: result.lint
      )
      render.update!(png_path: png_path.to_s) if png_path
      run.artifacts.create!(kind: "png", path: png_path.to_s, byte_size: File.size(png_path)) if png_path
      saved += 1
    rescue StudioRenderer::Error => e
      sink.say("  seed #{seed} failed: #{e.message}")
    end

    sink.flush!
    run.finish!(stats: { "rendered" => saved, "requested" => count })
    broadcast_done(run)
  rescue StandardError => e
    sink&.flush!
    run&.fail!("#{e.class}: #{e.message}")
    broadcast_done(run) if run
    raise
  end

  private

  # Write the SVG and rasterize it with the engine's own chain. Returns the PNG
  # path, or nil if no rasterizer is available (the SVG is still saved).
  def rasterize(svg, svg_path)
    EngineBridge.load!
    File.write(svg_path.to_s, svg)
    png_path = svg_path.sub_ext(".png")
    tool = Zer0ImageGenerator::Svg::Rasterizer.rasterize_svg(
      svg_path, png_path, Rails.application.config.repo_root, preference: "auto"
    )
    tool ? png_path : nil
  ensure
    File.delete(svg_path.to_s) if File.exist?(svg_path.to_s) && File.exist?(svg_path.sub_ext(".png").to_s)
  end

  def broadcast_done(run)
    Turbo::StreamsChannel.broadcast_replace_to(
      run, target: "run-header", partial: "runs/header", locals: { run: run.reload }
    )
  rescue StandardError
    nil
  end
end
