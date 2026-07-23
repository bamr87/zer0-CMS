# frozen_string_literal: true

# Loads the entire engine in dependency order.
#
# The individual files require only their immediate collaborators, so that a
# single slice (a generator, the sanitizer) can be pulled in on its own. This
# file is the "give me everything" entry point the CLI and the Rails app use,
# where the whole pipeline — config, settings, providers, Claude, the runner —
# has to be present at once.
#
# Stdlib only, by policy.

require_relative "engine"          # version + PyRandom + Error
require_relative "logging"
require_relative "stats"
require_relative "constants"
require_relative "config"
require_relative "settings"
require_relative "content"
require_relative "prompt"
require_relative "http"
require_relative "claude/client"
require_relative "claude/orchestration"
require_relative "svg/sanitizer"
require_relative "svg/local_renderer"
require_relative "svg/rasterizer"
require_relative "svg/lint"
require_relative "svg/pixel_kit"
require_relative "providers"
require_relative "runner"
require_relative "cli"

# The parametric SVG generators are optional for a preview run but always wanted
# by the studio, so load them here too.
Dir[File.join(__dir__, "svg", "generators", "*.rb")].sort.each { |file| require file }
require_relative "svg/banner_seed"

# The example library and FreeSVG sourcing are auxiliary features (library
# browsing, external sourcing) with no role in the generation pipeline, so they
# are required on demand by the code that uses them (see
# Zer0ImageGenerator.load_sourcing) rather than pulled into every load.

module Zer0ImageGenerator
  # Load the on-demand sourcing + library modules. Separate from the core so a
  # preview run or a studio render never depends on the FreeSVG client being
  # present; called by the library/freesvg web controllers before they use it.
  def self.load_sourcing
    require_relative "library"
    require_relative "freesvg/cache"
    require_relative "freesvg/client"
  end
end
