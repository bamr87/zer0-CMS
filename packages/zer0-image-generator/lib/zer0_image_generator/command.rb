# frozen_string_literal: true

module Zer0ImageGenerator
  # `jekyll preview-images` — a thin launcher for the vendored single-file
  # Python engine (preview_generator.py, same directory). The Ruby layer only
  # translates Mercenary options back into the engine's argv and execs
  # python3: all behavior (config resolution, credentials, providers, front
  # matter) lives in the engine so the gem and the standalone file can never
  # drift.
  #
  # Jekyll's global switches already claim -s/-d/-p/-v at the program level,
  # so conflicting engine shorts are exposed long-form here; the engine's own
  # CLI keeps the full short surface for direct `python3` use.
  class Command < Jekyll::Command
    ENGINE = File.expand_path("preview_generator.py", __dir__)

    # [engine flag, mercenary args] — booleans pass bare, values pass through.
    SWITCHES = [
      ["--dry-run",          [:dry_run, "--dry-run", "Preview what would be generated (no changes)"]],
      ["--verbose",          [:verbose, "--verbose", "Enable verbose output"]],
      ["--file",             [:file, "-f", "--file FILE", "Process a specific file only"]],
      ["--collection",       [:collection, "--collection NAME", "Process one collection, or 'all'"]],
      ["--provider",         [:provider, "--provider NAME", "Renderer: openai, xai, stability, gemini, local"]],
      ["--model",            [:model, "--model NAME", "Override the provider's image model"]],
      ["--output-dir",       [:output_dir, "--output-dir DIR", "Image output directory"]],
      ["--force",            [:force, "--force", "Regenerate even when a preview exists"]],
      ["--list-missing",     [:list_missing, "--list-missing", "Only list files with missing previews"]],
      ["--parallel",         [:parallel, "-j", "--parallel N", "Concurrent workers (default 4)"]],
      ["--enhance",          [:enhance, "-e", "--enhance", "Enhance existing images (OpenAI images/edits)"]],
      ["--enhance-prompt",   [:enhance_prompt, "--enhance-prompt TEXT", "Custom enhancement prompt (implies --enhance)"]],
      ["--enhance-model",    [:enhance_model, "--enhance-model NAME", "Enhancement model (default: gpt-image-2)"]],
      ["--enhance-quality",  [:enhance_quality, "--enhance-quality Q", "low|medium|high|auto"]],
      ["--enhance-fidelity", [:enhance_fidelity, "--enhance-fidelity F", "high|low (implies --enhance)"]],
      ["--enhance-format",   [:enhance_format, "--enhance-format FMT", "png|jpeg|webp (implies --enhance)"]],
      ["--prompt-engine",    [:prompt_engine, "--prompt-engine ENGINE", "claude (analyzes the article) or template"]],
      ["--review",           [:review, "--review ENGINE", "claude (vision-reviews the render) or none"]],
      ["--rasterizer",       [:rasterizer, "--rasterizer TOOL", "auto|rsvg|inkscape|magick|playwright|none"]],
      ["--style",            [:style, "--style TEXT", "Override the image style prompt"]],
      ["--assets-prefix",    [:assets_prefix, "--assets-prefix PREFIX", "Assets prefix for path normalization"]],
      ["--no-auto-prefix",   [:no_auto_prefix, "--no-auto-prefix", "Disable automatic assets-prefix prepending"]],
      ["--batch",            [:batch, "--batch N", "Limit number of files processed"]],
      ["--log-file",         [:log_file, "--log-file FILE", "Also write log output to a file"]],
      ["--collections-dir",  [:collections_dir, "--collections-dir DIR", "Directory holding _<collection> dirs"]],
      ["--front-matter-key", [:front_matter_key, "--front-matter-key KEY", "Front-matter key (default preview; seo-tag sites: image)"]],
      ["--authors-file",     [:authors_file, "--authors-file FILE", "Author-overrides YAML ('' disables)"]],
    ].freeze

    BOOLEANS = %w[--dry-run --verbose --force --list-missing --enhance --no-auto-prefix].freeze

    class << self
      def init_with_program(prog)
        prog.command(:"preview-images") do |c|
          c.syntax "preview-images [options]"
          c.description "Generate AI preview/social images (Claude directs & reviews; " \
                        "OpenAI/xAI/Stability/Gemini/local renders)"
          SWITCHES.each { |_flag, merc| c.option(*merc) }

          c.action do |_args, options|
            new.run(options)
          end
        end
      end
    end

    def run(options)
      python = ENV["PYTHON"] || "python3"
      ensure_python!(python)
      argv = build_argv(options)
      Jekyll.logger.info "preview-images:", "#{python} #{ENGINE} #{argv.join(' ')}"
      exec(python, ENGINE, *argv)
    end

    def build_argv(options)
      SWITCHES.each_with_object([]) do |(flag, merc), argv|
        value = options[merc.first.to_s]
        next if value.nil? || value == false

        if BOOLEANS.include?(flag)
          argv << flag
        else
          argv << flag << value.to_s
        end
      end
    end

    private

    def ensure_python!(python)
      unless command_available?(python)
        Jekyll.logger.abort_with "preview-images:",
                                 "#{python} not found — install Python 3.9+ " \
                                 "(or set PYTHON=/path/to/python3)."
      end
      return if system(python, "-c", "import yaml", out: File::NULL, err: File::NULL)

      Jekyll.logger.abort_with "preview-images:",
                               "PyYAML is missing — run: #{python} -m pip install pyyaml"
    end

    def command_available?(cmd)
      system(cmd, "--version", out: File::NULL, err: File::NULL)
    rescue SystemCallError
      false
    end
  end
end
