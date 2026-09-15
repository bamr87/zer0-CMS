# frozen_string_literal: true

ENV["BUNDLE_GEMFILE"] ||= File.expand_path("../Gemfile", __dir__)

require "bundler/setup"

# The stdlib content library (lib/zer0_cms) is required by path, not
# autoloaded: it is plain Ruby shared with bin/zer0-cms and bin/test-stdlib.
$LOAD_PATH.unshift File.expand_path("../lib", __dir__)
