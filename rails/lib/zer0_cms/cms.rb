# frozen_string_literal: true

require_relative "cms/front_matter"
require_relative "cms/catalog"
require_relative "cms/writer"

module Zer0Cms
  # Fleet CMS primitives used by the Rails platform. Stdlib-only so the
  # headless tests can load them without bundler. The VS Code extension in
  # src/ remains the in-editor editor; this is the on-disk read/write layer
  # the web app drives.
  module Cms
  end
end
