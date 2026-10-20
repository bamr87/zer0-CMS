# frozen_string_literal: true

require "json"
require "open3"

# Differential-test harness: runs the Python generator ORACLE
# (tools/svg/examples/*.py) and returns its output so the Ruby port can be
# compared byte-for-byte. The Python files are the source of truth for this
# port; these tests fail loudly if Ruby drifts from them.
#
# Guarded so the suite skips cleanly where python3 is unavailable, but where it
# is present (as in this repo's CI) the differential assertions actually run.
module SvgOracle
  REPO_ROOT = File.expand_path("../..", __dir__)

  # One python invocation loads the target example module by file path (so its
  # module-level sys.path shims for pixelkit run exactly as on the CLI) and
  # emits build() output for every requested combo. Framed as JSON so SVG text
  # survives transport unaltered.
  DRIVER = <<~PYTHON
    import sys, os, json, importlib.util
    gen, repo = sys.argv[1], sys.argv[2]
    path = os.path.join(repo, "tools", "svg", "examples", gen + ".py")
    spec = importlib.util.spec_from_file_location(gen, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = []
    for combo in json.load(sys.stdin):
        seed, palette = combo[0], combo[1]
        out.append(mod.build(seed) if palette is None else mod.build(seed, palette))
    sys.stdout.write(json.dumps(out))
  PYTHON

  module_function

  def python3
    return @python3 if defined?(@python3)

    @python3 = [ENV["PYTHON3"], "python3", "python"].compact.find do |candidate|
      system(candidate, "-c", "import sys", out: File::NULL, err: File::NULL)
    end
  end

  def available?
    !python3.nil?
  end

  # combos: array of [seed, palette]; pass nil palette for generators without a
  # palette knob (starmap). Returns an array of oracle SVG strings, aligned.
  def run(generator, combos)
    stdout, stderr, status = Open3.capture3(
      python3, "-c", DRIVER, generator, REPO_ROOT, stdin_data: JSON.dump(combos)
    )
    raise "python oracle for #{generator} failed:\n#{stderr}" unless status.success?

    JSON.parse(stdout)
  end
end
