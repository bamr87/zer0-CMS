# frozen_string_literal: true

require "fileutils"
require "optparse"
require_relative "local_renderer" # render_local_svg + the shared seed_for/palette/composition scheme
require_relative "sanitizer"      # sanitize_svg + SvgError — the REAL sanitizer, never a copy
require_relative "rasterizer"     # which() for montage discovery; rasterize_svg for the full sweep

module Zer0ImageGenerator
  module Svg
    # Parametric adapter over the engine's OWN `local` banner template — the
    # Ruby port of tools/svg/banner-seed.py, plus tools/svg/svg-sweep.sh's
    # contact-sheet stitching.
    #
    # The adapter is deliberately thin: a sweep must judge the REAL `local`
    # output, so it renders through LocalRenderer.render_local_svg and cleans
    # through the real Sanitizer.sanitize_svg — the exact path LocalProvider
    # ships (render_local_svg(slug, seed_for(slug)) -> sanitize_svg). It never
    # reimplements either, so a change to the template is seen on true output
    # instead of a lookalike.
    #
    # BYTE-IDENTITY (see test/ruby/test_banner_seed.rb):
    #   * The PRE-sanitize render is byte-identical to the Python adapter's —
    #     render_local_svg is a hard determinism contract (seeded LCG only).
    #   * The FINAL sanitized string is the SAME DOM but NOT byte-identical: the
    #     ported Sanitizer serializes via REXML (single quotes, alphabetized
    #     attributes, spaced self-closing tags) where Python uses ElementTree.
    #     That serializer difference is owned and documented by the sanitizer
    #     slice; this adapter inherits it. The test proves DOM byte-identity by
    #     canonicalizing both outputs through REXML.
    module BannerSeed
      # argparse defaults from banner-seed.py.
      DEFAULT_SEED = 1
      DEFAULT_OUT = ".sweep/banner.svg"

      # OptionParser token for a base-10 integer flag (see main). A bare token
      # object is all OptionParser#accept needs as the type key.
      Base10Int = Object.new

      # svg-sweep.sh's `montage` knobs, verbatim: a dark contact sheet, filename
      # labels, fixed 400px cells with 8px gutters. The tile column count is
      # per-run (ceil(sqrt(N))), so it is computed, not stored here.
      MONTAGE_LABEL = "%f"
      MONTAGE_BACKGROUND = "#111"
      MONTAGE_FILL = "#eee"
      MONTAGE_GEOMETRY = "400x400+8+8"

      # Raised when a contact sheet is requested but ImageMagick's `montage` is
      # not on PATH. svg-sweep.sh exits 127 for this; as a library we surface it
      # as an explicit, actionable error rather than an exit code. ImageMagick
      # is an OPTIONAL dependency — everything else here runs without it.
      class MontageMissing < StandardError; end

      module_function

      # seed_for lives on LocalRenderer (the shared seed -> palette/composition
      # contract also used by the claude provider). Re-exposed so the studio and
      # CLI resolve slugs without reaching across modules. zlib.crc32 of the
      # UTF-8 bytes; matches pg.seed_for exactly.
      def seed_for(slug)
        LocalRenderer.seed_for(slug)
      end

      # banner-seed.py's (title, seed) rule. A non-empty --slug wins and
      # reproduces that post's banner (title = slug, seed derived as the engine
      # derives it); otherwise a bare --seed drives the palette/composition
      # scheme directly under a synthetic "banner-seed-N" title. Returns
      # [title, seed]. Empty-string slug is falsy exactly as `if args.slug:` is.
      def resolve(seed: DEFAULT_SEED, slug: "")
        if slug.nil? || slug.empty?
          ["banner-seed-#{seed}", seed]
        else
          [slug, seed_for(slug)]
        end
      end

      # Core operation, == pg.sanitize_svg(pg.render_local_svg(title, seed)).
      # Returns [svg_text, notes]; notes is the sanitizer's warnings list.
      def generate(seed: DEFAULT_SEED, slug: "")
        title, resolved = resolve(seed: seed, slug: slug)
        Sanitizer.sanitize_svg(LocalRenderer.render_local_svg(title, resolved))
      end

      # Just the sanitized SVG string — the studio's common case. Notes are
      # dropped; for the local template they are always empty (it renders SVG
      # the sanitizer accepts untouched). Callers needing notes use #generate.
      def svg(seed: DEFAULT_SEED, slug: "")
        generate(seed: seed, slug: slug).first
      end

      # Rails "SVG studio" entry point: hand back one result per seed with no
      # shelling out. Each entry is { seed:, title:, svg:, notes: }. Accepts any
      # Enumerable of seeds (a form may request an arbitrary set, not a range).
      def render_many(seeds)
        seeds.map do |seed|
          svg_text, notes = generate(seed: seed)
          { seed: seed, title: "banner-seed-#{seed}", svg: svg_text, notes: notes }
        end
      end

      # svg-sweep.sh's sweep shape: seeds `first .. first+count-1` (the bash
      # sweeps 1..N). Returns the same { seed:, title:, svg:, notes: } records.
      def sweep(count, first: 1)
        raise ArgumentError, "count must be non-negative" if count.negative?

        render_many(first...(first + count))
      end

      # File-writing half of banner-seed.py: make the parent dir, write UTF-8,
      # emit sanitizer notes to `err`. Returns the out path (what the CLI prints
      # to stdout). Separate from #generate so the studio never touches disk.
      def write(out, seed: DEFAULT_SEED, slug: "", err: $stderr)
        svg_text, notes = generate(seed: seed, slug: slug)
        notes.each { |note| err.puts("sanitizer: #{note}") }
        # os.makedirs(dirname(out) or ".", exist_ok=True): dirname("banner.svg")
        # is "" -> ".", and mkdir_p(".") is a harmless no-op.
        dir = File.dirname(out)
        FileUtils.mkdir_p(dir.empty? ? "." : dir)
        # The SVG string is UTF-8; write its bytes as-is (Python opens utf-8).
        File.write(out, svg_text)
        out
      end

      # CLI port of banner-seed.py's main(): parse --seed/--slug/--out, write the
      # file, print the out path to `out`. Returns a process exit code (0 on
      # success, 2 on a bad argument, mirroring argparse). Exposed so a bin/ shim
      # or a test can drive the exact documented CLI surface without a subprocess.
      def main(argv, out: $stdout, err: $stderr)
        opts = { seed: DEFAULT_SEED, slug: "", out: DEFAULT_OUT }
        parser = OptionParser.new do |p|
          # Base-10, like Python argparse's `type=int` (int()). OptionParser's
          # built-in Integer accepts 0x/0o/0b prefixes, so `--seed 010` would be
          # octal 8 in Ruby but decimal 10 in Python — a different banner.
          p.accept(Base10Int, /\A\s*[-+]?\d+\s*\z/) { |s| Integer(s.strip, 10) }
          p.on("--seed N", Base10Int) { |v| opts[:seed] = v }
          p.on("--slug SLUG", String, "derive the seed from a post slug, as the engine does") do |v|
            opts[:slug] = v
          end
          p.on("--out PATH", String) { |v| opts[:out] = v }
        end
        begin
          parser.parse(argv)
        rescue OptionParser::ParseError => exc
          # argparse writes usage + error to stderr and exits 2. Mirror the exit
          # code with an explicit message; never swallow the parse failure.
          err.puts(exc.message)
          return 2
        end
        out.puts(write(opts[:out], seed: opts[:seed], slug: opts[:slug], err: err))
        0
      end

      # ---- svg-sweep.sh contact-sheet logic --------------------------------

      # ceil(sqrt(N)) — svg-sweep.sh's column count. Own method so the sweep and
      # any caller building a montage agree on layout. Math.sqrt(N).ceil matches
      # Python's math.ceil(math.sqrt(N)) (both IEEE-754, exact on perfect squares).
      def tile_columns(count)
        Math.sqrt(count).ceil
      end

      # `command -v montage` equivalent, via the ported Rasterizer.which (itself
      # shutil.which-equivalent and memoized). nil when ImageMagick is absent.
      def montage_path
        Rasterizer.which("montage")
      end

      def montage_available?
        !montage_path.nil?
      end

      # The exact `montage` argv from svg-sweep.sh, as an array (no shell). Built
      # separately from #contact_sheet so the flag set can be asserted without
      # ImageMagick installed. `bin` defaults to the plain name for that offline
      # inspection; #contact_sheet passes the resolved absolute path.
      def montage_argv(png_paths, out:, columns: nil, bin: "montage")
        cols = columns || tile_columns(png_paths.length)
        [bin, "-label", MONTAGE_LABEL,
         "-background", MONTAGE_BACKGROUND, "-fill", MONTAGE_FILL,
         "-tile", "#{cols}x", "-geometry", MONTAGE_GEOMETRY,
         *png_paths.map(&:to_s), out.to_s]
      end

      # Stitch PNGs into one labelled contact sheet via ImageMagick `montage`.
      # ImageMagick is optional: when `montage` is absent this raises
      # MontageMissing with an actionable message instead of failing obscurely.
      # Returns the output path on success.
      def contact_sheet(png_paths, out:, columns: nil)
        montage = montage_path
        unless montage
          raise MontageMissing,
                "ImageMagick 'montage' not found on PATH; install ImageMagick " \
                "(e.g. `brew install imagemagick`) to stitch contact sheets"
        end
        raise ArgumentError, "no PNGs to montage" if png_paths.empty?

        cmd = montage_argv(png_paths, out: out, columns: columns, bin: montage)
        # system returns false on non-zero exit; surface it rather than pretend
        # the sheet was written.
        unless system(*cmd)
          raise "montage exited #{$?.exitstatus} building #{out}"
        end

        out
      end

      # Full svg-sweep.sh pipeline in Ruby, opt-in: render seeds 1..count to SVG
      # under `dir`, rasterize each to PNG, then montage them into one sheet.
      # Returns the contact-sheet path.
      #
      # The SVG->PNG step delegates to the engine's Rasterizer (another slice);
      # the dev-side svg-render.sh chain (400px, ImageMagick-free) is not
      # separately ported, so this reuses the engine chain and lets `montage`'s
      # -geometry downscale to the same 400px cells. Both external tools are
      # optional: an empty render set or a missing montage raises explicitly.
      # The studio uses #sweep (in-memory) instead of this disk+subprocess path.
      def sweep_contact_sheet(count, dir: ".sweep", preview_dir: ".preview",
                              project_root: Dir.pwd)
        FileUtils.rm_rf(dir)
        FileUtils.mkdir_p(dir)
        FileUtils.mkdir_p(preview_dir)

        pngs = []
        (1..count).each do |seed|
          svg_path = File.join(dir, "seed-#{seed}.svg")
          write(svg_path, seed: seed)
          png_path = File.join(preview_dir, "seed-#{seed}.png")
          # Only montage what actually rasterized; unlike the bash's stale
          # `.preview/seed-*.png` glob, this feeds exactly this run's outputs.
          pngs << png_path if Rasterizer.rasterize_svg(svg_path, png_path, project_root)
        end
        if pngs.empty?
          raise "no PNGs rendered; install a rasterizer " \
                "(resvg / rsvg-convert / inkscape / cairosvg) to sweep"
        end

        contact_sheet(pngs, out: File.join(dir, "contact-sheet.png"))
      end
    end
  end
end
