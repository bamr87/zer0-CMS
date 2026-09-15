# frozen_string_literal: true

require "pathname"

# The one seam between zer0-CMS and zer0-image-generator (RFC §3). This file,
# and only this file, loads or runs the image engine; everything bigger than
# one page (batch runs, compositions, the studio) links out to the image
# generator's own panel at ImageEngine.generator_url.
#
# It answers two questions — which pages of a site lack a preview, and "draw
# this one page with the local provider" — through one of two backends, chosen
# once per process:
#
# - FacadeBackend: Zer0ImageGenerator::Facade (missing_previews/generate_one),
#   the stable Ruby API. It lands with the image generator's
#   feat/zer0-stack-tokens branch and ships in the first gem release after
#   0.7.0; the Gemfile.lock pins 0.6.0, which does not have it.
# - PythonBackend: what the released 0.6.0 gem exposes. `jekyll preview-images`
#   is a launcher that execs the vendored single-file Python engine
#   (preview_generator.py), so this runs the same argv the CLI would —
#   `--list-missing` and `--file FILE --provider local` — as a subprocess in the
#   site root, with a minimal environment and a deadline. It needs python3 with
#   PyYAML; the Docker image installs both.
#
# The engine writes the preview key into the content file itself. A generation
# therefore refuses a file that changed since the last sync BEFORE the engine
# runs, and afterwards hands the engine's write to PageEditor, which applies
# the same key to the bytes the index knew with FrontMatter.update_keys (line
# surgery, atomic rename, re-sync). The engine's own writer never has the last
# word, and nothing is written through ActiveRecord.
class ImageEngine
  class Error < StandardError; end
  class Unavailable < Error; end

  PROVIDER = "local"
  DEFAULT_OUTPUT_DIR = "assets/images/previews"
  DEFAULT_KEY = "preview"
  KEY_PATTERN = /\A[A-Za-z_][A-Za-z0-9_-]*\z/
  TIMEOUT = 300

  # One generation at a time per process: the engine writes into the site.
  LOCK = Mutex.new

  Missing = Struct.new(:relative, :title, :preview, keyword_init: true)
  Settings = Struct.new(:key, :output_dir, keyword_init: true)
  Outcome = Struct.new(:status, :page, :preview, :message, :log, keyword_init: true) do
    def generated?
      status == :generated
    end
  end

  class << self
    attr_writer :backend

    def backend
      @backend ||= FacadeBackend.loadable? ? FacadeBackend.new : PythonBackend.new
    end

    # nil when the engine can run, else a sentence saying why it cannot.
    def unavailable_reason
      backend.unavailable_reason
    end

    def description
      backend.description
    end

    # The image generator's web panel, for full runs.
    def generator_url
      Rails.application.config.x.image_generator_url
    end

    # The site's preview key and output directory, as the engine reads them
    # from `preview_images:` — confined to the site root.
    def settings_for(site)
      catalog = Zer0Cms::Cms::Catalog.site_for(site.path)
      block = catalog.config["preview_images"]
      block = {} unless block.is_a?(Hash)
      key = block["front_matter_key"].to_s.strip
      key = DEFAULT_KEY if key.empty?
      raise Error, "preview_images.front_matter_key #{key.inspect} is not a plain key" unless KEY_PATTERN.match?(key)

      output = block["output_dir"].to_s.strip
      output = DEFAULT_OUTPUT_DIR if output.empty?
      dir = Zer0Cms::Cms::Catalog.confine(catalog.root, catalog.source, output, "preview_images.output_dir")
      raise Error, "preview_images.output_dir must be a directory below the site source" if dir == catalog.source

      Settings.new(key: key, output_dir: dir.relative_path_from(catalog.source).to_s)
    rescue Zer0Cms::Cms::UnsafePath => e
      raise Error, e.message
    end

    # Content files the engine would draw a preview for, in run order.
    def missing_previews(site)
      ensure_available!
      root = site.site_path
      backend.missing_previews(root.root.to_s).filter_map do |missing|
        missing.relative.nil? ? nil : missing
      end
    rescue SitePath::Refused => e
      raise Error, e.message
    end

    # The Administrate `missing_preview:` filter: the rows among `resources`
    # (optionally one site's) whose file the engine lists as missing a preview.
    def filter_missing(resources, site_id = nil)
      scope = site_id.present? ? resources.where(site_id: site_id) : resources
      ids = Site.where(id: scope.distinct.pluck(:site_id)).flat_map do |site|
        relatives = missing_previews(site).map(&:relative)
        relatives.empty? ? [] : site.pages.where(relative: relatives).pluck(:id)
      end
      scope.where(id: ids)
    end

    # Draw one page's preview with the local provider and write the key back
    # through PageEditor. Returns an Outcome; raises Error, PageEditor::Error or
    # SiteSync::Failed when nothing could be done.
    def generate_preview(page)
      ensure_available!
      site = page.site
      settings = settings_for(site)
      LOCK.synchronize { generate_locked(page, site, settings) }
    end

    private

    def ensure_available!
      reason = unavailable_reason
      raise Unavailable, reason if reason
    end

    def generate_locked(page, site, settings)
      editor = PageEditor.new(page)
      original = editor.current_text # refuses a stale file before the engine runs
      path = editor.file_path
      before = Zer0Cms::Cms::FrontMatter.parse(original).data[settings.key]

      result = backend.generate(site.site_path.root.to_s, path.to_s, output_dir: settings.output_dir, key: settings.key)

      engine_text = File.binread(path).force_encoding(Encoding::UTF_8)
      value = before
      value = editor.replace_engine_write!(original, engine_text, settings.key) if engine_text.b != original.b
      site.sync!
      fresh = site.pages.find_by(relative: page.relative) || page
      outcome_for(result, fresh, settings, before, value)
    end

    def outcome_for(result, page, settings, before, value)
      log = Array(result[:log])
      if result[:status] == :error
        return Outcome.new(status: :error, page: page, preview: value, log: log,
                           message: "The image engine failed: #{result[:error].presence || "see the log"}")
      end
      if value.is_a?(String) && value != before && PreviewImageField.locate(page.site, value)
        return Outcome.new(status: :generated, page: page, preview: value, log: log,
                           message: "Generated a local preview: #{settings.key}: #{value}")
      end

      message = if before.is_a?(String) && PreviewImageField.locate(page.site, before)
                  "#{page.relative} already has a preview (#{before}); the engine drew nothing."
                else
                  "The engine drew nothing for #{page.relative}."
                end
      Outcome.new(status: :skipped, page: page, preview: value, log: log, message: message)
    end
  end

  # Zer0ImageGenerator::Facade — the stable Ruby API (image generator > 0.7.0).
  class FacadeBackend
    FEATURE = "zer0_image_generator/facade"

    def self.loadable?
      $LOAD_PATH.resolve_feature_path(FEATURE) ? true : false
    rescue LoadError
      false
    end

    def description
      load!
      "zer0-image-generator #{Zer0ImageGenerator::VERSION} (Facade)"
    rescue Error => e
      "zer0-image-generator Facade (#{e.message})"
    end

    def unavailable_reason
      load!
      nil
    rescue Error => e
      e.message
    end

    def missing_previews(root)
      load!
      Zer0ImageGenerator::Facade.missing_previews(root).map do |missing|
        Missing.new(relative: missing.relative, title: missing.title, preview: missing.preview)
      end
    rescue Zer0ImageGenerator::Error => e
      raise Error, e.message
    end

    # output_dir and key are resolved (and confined) by the facade itself.
    def generate(root, file, output_dir:, key:)
      load!
      result = Zer0ImageGenerator::Facade.generate_one(root, file, provider: PROVIDER, env: {}, dry_run: false)
      {
        status: result.status, error: result.error,
        log: Array(result.log).map { |level, text| "#{level}: #{text}" }
      }
    rescue Zer0ImageGenerator::Error => e
      raise Error, e.message
    end

    private

    def load!
      return if @loaded

      require FEATURE
      @loaded = true
    rescue LoadError, StandardError => e
      raise Error, "the image engine facade failed to load: #{e.message}"
    end
  end

  # The released 0.6.0 gem's API: its vendored Python engine, run as the
  # `jekyll preview-images` launcher would run it.
  class PythonBackend
    ANSI = /\e\[[0-9;]*m/
    # The child sees these and nothing else: no credential reaches the engine,
    # and the local provider needs none.
    ENV_KEEP = %w[PATH HOME LANG LC_ALL TMPDIR].freeze

    attr_reader :python, :engine, :rasterizer, :timeout

    def self.engine_path
      spec = Gem.loaded_specs["zer0-image-generator"]
      spec ? File.join(spec.full_gem_path, "lib/zer0_image_generator/preview_generator.py") : nil
    end

    def initialize(python: ENV["PYTHON"].presence || "python3", engine: self.class.engine_path,
                   rasterizer: ENV["ZER0_CMS_RASTERIZER"].presence || "auto", timeout: TIMEOUT)
      @python = python
      @engine = engine
      @rasterizer = rasterizer
      @timeout = timeout
    end

    def description
      spec = Gem.loaded_specs["zer0-image-generator"]
      "zer0-image-generator #{spec ? spec.version : "(not bundled)"} (Python engine)"
    end

    def unavailable_reason
      return @unavailable_reason if defined?(@unavailable_reason)

      @unavailable_reason = probe
    end

    def missing_previews(root)
      output, status = capture(root, ["--list-missing", "--collection", "all", "--provider", PROVIDER])
      raise Error, "the image engine could not list missing previews: #{tail(output)}" unless status.success?

      self.class.parse_missing(output, root)
    end

    # --parallel 2: with one worker the engine sleeps two seconds after every
    # generation (paced paid API calls); a single --file run is serial anyway.
    def generate(root, file, output_dir:, key:)
      output, status = capture(root, ["--file", file, "--provider", PROVIDER, "--output-dir", output_dir,
                                      "--front-matter-key", key, "--rasterizer", rasterizer, "--parallel", "2"])
      text = output.gsub(ANSI, "")
      errors = text[/^\s*Errors:\s*(\d+)/, 1].to_i
      generated = text[/^\s*Images generated:\s*(\d+)/, 1].to_i
      log = text.lines.map(&:rstrip).reject(&:empty?)
      if !status.success? || errors.positive?
        { status: :error, error: tail(text), log: log }
      else
        { status: generated.positive? ? :generated : :skipped, error: nil, log: log }
      end
    end

    # "Missing preview: /abs/path.md" blocks from `--list-missing`, as
    # root-relative paths (a path outside the root is dropped).
    def self.parse_missing(output, root)
      prefix = "#{File.realpath(root)}/"
      missing = []
      output.gsub(ANSI, "").each_line do |line|
        line = line.chomp
        if (path = line[/\AMissing preview: (.+)\z/, 1])
          relative = path.start_with?(prefix) ? path.delete_prefix(prefix) : nil
          missing << Missing.new(relative: relative)
        elsif missing.any? && (title = line[/\A  Title: (.*)\z/, 1])
          missing.last.title = title
        elsif missing.any? && (preview = line[/\A  Current preview \(not found\): (.*)\z/, 1])
          missing.last.preview = preview
        end
      end
      missing.reject { |m| m.relative.nil? }
    end

    private

    def probe
      return "the zer0-image-generator gem is not in the bundle" unless engine && File.file?(engine)

      _, status = run_process(Dir.tmpdir, python, ["-c", "import yaml"], deadline: 30)
      return nil if status.success?

      "#{python} with PyYAML is required: the released zer0-image-generator engine is Python"
    rescue Error, SystemCallError => e
      "#{python} could not be started (#{e.message}): the released zer0-image-generator engine is Python"
    end

    def capture(root, args)
      run_process(root, python, [engine, *args], deadline: timeout)
    end

    # [combined output, Process::Status]. The child gets its own process group
    # so a deadline kills the rasterizer it may have started, too.
    def run_process(chdir, command, args, deadline:)
      env = ENV.to_h.slice(*ENV_KEEP).merge("PYTHONDONTWRITEBYTECODE" => "1", "PYTHONIOENCODING" => "utf-8")
      reader, writer = IO.pipe
      pid = Process.spawn(env, command, *args, chdir: chdir, unsetenv_others: true, in: File::NULL,
                                               out: writer, err: writer, pgroup: true)
      writer.close
      collector = Thread.new { reader.read.to_s.force_encoding(Encoding::UTF_8).scrub }
      unless collector.join(deadline)
        kill_group(pid)
        raise Error, "the image engine did not finish within #{deadline}s"
      end
      _, status = Process.wait2(pid)
      [collector.value, status]
    rescue SystemCallError => e
      raise Error, "the image engine could not be started: #{e.message}"
    ensure
      writer.close unless writer.nil? || writer.closed?
      reader&.close
    end

    def kill_group(pid)
      Process.kill("KILL", -pid)
      Process.wait(pid)
    rescue Errno::ESRCH, Errno::ECHILD
      Rails.logger.info("image engine #{pid} had already exited when its deadline passed")
    end

    def tail(text)
      text.gsub(ANSI, "").lines.map(&:strip).reject(&:empty?).last(6).join(" · ").truncate(600)
    end
  end
end
