# frozen_string_literal: true

require "zlib"
require_relative "sanitizer" # for SVG_NS / SVG_WIDTH / SVG_HEIGHT — the shared geometry contract

module Zer0ImageGenerator
  module Svg
    # Deterministic local banner renderer. HARD CONTRACT (.claude/rules/svg.md):
    # same slug -> byte-identical banner. Every random draw goes through the
    # seeded LCG (nxt); nothing here may touch a clock, a real RNG, or the
    # environment. The seed -> palette/composition scheme (seed_for /
    # palette_for / composition_for) is shared with the claude provider and is
    # a cross-slice contract — changing it re-skins every existing banner.
    module LocalRenderer
      # Curated retro palettes: [sky/background, far, mid, near, accent, glow].
      # Selected deterministically per slug so re-runs stay visually stable.
      RETRO_PALETTES = [
        %w[#1a1a2e #16213e #0f3460 #533483 #e94560 #f9ed69],
        %w[#0d1b2a #1b263b #415a77 #778da9 #e0e1dd #ffb703],
        %w[#2d132c #801336 #c72c41 #ee4540 #f9d276 #f4f4f4],
        %w[#10002b #3c096c #7b2cbf #c77dff #e0aaff #72efdd],
        %w[#001219 #005f73 #0a9396 #94d2bd #e9d8a6 #ee9b00],
        %w[#03071e #370617 #9d0208 #dc2f02 #f48c06 #ffba08],
        %w[#0b132b #1c2541 #3a506b #5bc0be #6fffe9 #ff6b6b],
        %w[#232931 #393e46 #4ecca3 #a5ecd7 #eeeeee #f95959],
        %w[#1f0a24 #571089 #ab51e3 #f7aef8 #b388eb #8093f1],
        %w[#141e30 #243b55 #3c6382 #82ccdd #f8c291 #e55039],
      ].freeze

      # Only the length matters to render_local_svg (variant selection), but the
      # full list is the shared contract also consumed by composition_for.
      COMPOSITION_VARIANTS = [
        "a low horizon with a huge rising sun disk banded by scanlines",
        "layered diagonal mountain silhouettes receding into haze",
        "a vaporwave perspective grid floor vanishing toward the horizon",
        "floating terraced islands with cascading pixel waterfalls",
        "a night starfield with a large ringed planet arcing across the frame",
        "a stepped city skyline of blocky towers with lit windows",
        "rolling desert dunes with a lone monolith and long shadows",
        "an ocean of chunky pixel waves under drifting square clouds",
      ].freeze

      module_function

      # zlib.crc32(slug.encode("utf-8")) == Ruby Zlib.crc32(slug). Zlib.crc32
      # already returns a non-negative 32-bit int, so no masking is needed to
      # match CPython's unsigned crc32.
      def seed_for(slug)
        Zlib.crc32(slug)
      end

      def palette_for(seed)
        RETRO_PALETTES[seed % RETRO_PALETTES.length]
      end

      def composition_for(seed)
        COMPOSITION_VARIANTS[(seed >> 8) % COMPOSITION_VARIANTS.length]
      end

      # Deterministic retro-landscape SVG for the `local` provider (no network).
      #
      # Shares the claude provider's seed -> palette/composition scheme so the
      # two stay visually kin per slug. BYTE-IDENTICAL to Python's
      # render_local_svg for the same (title, seed) — verified over 200+ slugs
      # by test/ruby/test_local_renderer.rb.
      def render_local_svg(title, seed)
        pal = palette_for(seed)
        variant = (seed >> 8) % COMPOSITION_VARIANTS.length
        # Python `seed or 1`: a zero seed (crc32 of "") would freeze the LCG.
        rng = seed.zero? ? 1 : seed

        # Seeded LCG — glibc's constants. The & 0x7FFFFFFF mask keeps rng a
        # non-negative 31-bit int; Ruby's arbitrary-precision ints make the
        # mask (not overflow) the thing that bounds the value, so it must land
        # in exactly the same place as the Python. `%` on non-negative operands
        # matches Python. nxt draws MUST happen in the same order as the Python
        # or the whole stream desynchronizes.
        nxt = lambda do |bound|
          rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
          rng % [bound, 1].max
        end

        w = SVG_WIDTH
        h = SVG_HEIGHT
        safe_title = title.gsub("&", "&amp;").gsub("<", "&lt;")
        parts = [
          %(<svg xmlns="#{SVG_NS}" viewBox="0 0 #{w} #{h}" width="#{w}" height="#{h}" ) +
            %(role="img">),
          %(<title>Preview banner: #{safe_title}</title>),
          %(<rect width="#{w}" height="#{h}" fill="#{pal[0]}"/>),
        ]
        # Sky bands. opacity is string-built as "0." + (25 + i*12): 0.25/0.37/0.49.
        band_h = h / 8
        (0...3).each do |i|
          parts << %(<rect y="#{i * band_h}" width="#{w}" height="#{band_h}" ) +
                   %(fill="#{pal[1]}" opacity="0.#{25 + i * 12}"/>)
        end
        # Celestial body with stepped "pixel" rings. Draw order: cx, cy, radius.
        cx = w - 320 - nxt.call(400)
        cy = 240 + nxt.call(160)
        radius = 130 + nxt.call(80)
        [pal[5], pal[4]].each_with_index do |ring_color, i|
          parts << %(<circle cx="#{cx}" cy="#{cy}" r="#{radius - i * 26}" fill="#{ring_color}"/>)
        end
        # Scanline stripes across the disk (clipped to the circle's chord width).
        (0...3).each do |i|
          y = cy + 12 + i * 26
          dy = (y + 5 - cy).abs
          next if dy >= radius

          # int(sqrt) via ** 0.5 then truncate-toward-zero, mirroring Python's
          # int((...)**0.5). Differential-tested against pow over the domain.
          half = ((radius * radius - dy * dy)**0.5).to_i
          parts << %(<rect x="#{cx - half}" y="#{y}" width="#{half * 2}" height="10" fill="#{pal[0]}"/>)
        end
        # Layered terrain: three silhouette ranges of blocky steps.
        [pal[2], pal[3], pal[1]].each_with_index do |color, layer|
          base = h - 120 - layer * 170
          x = -40
          points = ["-40,#{h}"]
          while x < w + 80
            # Draw order inside the loop: peak (nxt 300) then width_step (nxt 150).
            peak = base - nxt.call(300) - (2 - layer) * 70
            width_step = 90 + nxt.call(150)
            points << "#{x},#{peak}"
            points << "#{x + width_step},#{peak}"
            x += width_step
          end
          points << "#{w + 80},#{h}"
          parts << %(<polygon points="#{points.join(' ')}" fill="#{color}"/>)
        end
        # Variant flourish: grid floor for even variants, stars for odd.
        if variant.even?
          (1...7).each do |i|
            y = h - i * (i * 8)
            parts << %(<rect y="#{y}" width="#{w}" height="3" fill="#{pal[4]}" opacity="0.35"/>)
          end
        else
          40.times do
            # Draw order: sx (nxt w), sy (nxt h/2), size (nxt 5).
            sx = nxt.call(w)
            sy = nxt.call(h / 2)
            size = 3 + nxt.call(5)
            parts << %(<rect x="#{sx}" y="#{sy}" width="#{size}" height="#{size}" fill="#{pal[4]}"/>)
          end
        end
        # CRT scanline veil + vignette bars.
        (0...h).step(8) do |y|
          parts << %(<rect y="#{y}" width="#{w}" height="1" fill="#000" opacity="0.10"/>)
        end
        parts << %(<rect width="#{w}" height="26" fill="#000" opacity="0.35"/>)
        parts << %(<rect y="#{h - 26}" width="#{w}" height="26" fill="#000" opacity="0.35"/>)
        parts << "</svg>"
        parts.join
      end
    end
  end
end
