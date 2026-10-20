# frozen_string_literal: true

# Tests for the deterministic SVG linter port (lib/zer0_image_generator/svg/lint.rb).
#
#     ruby -Ilib test/ruby/test_svg_lint.rb
#
# Two layers:
#   1. Branch unit tests that pin the exact message text and exit code of every
#      check, using in-memory SVG so they run with no python3 and no files.
#   2. A differential test that runs the Python oracle (tools/svg/svg-check.py)
#      and this port over every committed .svg in both normal and --strict mode
#      and asserts identical exit code, stdout, and stderr. Skips cleanly if
#      python3 is unavailable.

require "minitest/autorun"
require "open3"
require "stringio"
require_relative "../../lib/zer0_image_generator/svg/lint"

module Zer0ImageGenerator
  module Svg
    class LintBranchTest < Minitest::Test
      Lint = Zer0ImageGenerator::Svg::Lint

      def report(svg, strict: false)
        Lint.check_source(svg, path: "mem.svg", strict: strict)
      end

      def test_clean_svg_passes_and_prints_kb
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" ) +
              %(role="img"><title>t</title><rect/></svg>)
        r = report(svg)
        assert_equal 0, r.exit_code
        assert_empty r.stderr_lines
        assert_equal ["svg-check: mem.svg clean (#{format('%.1f', svg.bytesize / 1024.0)}KB)"], r.stdout_lines
      end

      def test_missing_viewbox_is_an_error
        r = report(%(<svg xmlns="http://www.w3.org/2000/svg" role="img"><title>t</title></svg>))
        assert_equal 1, r.exit_code
        assert_includes r.errors, 'no viewBox on root — the art will not scale. Add viewBox="0 0 W H".'
      end

      def test_missing_title_and_role_are_warnings
        r = report(%(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect/></svg>))
        assert_equal 0, r.exit_code # warnings only, non-strict
        assert_includes r.warnings, "no <title> as first child (screen readers, and it shows as a tooltip)"
        assert_includes r.warnings, 'missing role="img" on root'
      end

      def test_warnings_fail_under_strict
        r = report(%(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect/></svg>), strict: true)
        assert_equal 1, r.exit_code
      end

      def test_warning_lines_precede_error_lines_on_stderr
        # A doc with both a warning (missing role) and an error (dup ids).
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">) +
              %(<title>t</title><rect id="a"/><rect id="a"/></svg>)
        lines = report(svg).stderr_lines
        assert_equal 'WARN  missing role="img" on root', lines.first
        assert lines.last.start_with?("ERROR duplicate id(s): a")
      end

      def test_root_not_svg
        r = report(%(<div xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><p/></div>))
        assert_includes r.errors, "root element is <div>, expected <svg>"
      end

      def test_embedded_raster_image
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img">) +
              %(<title>t</title><image href="data:image/png;base64,AAAA"/></svg>)
        assert_includes report(svg).errors,
                        "embedded raster <image> — that is a PNG in a trenchcoat, not vector art"
      end

      def test_external_image_reference
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img">) +
              %(<title>t</title><image href="/pic.png"/></svg>)
        assert_includes report(svg).errors, "external <image> reference: /pic.png"
      end

      def test_network_href_and_xlink_fallback
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" ) +
              %(viewBox="0 0 10 10" role="img"><title>t</title><use xlink:href="https://x.example/y"/></svg>)
        assert_includes report(svg).errors, "external network references: https://x.example/y"
      end

      def test_duplicate_ids_sorted
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img"><title>t</title>) +
              %(<rect id="b"/><rect id="b"/><rect id="a"/><rect id="a"/></svg>)
        assert_includes report(svg).errors, "duplicate id(s): a, b"
      end

      def test_dangling_references_from_hash_and_url
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img"><title>t</title>) +
              %(<rect fill="url(#grad)"/><use href="#sym"/></svg>)
        assert_includes report(svg).errors,
                        "reference(s) to missing id(s): grad, sym — gradient or clipPath " \
                        "will silently render as black/none"
      end

      def test_live_reference_is_not_flagged
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img"><title>t</title>) +
              %(<rect id="grad"/><rect fill="url(#grad)"/></svg>)
        assert_equal 0, report(svg).exit_code
      end

      def test_text_only_warns_under_strict
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img">) +
              %(<title>t</title><text>hi</text></svg>)
        refute_includes report(svg).warnings.join, "<text> present"
        assert report(svg, strict: true).warnings.any? { |w| w.start_with?("<text> present") }
      end

      def test_path_coordinate_far_outside_viewbox
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img">) +
              %(<title>t</title><path d="M 9999 8888 L 1 1"/></svg>)
        assert report(svg).warnings.any? { |w| w.include?("(9999,8888) is far outside") }
      end

      def test_oversize_file_error
        svg = %(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img"><title>t</title></svg>)
        r = Lint.check_source(svg, path: "mem.svg", max_kb: 0.001)
        assert_includes r.errors.first, "budget is 0KB"
      end

      def test_missing_file_is_fatal
        r = Lint.check("/no/such/file.svg")
        assert_equal 1, r.exit_code
        assert_equal ["ERROR missing file: /no/such/file.svg"], r.stderr_lines
        assert_empty r.stdout_lines
      end

      def test_coords_in_path_samples_absolute_ml_and_c_endpoints
        # M/L pairs plus the endpoint of a cubic; relative commands ignored.
        coords = Lint.coords_in_path("M 1 2 L 3 4 C 5 6 7 8 9 10 l 99 99")
        assert_equal [[1.0, 2.0], [3.0, 4.0], [9.0, 10.0]], coords
      end
    end

    # Runs the Python oracle and this port over every committed .svg and asserts
    # byte-identical stdout, stderr, and exit codes — the contract the
    # PostToolUse hook depends on.
    class LintDifferentialTest < Minitest::Test
      REPO = File.expand_path("../..", __dir__)
      ORACLE = File.join(REPO, "tools", "svg", "svg-check.py")

      def python3?
        @python3 ||= system("python3", "--version", out: File::NULL, err: File::NULL)
      end

      def svg_files
        # Committed, always-present directories first; scratch dirs are a bonus
        # when a working tree happens to have them.
        globs = %w[
          docs/**/*.svg
          tools/svg/library/**/*.svg
          web/public/*.svg
          .sweep/**/*.svg
          .preview/**/*.svg
        ]
        globs.flat_map { |g| Dir[File.join(REPO, g)] }.uniq.sort
      end

      def run_ruby(args)
        out = StringIO.new
        err = StringIO.new
        code = Zer0ImageGenerator::Svg::Lint.run(args, stdout: out, stderr: err)
        [out.string, err.string, code]
      end

      def run_python(args)
        stdout, stderr, status = Open3.capture3("python3", ORACLE, *args, chdir: REPO)
        [stdout, stderr, status.exitstatus]
      end

      def test_findings_and_exit_codes_match_the_oracle
        skip "python3 not available" unless python3?

        files = svg_files
        refute_empty files, "expected committed SVGs to lint"

        checked = 0
        files.each do |file|
          [[], ["--strict"]].each do |flags|
            args = [file] + flags
            py_out, py_err, py_code = run_python(args)
            rb_out, rb_err, rb_code = run_ruby(args.dup)

            label = "#{file} #{flags.join(' ')}"
            assert_equal py_code, rb_code, "exit code differs for #{label}"
            assert_equal py_out, rb_out, "stdout differs for #{label}"
            assert_equal py_err, rb_err, "stderr differs for #{label}"
            checked += 1
          end
        end
        # Visible in verbose runs; documents the corpus size the parity holds over.
        assert_operator checked, :>=, 2
      end
    end
  end
end
