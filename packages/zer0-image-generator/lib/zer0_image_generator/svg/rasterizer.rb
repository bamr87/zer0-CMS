# frozen_string_literal: true

require "open3"
require_relative "sanitizer" # for SVG_WIDTH / SVG_HEIGHT — export dimensions

module Zer0ImageGenerator
  module Svg
    # SVG -> PNG through the first available external tool. Chain and order are
    # a fidelity contract: rsvg-convert, then inkscape, then ImageMagick
    # (magick then convert), then the vendored Playwright/Chromium helper.
    module Rasterizer
      PNG_SIGNATURE = "\x89PNG\r\n\x1a\n".b

      class << self
        # debug() output is VERBOSE-gated in the Python; warn() always prints.
        # The real logging module lives outside this slice, so route through a
        # minimal, explicit stderr sink here (see DEVIATIONS in the port notes).
        attr_accessor :verbose
      end
      @verbose = false

      module_function

      def log_warn(msg)
        warn("[WARNING] #{msg}") # Kernel#warn -> $stderr
      end

      def log_debug(msg)
        warn("[DEBUG] #{msg}") if Rasterizer.verbose
      end

      # shutil.which equivalent, memoized like the Python's lru_cache: a batch
      # of N files must not pay N x 4 PATH scans. Returns the resolved path or
      # nil. Tool discovery is per-run stable, so the cache is never invalidated.
      def which(tool)
        @which_cache ||= {}
        return @which_cache[tool] if @which_cache.key?(tool)

        @which_cache[tool] = resolve_on_path(tool)
      end

      def resolve_on_path(tool)
        # A name with a directory component is checked directly, not searched.
        if tool.include?(File::SEPARATOR) ||
           (File::ALT_SEPARATOR && tool.include?(File::ALT_SEPARATOR))
          return executable_file?(tool) ? tool : nil
        end

        path = ENV["PATH"]
        return nil if path.nil? || path.empty?

        seen = {}
        path.split(File::PATH_SEPARATOR).each do |dir|
          next if dir.empty? || seen[dir]

          seen[dir] = true
          candidate = File.join(dir, tool)
          return candidate if executable_file?(candidate)
        end
        nil
      end

      def executable_file?(path)
        # os.access(X_OK) and not isdir: File.executable? is false for a
        # missing path, and File.file? rules out directories.
        File.file?(path) && File.executable?(path)
      end

      # Run a command with output captured and discarded; true on exit 0.
      # Mirrors _run_quiet: swallows OSError/timeout as a false result (with a
      # debug line) — explicitly, never a bare rescue.
      def run_quiet(cmd, cwd: nil, timeout: 120)
        opts = {}
        opts[:chdir] = cwd.to_s if cwd
        status = nil
        stderr_bytes = "".b
        begin
          Open3.popen3(*cmd, opts) do |stdin, stdout, stderr, wait_thr|
            stdin.close
            # Drain both pipes on threads so a chatty child can't deadlock on a
            # full pipe buffer while we wait.
            out_reader = Thread.new { stdout.read }
            err_reader = Thread.new { stderr.read }
            if wait_thr.join(timeout).nil?
              # subprocess.TimeoutExpired branch: kill, then report failure.
              begin
                Process.kill("KILL", wait_thr.pid)
              rescue Errno::ESRCH
                # Race: the child already exited between join and kill.
              end
              out_reader.join
              err_reader.join
              log_debug("rasterizer #{cmd[0]} failed: timeout after #{timeout}s")
              return false
            end
            status = wait_thr.value
            out_reader.join
            stderr_bytes = err_reader.value.to_s
          end
        rescue SystemCallError => exc
          # OSError family (e.g. the binary vanished between which() and spawn).
          log_debug("rasterizer #{cmd[0]} failed: #{exc}")
          return false
        end

        if status.exitstatus != 0
          snippet = stderr_bytes.dup.force_encoding("UTF-8").scrub[0, 200]
          log_debug("rasterizer #{cmd[0]} exit #{status.exitstatus}: #{snippet}")
          return false
        end
        true
      end

      # Locate the vendored Playwright helper. Candidate order mirrors the
      # Python: beside the engine (the gem layout, where it actually lives),
      # then the theme/curl layouts.
      def playwright_helper(project_root)
        engine_dir = File.expand_path("..", __dir__) # .../lib/zer0_image_generator
        candidates = [
          File.join(engine_dir, "rasterize-svg.js"),
          File.expand_path(File.join(engine_dir, "..", "dev", "rasterize-svg.js")),
          File.join(project_root.to_s, "scripts", "dev", "rasterize-svg.js"),
        ]
        candidates.find { |c| File.file?(c) }
      end

      CHOICES = %w[auto rsvg resvg inkscape magick playwright none].freeze

      # resvg — the closest headless match to browser rendering. Native `resvg`
      # first, then the `resvg-js` CLI; only an EXPLICIT `resvg` preference may
      # fall through to `npx -y`, because that downloads a package. Port of
      # _resvg_attempt.
      def resvg_attempt(svg_path, png_path, w, explicit)
        if which("resvg")
          return run_quiet(["resvg", "-w", w.to_s, svg_path, png_path])
        end
        if which("resvg-js")
          return run_quiet(["resvg-js", "--fit-width", w.to_s, svg_path, png_path])
        end
        if explicit && which("npx")
          return run_quiet(["npx", "-y", "@resvg/resvg-js-cli", "--fit-width", w.to_s,
                            svg_path, png_path], timeout: 300)
        end
        false
      end

      # SVG -> PNG through the first available tool. Returns the tool name used,
      # or nil when nothing worked (caller keeps the .svg). `width` sets the
      # output pixel width (height follows the banner aspect) — the oracle's
      # illustration loop renders the same file at 1536px and at 120px.
      def rasterize_svg(svg_path, png_path, project_root, preference: "auto", width: SVG_WIDTH)
        svg_path = svg_path.to_s
        png_path = png_path.to_s
        w = [1, width.to_i].max
        # int(round(...)) in the oracle — banker's rounding, hence :even.
        h = [1, (w * SVG_HEIGHT.to_f / SVG_WIDTH).round(half: :even)].max
        helper = playwright_helper(project_root)

        chain = [
          ["rsvg", lambda {
            which("rsvg-convert") && run_quiet(
              ["rsvg-convert", "-w", w.to_s, "-h", h.to_s, "-o", png_path, svg_path]
            )
          }],
          ["resvg", lambda { resvg_attempt(svg_path, png_path, w, preference == "resvg") }],
          ["inkscape", lambda {
            which("inkscape") && run_quiet(
              ["inkscape", svg_path, "--export-type=png",
               "--export-filename=#{png_path}", "-w", w.to_s, "-h", h.to_s]
            )
          }],
          ["magick", lambda {
            (which("magick") && run_quiet(
              ["magick", svg_path, "-resize", "#{w}x#{h}", png_path]
            )) ||
              (which("convert") && run_quiet(
                ["convert", svg_path, "-resize", "#{w}x#{h}", png_path]
              ))
          }],
          ["playwright", lambda {
            !helper.nil? && which("node") && run_quiet(
              ["node", helper.to_s, svg_path, png_path, w.to_s, h.to_s],
              cwd: project_root, timeout: 180
            )
          }],
        ]

        return nil if preference == "none"

        if preference != "auto"
          chain = chain.select { |entry| entry[0] == preference }
          if chain.empty?
            log_warn("Unknown rasterizer '#{preference}'")
            return nil
          end
        end

        chain.each do |name, attempt|
          next unless attempt.call

          begin
            if File.file?(png_path) && File.binread(png_path)[0, 8] == PNG_SIGNATURE
              log_debug("Rasterized with #{name}: #{File.basename(png_path)}")
              return name
            end
          rescue SystemCallError
            # OSError reading the file — fall through to unlink + next tool.
          end
          # png_path.unlink(missing_ok=True): drop a partial/invalid output.
          begin
            File.delete(png_path)
          rescue Errno::ENOENT
            # Already absent — nothing to remove.
          end
        end
        nil
      end
    end
  end
end
