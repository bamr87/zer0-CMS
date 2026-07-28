# frozen_string_literal: true

require "zlib"
require "set"
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
      # --- Content-aware banner art -----------------------------------------
      # Port of the banner section of preview_generator.py, which stays the
      # oracle. The renderer used to draw ONE composition (a retro skyline
      # under a sun) re-coloured per slug, so every banner on a site looked
      # like every other and none had anything to do with what the article
      # said. These compositions replace it: the page's own context picks the
      # composition AND the palette.
      #
      # Everything is authored at the banner frame, and every draw goes through
      # the seeded LCG — no clock, no Random, no environment.

      # [bg, far, mid, near, accent, glow]
      BANNER_PALETTES = {
        "neon" => %w[#0b0f17 #171b2e #2b2a5e #d946ef #22d3ee #f5f3ff],
        "ember" => %w[#120b16 #2d1b2e #5c2a4a #b3324b #f2542d #ffd166],
        "cyanic" => %w[#0b132b #1c2541 #1c7293 #5bc0be #9fd8d6 #e8f1f2],
        "moss" => %w[#101a14 #1b2f22 #2f5d3f #6f9e6f #a3c9a8 #e9edc9],
        "dusk" => %w[#1a1423 #2c1f3d #5c3a72 #a05fa8 #f5a623 #f7e8d3],
        "slate" => %w[#0d1117 #161b22 #26303d #4b6178 #7ea6c9 #dbe7f0],
      }.freeze
      BANNER_PALETTE_ORDER = %w[neon ember cyanic moss dusk slate].freeze

      # Matched as WHOLE WORDS, so section names must appear in the form a
      # section directory actually uses ('hacks', not 'hack').
      BANNER_KEYWORDS = [
        ["circuit", %w[hack hacks shell bash zsh cli terminal command script
                       docker container pipeline deploy git kernel server
                       network port cache sed awk grep ssh make compile]],
        ["pixelscene", %w[tool tools review reviews app editor game retro
                          install cheatsheet productivity keyboard plugin
                          extension terminal]],
        ["starfield", %w[security threat secret secrets token auth permission
                         permissions audit risk attack privacy explore journey
                         discover vulnerability credential sandbox]],
        ["lowpoly", %w[doc docs guide reference architecture design system
                       structure schema diagram overview spec concept concepts
                       glossary handbook]],
        ["flowfield", %w[note notes essay story ai agent agents robot automation
                         loop flow process thought retrospective lesson lessons
                         journal reflection]],
      ].freeze
      BANNER_COMPOSITION_ORDER = %w[circuit flowfield lowpoly pixelscene starfield].freeze

      BANNER_TAU = 6.283185307179586

      module_function

      # glibc LCG masked to 31 bits — the same determinism seam the rest of the
      # engine draws from. Returns a lambda so each composition owns its stream.
      def banner_lcg(seed)
        state = seed.nil? || seed.zero? ? 1 : seed
        lambda do |bound|
          state = ((state * 1103515245) + 12345) & 0x7FFFFFFF
          state % [bound, 1].max
        end
      end

      # Round for markup. Mirrors Python's f"{v:.Nf}".rstrip("0").rstrip(".")
      # exactly — the trailing-zero strip is what keeps the bytes identical.
      def banner_num(value, places = 1)
        text = format("%.#{places}f", value)
        text = text.sub(/0+\z/, "").sub(/\.\z/, "")
        text.empty? ? "0" : text
      end

      # Blend two #rrggbb strings. Integer output, so the bytes do not depend on
      # float formatting.
      def banner_mix(a, b, t)
        t = [[t, 0.0].max, 1.0].min
        out = +"#"
        [1, 3, 5].each do |i|
          ca = a[i, 2].to_i(16)
          cb = b[i, 2].to_i(16)
          out << format("%02x", (ca + ((cb - ca) * t) + 0.5).to_i)
        end
        out
      end

      # Trig by lookup table, built from a Taylor series rather than Math.sin:
      # libm rounds the last bit differently across platforms and runtimes, and
      # this file is pinned byte-for-byte against the Python. 256 entries is
      # 1.4 degrees — finer than a 1px step can express at this size.
      BANNER_SIN = []
      BANNER_COS = []
      256.times do |i|
        a = (i / 256.0) * BANNER_TAU
        t = a > 3.141592653589793 ? a - BANNER_TAU : a
        BANNER_SIN << (t - (t**3 / 6) + (t**5 / 120) - (t**7 / 5040) + (t**9 / 362880))
        BANNER_COS << (1 - (t**2 / 2) + (t**4 / 24) - (t**6 / 720) + (t**8 / 40320) -
                       (t**10 / 3628800))
      end
      BANNER_SIN.freeze
      BANNER_COS.freeze

      def banner_sin(angle)
        BANNER_SIN[(angle / BANNER_TAU * 256).to_i & 255]
      end

      def banner_cos(angle)
        BANNER_COS[(angle / BANNER_TAU * 256).to_i & 255]
      end

      # Smoothed value noise on a 17x17 lattice, sampled in unit coordinates.
      def banner_noise(seed)
        nxt = banner_lcg(seed ^ 0x9E3779B9)
        grid = Array.new(17) { Array.new(17) { nxt.call(1000) / 1000.0 } }
        lambda do |x, y|
          gx = x * 16.0
          gy = y * 16.0
          x0 = gx.to_i
          y0 = gy.to_i
          fx = gx - x0
          fy = gy - y0
          x1 = [x0 + 1, 16].min
          y1 = [y0 + 1, 16].min
          # smoothstep, so the field has no directional creases
          sx = fx * fx * (3 - (2 * fx))
          sy = fy * fy * (3 - (2 * fy))
          a = (grid[y0][x0] * (1 - sx)) + (grid[y0][x1] * sx)
          b = (grid[y1][x0] * (1 - sx)) + (grid[y1][x1] * sx)
          (a * (1 - sy)) + (b * sy)
        end
      end

      # `role="img"` plus a `<title>` first child is the house rule
      # (.claude/rules/svg.md) — without it a screen reader meets an unlabeled
      # graphic.
      def banner_frame(body, pal, title = "")
        label = (title.to_s.empty? ? "banner" : title.to_s)
                .gsub("&", "&amp;").gsub("<", "&lt;").gsub(">", "&gt;")
        %(<svg xmlns="#{SVG_NS}" viewBox="0 0 #{SVG_WIDTH} #{SVG_HEIGHT}" ) +
          %(width="#{SVG_WIDTH}" height="#{SVG_HEIGHT}" role="img">) +
          %(<title>Preview banner: #{label}</title>) +
          %(<rect width="#{SVG_WIDTH}" height="#{SVG_HEIGHT}" fill="#{pal[0]}" />) +
          %(#{body}</svg>)
      end

      # Streamlines advected through a noise field — organic and dense, with no
      # dead space anywhere in the frame.
      def banner_flowfield(seed, pal, title = "")
        nxt = banner_lcg(seed)
        noise = banner_noise(seed)
        w = SVG_WIDTH
        h = SVG_HEIGHT
        inks = [pal[3], pal[4], pal[5], pal[2]]
        out = []
        400.times do
          x = nxt.call(w + 240) - 120
          y = nxt.call(h + 240) - 120
          pts = [[x, y]]
          # Advance in SMALL steps so the curve stays faithful to the field, but
          # record only every third. Mapping the 0..1 noise onto ONE turn (not
          # two) keeps adjacent steps from flipping ~180 degrees, which would
          # otherwise stutter the line into a zigzag.
          96.times do |i|
            angle = noise.call([[x / w.to_f, 0.0].max, 1.0].min,
                               [[y / h.to_f, 0.0].max, 1.0].min) * BANNER_TAU
            x += banner_cos(angle) * 9
            y += banner_sin(angle) * 9
            break unless x > -140 && x < w + 140 && y > -140 && y < h + 140

            pts << [x, y] if (i % 3) == 2
          end
          next if pts.length < 5

          ink = inks[nxt.call(inks.length)]
          width = 0.5 + (nxt.call(18) / 10.0)
          opacity = 0.16 + (nxt.call(50) / 100.0)
          # Whole pixels: at these stroke widths a decimal is invisible and
          # costs two bytes on each of ~12k coordinate pairs.
          d = "M" + pts.map { |px, py| "#{px.to_i} #{py.to_i}" }.join(" L")
          out << %(<path d="#{d}" fill="none" stroke="#{ink}" ) +
                 %(stroke-width="#{banner_num(width)}" ) +
                 %(stroke-opacity="#{banner_num(opacity, 2)}" ) +
                 %(stroke-linecap="round" />)
        end
        banner_frame(out.join, pal, title)
      end

      # Faceted gradient field — calm and technical, fills the frame edge to
      # edge.
      def banner_lowpoly(seed, pal, title = "")
        nxt = banner_lcg(seed)
        noise = banner_noise(seed)
        w = SVG_WIDTH
        h = SVG_HEIGHT
        cols = 22
        rows = 15
        cw = w / cols.to_f
        ch = h / rows.to_f
        lattice = (0..rows).map do |r|
          (0..cols).map do |c|
            # Edge vertices stay pinned, or the background shows through.
            jx = [0, cols].include?(c) ? 0.0 : (nxt.call(60) - 30) / 100.0 * cw
            jy = [0, rows].include?(r) ? 0.0 : (nxt.call(60) - 30) / 100.0 * ch
            [(c * cw) + jx, (r * ch) + jy]
          end
        end

        # Ramp CONTINUOUSLY down the frame and let the noise only shade each
        # facet slightly. Discrete stops band the field into hard stripes and an
        # accent threshold scatters floating shards.
        ramp = [pal[1], pal[2], pal[3], pal[4]]
        facet_color = lambda do |t, n|
          pos = [[t, 0.0].max, 0.999].min * (ramp.length - 1)
          i = pos.to_i
          base = banner_mix(ramp[i], ramp[i + 1], pos - i)
          n > 0.5 ? banner_mix(base, pal[5], (n - 0.5) * 0.22)
                  : banner_mix(base, pal[0], (0.5 - n) * 0.30)
        end

        out = []
        rows.times do |r|
          cols.times do |c|
            a = lattice[r][c]
            b = lattice[r][c + 1]
            d = lattice[r + 1][c]
            e = lattice[r + 1][c + 1]
            [[a, b, d], [b, e, d]].each do |tri|
              cx = (tri[0][0] + tri[1][0] + tri[2][0]) / 3
              cy = (tri[0][1] + tri[1][1] + tri[2][1]) / 3
              color = facet_color.call(cy / h, noise.call(cx / w, cy / h))
              points = tri.map { |px, py| "#{banner_num(px)},#{banner_num(py)}" }.join(" ")
              # Stroke each facet in its own fill: float rounding otherwise
              # leaves hairline seams that render as stray light lines.
              out << %(<polygon points="#{points}" fill="#{color}" ) +
                     %(stroke="#{color}" stroke-width="1" />)
            end
          end
        end
        banner_frame(out.join, pal, title)
      end

      # Orthogonal traces, pads, vias and chips — a schematic read for the
      # shell/infrastructure end of a site.
      def banner_circuit(seed, pal, title = "")
        nxt = banner_lcg(seed)
        w = SVG_WIDTH
        h = SVG_HEIGHT
        step = 32
        out = []

        substrate = []
        (0..w).step(step * 2) { |x| substrate << "M#{x} 0 L#{x} #{h}" }
        (0..h).step(step * 2) { |y| substrate << "M0 #{y} L#{w} #{y}" }
        out << %(<path d="#{substrate.join(" ")}" stroke="#{pal[1]}" ) +
               %(stroke-width="1" fill="none" stroke-opacity="0.9" />)

        junctions = []
        64.times do
          # Snap to the grid so every trace is orthogonal by construction.
          x = nxt.call(w / step) * step
          y = nxt.call(h / step) * step
          segments = ["M#{x} #{y}"]
          junctions << [x, y]
          (3 + nxt.call(5)).times do
            if nxt.call(2) != 0
              x = [[x + ((nxt.call(11) - 5) * step), 0].max, w].min
              segments << "L#{x} #{y}"
            else
              y = [[y + ((nxt.call(9) - 4) * step), 0].max, h].min
              segments << "L#{x} #{y}"
            end
          end
          junctions << [x, y]
          ink = nxt.call(3) != 0 ? pal[4] : pal[3]
          out << %(<path d="#{segments.join(" ")}" fill="none" stroke="#{ink}" ) +
                 %(stroke-width="#{2 + nxt.call(3)}" stroke-opacity="0.85" ) +
                 %(stroke-linecap="square" stroke-linejoin="miter" />)
        end

        junctions.each do |px, py|
          out << %(<circle cx="#{px}" cy="#{py}" r="7" fill="#{pal[0]}" ) +
                 %(stroke="#{pal[4]}" stroke-width="3" />)
        end

        6.times do
          x = nxt.call((w / step) - 6) * step
          y = nxt.call((h / step) - 4) * step
          cw = (3 + nxt.call(3)) * step
          chh = (2 + nxt.call(2)) * step
          out << %(<rect x="#{x}" y="#{y}" width="#{cw}" height="#{chh}" rx="6" ) +
                 %(fill="#{pal[2]}" stroke="#{pal[5]}" stroke-width="2" />)
          (cw / step * 2).times do |leg|
            out << %(<rect x="#{x + 8 + (leg * (step / 2))}" y="#{y + chh}" ) +
                   %(width="6" height="10" fill="#{pal[5]}" />)
          end
        end
        banner_frame(out.join, pal, title)
      end

      # Constellations over layered ridges — the night-sky read.
      def banner_starfield(seed, pal, title = "")
        nxt = banner_lcg(seed)
        w = SVG_WIDTH
        h = SVG_HEIGHT
        horizon = (h * 0.72).to_i
        out = []

        230.times do
          x = nxt.call(w)
          y = nxt.call(horizon)
          # Thin the field toward the horizon so the sky reads as deep.
          next if nxt.call(horizon) < y * 0.75

          out << %(<circle cx="#{x}" cy="#{y}" r="#{1 + nxt.call(3)}" fill="#{pal[5]}" ) +
                 %(fill-opacity="#{banner_num(0.3 + (nxt.call(70) / 100.0), 2)}" />)
        end

        4.times do
          cx = 120 + nxt.call(w - 240)
          cy = 90 + nxt.call(horizon - 220)
          nodes = [[cx, cy]]
          (3 + nxt.call(3)).times do
            cx += nxt.call(220) - 90
            cy += nxt.call(180) - 80
            nodes << [cx, cy]
          end
          d = "M" + nodes.map { |nx, ny| "#{nx} #{ny}" }.join(" L")
          out << %(<path d="#{d}" fill="none" stroke="#{pal[4]}" ) +
                 %(stroke-width="2" stroke-opacity="0.55" />)
          nodes.each do |nx, ny|
            out << %(<circle cx="#{nx}" cy="#{ny}" r="5" fill="#{pal[4]}" />)
          end
        end

        mx = w - 260 - nxt.call(200)
        my = 150 + nxt.call(120)
        out << %(<circle cx="#{mx}" cy="#{my}" r="86" fill="#{pal[3]}" ) +
               %(fill-opacity="0.18" />)
        out << %(<circle cx="#{mx}" cy="#{my}" r="62" fill="#{pal[5]}" />)
        out << %(<circle cx="#{mx + 26}" cy="#{my - 16}" r="56" fill="#{pal[0]}" />)

        # Aerial perspective: the FARTHEST ridge is hazy and light, each nearer
        # one steps darker. Every layer closes to the bottom of the frame, so
        # the foreground is ridge mass rather than a flat band of background.
        4.times do |layer|
          top = horizon - 40 + (layer * 58)
          points = ["0,#{h}"]
          x = 0
          y = top.to_f
          while x <= w
            points << "#{x},#{banner_num(y)}"
            x += 40 + nxt.call(80)
            y = top + nxt.call(56) - 24
          end
          points << "#{w},#{banner_num(top.to_f)}"
          points << "#{w},#{h}"
          out << %(<polygon points="#{points.join(" ")}" ) +
                 %(fill="#{banner_mix(pal[3], pal[0], layer / 3.0)}" />)
        end
        banner_frame(out.join, pal, title)
      end

      # Pixel-art side-scroller on a strict integer grid, run-length merged.
      def banner_pixelscene(seed, pal, title = "")
        nxt = banner_lcg(seed)
        px = 16
        cols = SVG_WIDTH / px
        rows = SVG_HEIGHT / px
        cells = Array.new(rows) { Array.new(cols) }

        put = lambda do |cx, cy, color|
          cells[cy][cx] = color if cx >= 0 && cx < cols && cy >= 0 && cy < rows
        end
        block = lambda do |cx, cy, bw, bh, color|
          (cy...(cy + bh)).each do |yy|
            (cx...(cx + bw)).each { |xx| put.call(xx, yy, color) }
          end
        end

        ground = rows - 12
        150.times do
          sx = nxt.call(cols)
          sy = nxt.call(ground - 4)
          put.call(sx, sy, nxt.call(4) != 0 ? pal[5] : pal[3]) if nxt.call(ground) > sy
        end

        sun_x = cols - 20 + nxt.call(8)
        sun_y = 6 + nxt.call(5)
        (-4..4).each do |yy|
          (-4..4).each do |xx|
            d2 = (xx * xx) + (yy * yy)
            if d2 <= 16
              put.call(sun_x + xx, sun_y + yy, pal[4])
            elsif d2 <= 25
              put.call(sun_x + xx, sun_y + yy, pal[3])
            end
          end
        end

        # `surface` is the row the ground starts at; fill from there to the
        # bottom so the land is solid mass, not a one-cell scribble.
        surface = ground
        cols.times do |cx|
          surface = [[surface + nxt.call(3) - 1, ground - 5].max, rows - 4].min if nxt.call(4).zero?
          block.call(cx, surface, 1, rows - surface, pal[2])
          put.call(cx, surface, pal[3])
          put.call(cx, surface + 2 + nxt.call(4), pal[1]) if nxt.call(7).zero?
        end

        5.times do
          span = 5 + nxt.call(8)
          bx = nxt.call([cols - span, 1].max)
          by = ground - 9 - nxt.call(16)
          span.times do |i|
            put.call(bx + i, by, pal[3])
            put.call(bx + i, by + 1, pal[1])
          end
        end

        # The hero: 6x9 cells with a dark keyline, so it reads off any ground
        # colour and stays the only glow-coloured figure in frame.
        hx = 10 + nxt.call(14)
        hy = ground - 10
        block.call(hx - 1, hy - 1, 8, 11, pal[0])
        block.call(hx + 1, hy, 4, 2, pal[4])
        block.call(hx + 1, hy + 2, 4, 1, pal[1])
        block.call(hx, hy + 3, 6, 4, pal[5])
        block.call(hx + 2, hy + 4, 2, 2, pal[3])
        block.call(hx, hy + 7, 2, 3, pal[5])
        block.call(hx + 4, hy + 7, 2, 3, pal[5])
        block.call(hx + 6, hy + 1, 1, 6, pal[4])

        # Merge horizontal runs of one colour into single rects: a 96x64 scene
        # stays a few KB instead of six thousand one-cell rects.
        out = []
        rows.times do |y|
          x = 0
          while x < cols
            color = cells[y][x]
            if color.nil?
              x += 1
              next
            end
            run = 1
            run += 1 while x + run < cols && cells[y][x + run] == color
            out << %(<rect x="#{x * px}" y="#{y * px}" width="#{run * px}" ) +
                   %(height="#{px}" fill="#{color}" />)
            x += run
          end
        end
        body = %(<g shape-rendering="crispEdges">#{out.join}</g>)
        veil = (0...SVG_HEIGHT).step(6).map do |y|
          %(<rect y="#{y}" width="#{SVG_WIDTH}" height="2" />)
        end.join
        body += %(<g fill="#{pal[0]}" fill-opacity="0.22">#{veil}</g>)
        banner_frame(body, pal, title)
      end

      BANNER_COMPOSITIONS = {
        "circuit" => :banner_circuit,
        "flowfield" => :banner_flowfield,
        "lowpoly" => :banner_lowpoly,
        "pixelscene" => :banner_pixelscene,
        "starfield" => :banner_starfield,
      }.freeze

      BANNER_WORD = /[a-z0-9]+/.freeze

      # Whole words, lowercased. Substring matching is not good enough here: a
      # bare "ci" fires inside 'decision', 'specific' and 'efficiency', which is
      # enough to drag every article on a dev blog toward one look.
      def banner_words(text)
        text.to_s.downcase.scan(BANNER_WORD)
      end

      def banner_signature(article)
        [
          article["section"], article["categories"], article["title"],
          article["description"], article["body"].to_s[0, 600]
        ].map(&:to_s).join(" ").downcase
      end

      # Seed from the article's CONTENT, not just its filename — so retitling or
      # re-tagging a piece re-rolls its art, and two posts that merely sort next
      # to each other do not come out kin.
      def banner_seed_for(article)
        Zlib.crc32("#{banner_signature(article)}|#{article["slug"]}")
      end

      # (composition, palette) for an article. Keyword hits decide; the seed only
      # breaks ties and picks the palette, so the mapping stays legible.
      #
      # The fields are weighted, not pooled. A section name is a deliberate
      # editorial choice and the tags and title are hand-written, so they carry
      # most of the signal; the body is long, incidental, and full of words the
      # author never chose, so its whole contribution is capped.
      def banner_theme_for(article)
        fields = [
          [article["section"], 6],
          [article["categories"], 3],
          [article["title"], 3],
          [article["description"], 2],
          [article["body"].to_s[0, 4000], 1],
        ]
        scored = fields.map { |text, weight| [banner_words(text).to_set, weight] }
        seed = banner_seed_for(article)

        best_name = nil
        best_score = 0
        BANNER_KEYWORDS.each do |name, keywords|
          wanted = keywords.to_set
          score = 0
          scored.each do |words, weight|
            hits = (wanted & words).size
            # Cap the body's contribution: presence, not word count, is what the
            # low-weight field is evidence of.
            score += weight == 1 ? [hits, 4].min * weight : hits * weight
          end
          # Strictly greater, so ties fall to the earlier (more specific) entry.
          if score > best_score
            best_name = name
            best_score = score
          end
        end
        best_name ||= BANNER_COMPOSITION_ORDER[seed % BANNER_COMPOSITION_ORDER.length]

        [best_name, BANNER_PALETTE_ORDER[(seed >> 8) % BANNER_PALETTE_ORDER.length]]
      end

      # Deterministic banner for the `local` provider (no network).
      #
      # `article` carries the page's context (slug, section, title, tags, body);
      # it selects the composition and palette. Without it — a caller that only
      # has a slug — the art still renders, chosen from the seed alone.
      def render_local_svg(title, seed, article = nil)
        if article && !article.empty?
          composition, palette = banner_theme_for(article)
          art_seed = banner_seed_for(article)
        else
          composition = BANNER_COMPOSITION_ORDER[seed % BANNER_COMPOSITION_ORDER.length]
          palette = BANNER_PALETTE_ORDER[(seed >> 8) % BANNER_PALETTE_ORDER.length]
          art_seed = seed
        end
        public_send(BANNER_COMPOSITIONS[composition], art_seed, BANNER_PALETTES[palette], title)
      end
    end
  end
end
