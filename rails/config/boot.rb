# frozen_string_literal: true

ENV["BUNDLE_GEMFILE"] ||= File.expand_path("../Gemfile", __dir__)

require "bundler/setup" if File.exist?(ENV["BUNDLE_GEMFILE"])

# Put the stdlib-only engine on the load path so `require "zer0_cms"` works
# whether the app is booted via Rails or the CLI.
$LOAD_PATH.unshift File.expand_path("../lib", __dir__)
