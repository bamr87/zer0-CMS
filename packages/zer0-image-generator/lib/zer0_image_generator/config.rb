# frozen_string_literal: true

# Port of the config layer of lib/zer0_image_generator/preview_generator.py
# (find_project_root, load_yaml_file, apply_source_root, read_config,
# read_authors, _load_dotenv, _env_flag). The Python file stays the oracle;
# test/ruby/test_config.rb differential-tests these against it where runnable.

require "yaml"
require "date" # so YAML.safe_load can parse the date/timestamp scalars a
# real _config.yml may carry — Python's yaml.safe_load accepts them and we must
# not diverge by rejecting an otherwise-valid config.
require "pathname"

require_relative "constants"

module Zer0ImageGenerator
  module_function

  # --- Diagnostic seam --------------------------------------------------------
  # The Python engine funnels warn()/info() through one colorized log(). Here
  # that shared logger lives in the `Zer0ImageGenerator::Logging` slice; route
  # through it when the full engine is loaded (so config/settings log with the
  # same colors, stream split, and --log-file mirror as everyone else). When
  # only this slice is present — a bare `ruby -Ilib` unit run — fall back to the
  # oracle's own stream split: info to stdout, warnings to stderr. Detected at
  # call time (like content.rb) so the slice never hard-depends on logging.rb.
  def info(msg)
    _route_log(:info, "INFO", $stdout, msg)
  end

  def warn(msg)
    _route_log(:warn, "WARNING", $stderr, msg)
  end

  def _route_log(logging_method, label, fallback_stream, msg)
    if const_defined?(:Logging, false) && Logging.respond_to?(logging_method)
      Logging.public_send(logging_method, msg)
    else
      fallback_stream.puts("[#{label}] #{msg}")
    end
  end

  # --- CPython-truthiness helpers ---------------------------------------------
  # The precedence chain in resolve_settings leans on Python's `x or y` and
  # `bool(x)` semantics, where "" / 0 / [] / {} / None are all falsy. Ruby only
  # treats nil and false as falsy, so a naive `||` would let an empty string or
  # a `false`-from-YAML slip through where CPython would fall past it. These two
  # helpers make the port match the oracle exactly.

  # Mirrors CPython's builtin bool(): only nil/false, empty string, zero, and
  # empty collections are falsy.
  def python_bool(value)
    case value
    when nil, false then false
    when true then true
    when String then !value.empty?
    when Numeric then value != 0
    when Array, Hash then !value.empty?
    else true
    end
  end

  # Mirrors CPython's str() for the scalar types a YAML config yields. The only
  # values that diverge from Ruby's to_s in practice are booleans and nil
  # (Python str(True)=="True"/str(None)=="None" vs Ruby "true"/""), which a
  # config like `quality: true` or `collections: [true]` would otherwise flip.
  # Numeric str() agrees between the two runtimes for the integers/plain floats
  # a config carries (see DEVIATIONS for exotic-float exponents).
  def python_str(value)
    case value
    when true then "True"
    when false then "False"
    when nil then "None"
    else value.to_s
    end
  end

  # Mirrors CPython's `a or b or c ...`: the first python-truthy value, else the
  # last value regardless of truthiness.
  def python_first_truthy(*values)
    values.each_with_index do |value, index|
      return value if index == values.length - 1
      return value if python_bool(value)
    end
  end

  # --- .env loading -----------------------------------------------------------

  # Load .env from cwd (or `start`) up to 4 parents.
  #
  # Non-empty exported env vars win over .env; an EMPTY env var is treated as
  # unset (docker/VS Code tasks forward `-e KEY=${env:KEY}` which materializes
  # empty strings that must not shadow a real value in .env).
  def _load_dotenv(start = nil)
    search_dir = Pathname.new(start ? start.to_s : Dir.pwd)
    5.times do
      env_file = search_dir + ".env"
      if env_file.file?
        begin
          env_file.read(encoding: "UTF-8").each_line do |line|
            line = line.strip
            next if line.empty? || line.start_with?("#") || !line.include?("=")

            key, _, value = line.partition("=")
            key = key.strip
            value = value.strip
            if %w[' "].include?(value[0, 1]) && value[-1, 1] == value[0, 1]
              value = value[1..-2] # matched surrounding quotes
            else
              value = value.split(" #", 2).first.rstrip # inline comment
            end
            # An empty exported var is treated as unset, so it does not shadow.
            ENV[key] = value if !key.empty? && (ENV[key].nil? || ENV[key].empty?)
          end
        rescue SystemCallError
          # Oracle swallows OSError here (a partially-readable .env must not
          # abort the run); mirror that, but only for I/O errors.
        end
        return
      end
      break if search_dir.parent == search_dir

      search_dir = search_dir.parent
    end
    nil
  end

  # --- Project root / config files -------------------------------------------

  # Site root: two parents above this file when vendored at <site>/scripts/lib/
  # (curl layout); else walk up from cwd — the gem layout, where the engine
  # lives far from the site and `jekyll` runs at the root. Returns a Pathname.
  def find_project_root
    script_root = Pathname.new(File.expand_path("../../..", __FILE__))
    return script_root if (script_root + "_config.yml").file?

    probe = Pathname.new(Dir.pwd)
    6.times do
      return probe if (probe + "_config.yml").file?
      break if probe.parent == probe

      probe = probe.parent
    end
    script_root
  end

  def load_yaml_file(path)
    text = File.read(path.to_s, encoding: "UTF-8")
    data = YAML.safe_load(text, permitted_classes: [Date, Time], aliases: true)
    data.is_a?(Hash) ? data : {}
  rescue Errno::ENOENT
    {} # missing file: silent, exactly like the oracle's FileNotFoundError arm
  rescue StandardError => e
    # Malformed YAML (or any other read/parse error) must not kill the run.
    warn("Could not parse #{File.basename(path.to_s)}: #{e}")
    {}
  end

  # Honor Jekyll's top-level `source:` key: content (collections, assets,
  # _data) lives under <root>/<source> while _config.yml stays at the root —
  # e.g. zer0-pages sets `source: pages`. Disk-side only: URL-space values
  # (front-matter paths, assets_prefix) are unaffected. Returns a Pathname.
  def apply_source_root(project_root, config)
    root = Pathname.new(project_root.to_s)
    # python_str, not to_s: mirror CPython str() so a non-string Jekyll `source:`
    # (a bool or number) reroots the same way the oracle does.
    source = python_str(python_first_truthy(config["source"], "")).strip.gsub(%r{\A/+|/+\z}, "")
    return root + source if !source.empty? && source != "."

    root
  end

  # The site's full _config.yml — resolve_settings extracts the `preview_images:`
  # block plus the top-level Jekyll keys it honors (collections_dir, collections).
  def read_config(project_root)
    load_yaml_file(Pathname.new(project_root.to_s) + "_config.yml")
  end

  # Author-override map. `authors_file` is project-root-relative; an empty value
  # disables the feature (universal sites rarely have authors.yml).
  def read_authors(project_root, authors_file)
    rel = (authors_file || "").to_s
    return {} if rel.strip.empty?

    load_yaml_file(Pathname.new(project_root.to_s) + rel.strip.sub(%r{\A/+}, ""))
  end

  # `os.environ.get(name, "").strip().lower() == "true"`
  def _env_flag(name)
    ENV.fetch(name, "").strip.downcase == "true"
  end
end
