# frozen_string_literal: true

require_relative "base"

module Zer0ImageGenerator
  # Shared sanitize -> write -> rasterize tail for SVG-producing providers
  # (local now; claude when that renderer lands). Mixed into a Provider.
  module SvgProviderMixin
    def finish_svg(svg_text, out_base, settings, ctx)
      begin
        clean, notes = Svg::Sanitizer.sanitize_svg(svg_text)
      rescue Svg::SvgError => exc
        return ImageResult.new(false, error: exc.message)
      end
      notes.each { |note| Logging.warn("SVG sanitizer: #{note}") }
      svg_path = out_base.sub_ext(".svg")
      png_path = out_base.sub_ext(".png")
      File.write(svg_path.to_s, clean)
      tool = Svg::Rasterizer.rasterize_svg(svg_path, png_path, ctx.project_root,
                                           preference: settings.rasterizer)
      if tool
        # missing_ok: the rasterizer already consumed the SVG on some backends.
        File.delete(svg_path.to_s) if File.exist?(svg_path.to_s)
        return ImageResult.new(true, "png", png_path)
      end
      Logging.warn(
        "No SVG rasterizer available — keeping the .svg preview. Social " \
        "og:image works best as PNG: install librsvg (`brew install librsvg`) " \
        "or Playwright (`npx playwright install chromium`)."
      )
      ImageResult.new(true, "svg", svg_path)
    end
  end

  # Network-free, deterministic renderer: it renders the local SVG, sanitizes
  # it, and rasterizes it. This is the path CI's integration job exercises.
  class LocalProvider < Provider
    include SvgProviderMixin

    def name
      "local"
    end

    def is_configured(_env)
      true
    end

    def missing_hint(_env)
      ""
    end

    def default_model
      "template-svg"
    end

    def generate(_prompt, settings, out_base, ctx)
      # `ctx.slug or out_base.stem`: an empty slug (Python-falsy) falls back to
      # the output stem for the seed, but the raw slug — empty or not — is still
      # what render_local_svg titles the banner with.
      seed_key = ctx.slug.to_s.empty? ? stem_of(out_base) : ctx.slug
      seed = Svg::LocalRenderer.seed_for(seed_key)
      svg_text = Svg::LocalRenderer.render_local_svg(ctx.slug, seed)
      finish_svg(svg_text, out_base, settings, ctx)
    end

    def edit(image_path, prompt, _settings, _ctx, _out_path = nil)
      # Historical behavior: the local provider "enhances" by doing nothing (no
      # API), so dry testing of --enhance needs no credentials.
      Logging.warn("Local provider: No actual enhancement. Logging prompt...")
      Logging.debug("Enhancement prompt: #{prompt[0, 400]}...")
      Logging.info("Placeholder: would enhance #{image_path}")
      ImageResult.new(true, "png", image_path)
    end

    private

    # Pathname has no #stem; Path.stem is the basename minus its final suffix.
    def stem_of(path)
      s = path.to_s
      File.basename(s, File.extname(s))
    end
  end
end
