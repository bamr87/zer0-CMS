# frozen_string_literal: true

module Studio
  # The SVG studio: drive the ported generators from web forms, render live,
  # and save keepers. Interactive renders are synchronous — the generators are
  # pure Ruby and finish in milliseconds — so only multi-seed sweeps are queued.
  class RendersController < ApplicationController
    def index
      @generators = StudioCatalog.generators
      @renders = StudioRender.recent.limit(60)
      @favorites = StudioRender.favorites.recent.limit(24)
    end

    def new
      @generator = StudioCatalog.find(params[:generator]) || StudioCatalog.generators.first
    end

    def show
      @render = StudioRender.find(params[:id])
    end

    # Render one piece into a Turbo Frame without persisting it — the studio's
    # inner loop, tweak-a-knob-and-look. Lint runs alongside so problems show
    # next to the picture, the way the authoring loop intends.
    def preview
      result = StudioRenderer.new(generator_params).render
      @svg = result.svg
      @lint = result.lint
      @meta = result.meta
      render partial: "studio/renders/preview", locals: { svg: @svg, lint: @lint, meta: @meta }
    rescue StudioRenderer::Error => e
      render partial: "studio/renders/error", locals: { message: e.message }, status: :unprocessable_entity
    end

    def create
      result = StudioRenderer.new(generator_params).render
      @render = StudioRender.create!(
        generator: result.meta[:generator],
        params: result.meta[:params],
        seed: result.meta[:seed],
        svg: result.svg,
        lint: result.lint,
      )
      redirect_to studio_render_path(@render), notice: "Saved."
    rescue StudioRenderer::Error => e
      redirect_back fallback_location: studio_root_path, alert: e.message
    end

    # Queue a contact sheet: N seeds through one generator, rasterized and
    # montaged. This one is a background Run because rasterizing dozens of
    # frames is the slow part.
    def sweep
      run = Run.create!(kind: "sweep", params: generator_params.merge(count: sweep_count))
      SweepJob.perform_later(run.id)
      redirect_to run_path(run), notice: "Sweep queued."
    end

    def favorite
      render = StudioRender.find(params[:id])
      render.update!(favorite: !render.favorite)
      redirect_back fallback_location: studio_root_path
    end

    def destroy
      StudioRender.find(params[:id]).destroy
      redirect_to studio_root_path, notice: "Deleted."
    end

    private

    def generator_params
      params.permit(:generator, :seed, :slug, knobs: {}).to_h.symbolize_keys
    end

    def sweep_count
      params.fetch(:count, 12).to_i.clamp(1, 48)
    end
  end
end
