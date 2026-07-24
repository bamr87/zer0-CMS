# frozen_string_literal: true

# The ABC book subsystem: art styles, themed lexicons, the spec, content
# providers, the wizard, and the Jekyll exporter.

require_relative "abc/art_styles"
require_relative "abc/lexicon"
require_relative "abc/spec"
require_relative "abc/content_provider"
require_relative "abc/providers/deterministic"
require_relative "abc/providers/anthropic"
require_relative "abc/wizard"
require_relative "abc/jekyll_exporter"

module Zer0Cms
  module Abc
    SERIES = "abc-language"
  end
end
