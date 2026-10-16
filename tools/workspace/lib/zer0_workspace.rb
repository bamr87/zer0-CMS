# frozen_string_literal: true

# Zer0Workspace — the tooling behind `bin/zer0`, which manages every project
# in the zer0 monorepo from one manifest (workspace.yml). Stdlib only, like
# rails/lib, so it runs in a bare checkout and in any CI job before a single
# dependency is installed.

require_relative "zer0_workspace/manifest"
require_relative "zer0_workspace/ownership"
require_relative "zer0_workspace/checks"
require_relative "zer0_workspace/runner"
require_relative "zer0_workspace/vendor"
require_relative "zer0_workspace/doctor"
require_relative "zer0_workspace/cli"
