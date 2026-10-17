# frozen_string_literal: true

require "rexml/document"

module Zer0ImageGenerator
  module Svg
    # Deterministic SVG lint — a port of `tools/svg/svg-check.py`, which stays
    # the oracle.
    #
    # These are the checks you do not want to burn model tokens on: vision is
    # for composition, this is for correctness. The house rules it enforces
    # live in `.claude/rules/svg.md` (viewBox required, role="img" + <title>,
    # no raster/network payloads, coordinate sanity, live id references).
    #
    # Three things here are contract, not taste, because the PostToolUse hook
    # (`tools/svg/svg-hook.sh` via `.claude/settings.json`) consumes them:
    #   - exit 0 means clean, exit 1 means the write was rejected;
    #   - findings go to stderr as `WARN  …` / `ERROR …` lines, warnings first;
    #   - the exact wording is what Claude reads back as the reason to fix.
    # Rewording a message or reordering the findings changes what the model is
    # told, so both are pinned by the differential test against the Python.
    module Lint
      SVG_NS = "http://www.w3.org/2000/svg"
      XLINK = "http://www.w3.org/1999/xlink"

      # Same shape as svg-check.py's NUM. Ruby's `\d` is ASCII-only where
      # Python's is Unicode-aware; SVG number syntax is ASCII either way.
      NUM = /-?\d*\.?\d+(?:[eE][-+]?\d+)?/.freeze

      # Absolute-coordinate commands only — see #coords_in_path.
      PATH_SEGMENT = /[MLHVCSQTA][^A-Za-z]*/.freeze

      DEFAULT_MAX_KB = 250.0

      USAGE = "usage: lint [-h] [--max-kb MAX_KB] [--strict] path"

      # A finished lint run.
      #
      # `fatal` models svg-check.py's two early `return 1` paths (missing file,
      # unparseable XML): they print one ERROR line and never reach the
      # WARN/ERROR accumulation, so a fatal report deliberately discards any
      # findings gathered before the failure (the size check, notably).
      class Report
        attr_reader :path, :kilobytes, :errors, :warnings, :fatal

        def initialize(path:, kilobytes: 0.0, errors: [], warnings: [], fatal: nil, strict: false)
          @path = path
          @kilobytes = kilobytes
          @errors = errors
          @warnings = warnings
          @fatal = fatal
          @strict = strict
        end

        def strict? = @strict

        # Warnings are advisory in normal mode and fail the run under --strict;
        # that is the only difference between the two modes at the exit code.
        def exit_code
          return 1 if @fatal
          return 1 if !@errors.empty? || (@strict && !@warnings.empty?)

          0
        end

        def clean? = exit_code.zero?

        def stderr_lines
          return ["ERROR #{@fatal}"] if @fatal

          @warnings.map { |w| "WARN  #{w}" } + @errors.map { |e| "ERROR #{e}" }
        end

        # A run can be clean and still have warnings, and the "clean" line is
        # the hook's only positive signal, so it is emitted on stdout alone.
        def stdout_lines
          return [] unless clean?

          ["svg-check: #{@path} clean (#{format('%.1f', @kilobytes)}KB)"]
        end
      end

      class << self
        # The CLI shape of svg-check.py: returns the process exit code and
        # writes the same lines to the same streams. Callers that want the
        # findings as data should use .check instead.
        def run(argv, stdout: $stdout, stderr: $stderr)
          options = parse_argv(argv)
          return usage_error(stderr, options[:error]) if options[:error]

          if options[:help]
            stdout.puts(USAGE)
            return 0
          end

          report = check(options[:path], max_kb: options[:max_kb], strict: options[:strict])
          report.stderr_lines.each { |line| stderr.puts(line) }
          report.stdout_lines.each { |line| stdout.puts(line) }
          report.exit_code
        end

        def check(path, max_kb: DEFAULT_MAX_KB, strict: false)
          unless File.exist?(path)
            return Report.new(path: path, fatal: "missing file: #{path}", strict: strict)
          end

          check_source(File.binread(path), path: path, max_kb: max_kb, strict: strict)
        end

        # Same checks against an in-memory document. `path` only labels the
        # output, so a caller with SVG bytes in hand (a web request, say) never
        # has to round-trip through a tempfile.
        def check_source(source, path:, max_kb: DEFAULT_MAX_KB, strict: false)
          errors = []
          warnings = []
          kb = source.bytesize / 1024.0

          if kb > max_kb
            errors << "file is #{format('%.0f', kb)}KB, budget is #{format('%.0f', max_kb)}KB " \
                      "(run svgo, or reduce path precision)"
          end

          root = parse_root(source)
          if root.is_a?(String)
            return Report.new(path: path, kilobytes: kb, fatal: root, strict: strict)
          end

          errors << "root element is <#{root.name}>, expected <svg>" if root.name != "svg"

          viewbox = parse_viewbox(root)
          if viewbox.nil?
            errors << "no viewBox on root — the art will not scale. " \
                      'Add viewBox="0 0 W H".'
          end

          collect_root_findings(root, warnings)
          scan_elements(root, viewbox, strict, errors, warnings)

          Report.new(path: path, kilobytes: kb, errors: errors, warnings: warnings, strict: strict)
        end

        # Rough absolute-coordinate sample. Ignores relative commands on
        # purpose — we only want a cheap "is this wildly outside the canvas"
        # signal, not a path interpreter.
        def coords_in_path(data)
          out = []
          data.scan(PATH_SEGMENT) do |segment|
            nums = segment[1..].scan(NUM).map(&:to_f)
            case segment[0]
            when "M", "L" then out.concat(stride_pairs(nums, 0, 1, 2)) if nums.length >= 2
            when "C" then out.concat(stride_pairs(nums, 4, 5, 6))
            end
          end
          out
        end

        # A viewBox needs exactly four numbers; anything else is treated as
        # absent, matching the oracle (a 5-number viewBox is malformed anyway).
        def parse_viewbox(root)
          raw = plain_attribute(root, "viewBox")
          return nil if raw.nil? || raw.empty?

          parts = raw.scan(NUM).map(&:to_f)
          parts.length == 4 ? parts : nil
        end

        private

        # Returns the root element, or a String describing the fatal parse
        # failure. REXML happily returns a document with no root where
        # ElementTree raises, so the empty case is folded in here.
        def parse_root(source)
          root = REXML::Document.new(source).root
          return "not well-formed XML: no element found" if root.nil?

          root
        rescue REXML::ParseException => e
          # Mirrors svg-check.py's `except ET.ParseError` — the run stops here
          # rather than reporting on a half-built tree.
          "not well-formed XML: #{e.message}"
        end

        def collect_root_findings(root, warnings)
          kids = []
          root.elements.each { |child| kids << child.name }

          unless kids.include?("title")
            warnings << "no <title> as first child (screen readers, and it " \
                        "shows as a tooltip)"
          end
          warnings << 'missing role="img" on root' if plain_attribute(root, "role") != "img"
        end

        def scan_elements(root, viewbox, strict, errors, warnings)
          ids = []
          dupes = []
          used_refs = []
          ext_refs = []

          each_element(root) do |el|
            name = el.name

            id = plain_attribute(el, "id")
            if id && !id.empty?
              if ids.include?(id)
                dupes << id unless dupes.include?(id)
              else
                ids << id
              end
            end

            classify_href(el, name, used_refs, ext_refs, errors)

            el.attributes.each_attribute do |attribute|
              match = /\Aurl\(#([^)]+)\)/.match(attribute.value.to_s.strip)
              used_refs << match[1] if match
            end

            check_path(el, name, viewbox, warnings)

            if name == "text" && strict
              warnings << "<text> present — fonts are not guaranteed at " \
                          "render time. Convert to paths for distribution."
            end
          end

          finish(ids, dupes, used_refs, ext_refs, errors)
        end

        def classify_href(el, name, used_refs, ext_refs, errors)
          value = href(el)
          return if value.nil? || value.empty?

          if value.start_with?("#")
            used_refs << value[1..]
          elsif value.start_with?("http://", "https://", "//")
            ext_refs << value
          elsif value.start_with?("data:image") && name == "image"
            errors << "embedded raster <image> — that is a PNG in a " \
                      "trenchcoat, not vector art"
          elsif name == "image"
            errors << "external <image> reference: #{value}"
          end
        end

        def check_path(el, name, viewbox, warnings)
          return unless name == "path"

          data = plain_attribute(el, "d")
          return if data.nil? || data.empty?

          check_path_bounds(data, viewbox, warnings) if viewbox

          # Sub-pixel precision is invisible and triples file size; a handful
          # of long decimals is noise, a hundred is a generator that forgot to
          # round.
          if data.scan(/\d+\.\d{5,}/).length > 20
            warnings << "path data carries 5+ decimal places; round " \
                        "to 2-3 to cut file size ~40%"
          end
        end

        def check_path_bounds(data, viewbox, warnings)
          minx, miny, width, height = viewbox
          pad = [width, height].max * 2

          coords_in_path(data).each do |x, y|
            next if minx - pad <= x && x <= minx + width + pad &&
                    miny - pad <= y && y <= miny + height + pad

            warnings << "path coordinate (#{format('%g', x)},#{format('%g', y)}) is far outside the " \
                        "viewBox — likely a stray control point"
            break
          end
        end

        def finish(ids, dupes, used_refs, ext_refs, errors)
          errors << "external network references: #{ext_refs.first(3).join(', ')}" unless ext_refs.empty?
          errors << "duplicate id(s): #{dupes.sort.join(', ')}" unless dupes.empty?

          dangling = used_refs.uniq - ids
          return if dangling.empty?

          errors << "reference(s) to missing id(s): " \
                    "#{dangling.sort.join(', ')} — gradient or clipPath " \
                    "will silently render as black/none"
        end

        # ElementTree's iter() is a document-order walk that starts at the
        # receiver; REXML's each_recursive is the same walk minus the receiver.
        # Both yield elements only — comments and PIs are not visited.
        def each_element(root, &block)
          block.call(root)
          root.each_recursive(&block)
        end

        # ElementTree's `el.get("id")` matches the attribute whose serialized
        # name is exactly "id", i.e. the one in no namespace. REXML's
        # Attributes#[] can fall through to a prefixed attribute of the same
        # local name, and its Attribute#prefix inherits the element's prefix,
        # so neither is a faithful stand-in — compare expanded_name directly.
        def plain_attribute(el, name)
          el.attributes.each_attribute do |attribute|
            return attribute.value if attribute.expanded_name == name
          end
          nil
        end

        # The namespaced half of the same lookup: ElementTree keys these by
        # namespace URI, so the document's choice of prefix must not matter.
        def namespaced_attribute(el, uri, name)
          el.attributes.each_attribute do |attribute|
            prefix, separator, local = attribute.expanded_name.rpartition(":")
            next if separator.empty? # unprefixed attributes are in no namespace
            next unless local == name

            return attribute.value if el.namespace(prefix) == uri
          end
          nil
        end

        # Python's `or` falls through on an empty string too, so an empty
        # href="" still lets xlink:href be considered.
        def href(el)
          value = plain_attribute(el, "href")
          return value unless value.nil? || value.empty?

          namespaced_attribute(el, XLINK, "href")
        end

        # Python's zip() stops at the shorter leg; Ruby's Array#zip pads the
        # short one with nil, which would fabricate coordinates here.
        def stride_pairs(nums, x_offset, y_offset, step)
          xs = stride(nums, x_offset, step)
          ys = stride(nums, y_offset, step)
          Array.new([xs.length, ys.length].min) { |i| [xs[i], ys[i]] }
        end

        def stride(nums, offset, step)
          out = []
          i = offset
          while i < nums.length
            out << nums[i]
            i += step
          end
          out
        end

        def parse_argv(argv)
          options = { path: nil, max_kb: DEFAULT_MAX_KB, strict: false, help: false, error: nil }
          rest = argv.dup

          while (arg = rest.shift)
            case arg
            when "-h", "--help"
              options[:help] = true
              return options
            when "--strict"
              options[:strict] = true
            when "--max-kb"
              value = rest.shift
              return options.merge(error: "argument --max-kb: expected one argument") if value.nil?

              options[:max_kb] = parse_float(value) { |err| return options.merge(error: err) }
            when /\A--max-kb=(.*)\z/m
              value = Regexp.last_match(1)
              options[:max_kb] = parse_float(value) { |err| return options.merge(error: err) }
            else
              if options[:path] || arg.start_with?("-")
                return options.merge(error: "unrecognized arguments: #{arg}")
              end

              options[:path] = arg
            end
          end

          return options.merge(error: "the following arguments are required: path") if options[:path].nil?

          options
        end

        # Yields the argparse-shaped complaint rather than letting Float()'s
        # own ArgumentError escape as a backtrace.
        def parse_float(value)
          Float(value)
        rescue ArgumentError, TypeError
          yield "argument --max-kb: invalid float value: '#{value}'"
        end

        # argparse exits 2 for a usage error; the hook only distinguishes zero
        # from non-zero, but keeping 2 leaves that distinction available.
        def usage_error(stderr, message)
          stderr.puts(USAGE)
          stderr.puts("lint: error: #{message}")
          2
        end
      end
    end
  end
end
