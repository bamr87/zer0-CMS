# frozen_string_literal: true

# Pure-Ruby entry point for the image engine.
#
# Deliberately separate from `lib/zer0-image-generator.rb`: that file is the
# gem's Bundler entry point and conditionally pulls in Jekyll to register the
# `jekyll preview-images` command. This file loads the engine and nothing else,
# so the Rails app in `web/` (and any plain script) can drive the same code
# without dragging Jekyll in.
#
# Stdlib only, by policy — the gem stays dependency-light, so anything required
# here must ship with Ruby.

require_relative "version"
require_relative "support/py_random"

module Zer0ImageGenerator
  # Raised for engine-level failures that callers are expected to surface to a
  # human — a missing credential, an unreadable site, a provider refusal.
  class Error < StandardError; end
end
