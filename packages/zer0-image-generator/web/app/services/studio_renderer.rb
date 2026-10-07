# frozen_string_literal: true

# Bridges web form params to the ported SVG generators.
#
# Each generator has its own `build` signature, so this is where the studio's
# uniform {generator, seed, knobs} shape is translated into the specific
# positional call each one expects. Output is always sanitized (external-facing
# safety) and linted (so the UI can show findings), matching what the authoring
# loop does on disk.
class StudioRenderer
  class Error < StandardError; end

  Result = Struct.new(:svg, :lint, :meta, keyword_init: true)

  def initialize(params)
    @generator = params[:generator].to_s
    raw_seed = params[:seed].presence || catalog&.knobs&.find { |k| k.key == "seed" }&.default || 1
    # Base 10 explicitly: bare Integer("010") is octal in Ruby, so a leading
    # zero would silently pick a different seed — and thus different art — than
    # the number the user typed.
    @seed = raw_seed.is_a?(Integer) ? raw_seed : Integer(raw_seed.to_s.strip, 10)
    @slug = params[:slug].to_s
    @knobs = (params[:knobs] || {}).to_h.transform_keys(&:to_s)
  rescue ArgumentError, TypeError
    raise Error, "Seed must be an integer."
  end

  def render
    raise Error, "Unknown generator: #{@generator}" unless catalog

    # The generators, sanitizer, and linter live in the engine; make sure it is
    # loaded rather than assuming some other request already pulled it in.
    EngineBridge.load!
    begin
      raw = build_svg
      svg = Zer0ImageGenerator::Svg::Sanitizer.sanitize_svg(raw).first
      Result.new(svg: svg, lint: lint_of(svg), meta: meta)
    rescue Zer0ImageGenerator::Svg::SvgError => e
      raise Error, "Generator produced invalid SVG: #{e.message}"
    end
  end

  private

  def catalog = StudioCatalog.find(@generator)

  # Effective seed: a banner slug, when given, derives the seed via the same
  # crc32 the engine uses, so the studio matches what a real post would get.
  def effective_seed
    if @generator == "banner" && @slug.present?
      Zer0ImageGenerator::Svg::LocalRenderer.seed_for(@slug)
    else
      @seed
    end
  end

  def gen = Zer0ImageGenerator::Svg::Generators

  def build_svg
    case @generator
    when "banner"
      title = @slug.presence || "seed #{@seed}"
      Zer0ImageGenerator::Svg::LocalRenderer.render_local_svg(title, effective_seed)
    when "flowfield"
      gen::Flowfield.build(@seed, 800, 800, int(:lines, 240), int(:steps, 70), float(:scale, 180.0), enum(:palette, "cyanic"))
    when "lsystem"
      gen::Lsystem.build(@seed, enum(:species, "bush"), enum(:palette, "verdant"), optional_int(:iters))
    when "lowpoly"
      gen::Lowpoly.build(@seed, enum(:palette, "dusk"), int(:cols, 16), int(:rows, 11))
    when "mandala"
      gen::Mandala.build(@seed, enum(:palette, "jewel"))
    when "starmap"
      gen::Starmap.build(@seed)
    when "invaders"
      gen::Invaders.build(@seed, enum(:palette, "cyanic"))
    when "pixelquest"
      gen::PixelQuest.build(@seed, enum(:palette, "dusk"))
    else
      raise Error, "Unknown generator: #{@generator}"
    end
  end

  def lint_of(svg)
    report = Zer0ImageGenerator::Svg::Lint.check_source(svg, path: "#{@generator}-#{effective_seed}.svg")
    { "errors" => report.errors, "warnings" => report.warnings, "kilobytes" => report.kilobytes,
      "clean" => report.clean? }
  rescue StandardError => e
    # A linter crash must not take down the render — surface it as a warning
    # rather than a 500, since the picture is still valid to look at.
    { "errors" => [], "warnings" => ["lint unavailable: #{e.message}"], "clean" => false }
  end

  def meta
    { generator: @generator, seed: effective_seed, slug: @slug.presence, params: presented_knobs }
  end

  def presented_knobs
    catalog.knobs.each_with_object({}) do |knob, acc|
      next if knob.key == "seed"

      value = @knobs[knob.key]
      acc[knob.key] = value if value.present?
    end
  end

  def int(key, default)
    v = @knobs[key.to_s]
    v.present? ? Integer(v) : default
  rescue ArgumentError
    raise Error, "#{key} must be an integer."
  end

  def optional_int(key)
    v = @knobs[key.to_s]
    v.present? ? Integer(v) : nil
  rescue ArgumentError
    raise Error, "#{key} must be an integer."
  end

  def float(key, default)
    v = @knobs[key.to_s]
    v.present? ? Float(v) : default
  rescue ArgumentError
    raise Error, "#{key} must be a number."
  end

  # Enum knobs come from a fixed choice list; reject anything else rather than
  # passing an unknown palette into a generator that would KeyError on it.
  def enum(key, default)
    knob = catalog.knobs.find { |k| k.key == key.to_s }
    v = @knobs[key.to_s].presence || default
    return default unless knob&.choices

    knob.choices.include?(v) ? v : default
  end
end
