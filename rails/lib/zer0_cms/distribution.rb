# frozen_string_literal: true

require_relative "version"
require_relative "linkedin"
require_relative "cms"
require_relative "doctor"

module Zer0Cms
  # The distribution lane: a site's content, carried to LinkedIn under a human
  # gate, and the audience's aggregate response carried back.
  #
  #   Config     zer0.json `distribution.linkedin` + _config.yml + the environment
  #   Drafts     the governed queue (pending → approved → published)
  #   Guard      the mechanical brand guard, rule-for-rule with the extension
  #   Permalink  the canonical URL Jekyll gives a page — the ledger key
  #   Composer   a deterministic first draft of a share's commentary
  #   Ledger     what was published, byte-compatible with the other lanes
  #   Pipeline   compose, approve, preview, publish, read back — the one path
  #   Analytics  statistics joined onto content paths, into .cms/distribution
  #   CLI, Mcp   `zer0-cms linkedin …` and its MCP server
  #
  # Stdlib only, like the rest of lib/zer0_cms: the reusable workflow runs it on
  # a bare Ruby with no bundle, and the Rails app drives the same classes.
  module Distribution
  end
end

require_relative "distribution/py_json"
require_relative "distribution/config"
require_relative "distribution/ledger"
require_relative "distribution/drafts"
require_relative "distribution/guard"
require_relative "distribution/permalink"
require_relative "distribution/composer"
require_relative "distribution/analytics"
require_relative "distribution/pipeline"
require_relative "distribution/callback"
require_relative "distribution/mcp"
require_relative "distribution/cli"
