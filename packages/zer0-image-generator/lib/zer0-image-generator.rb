# frozen_string_literal: true

# Entry point required by Bundler's :jekyll_plugins group. Registers the
# `jekyll preview-images` command when Jekyll is present; outside Jekyll the
# gem is inert (the Python engine can always be run directly:
# python3 lib/zer0_image_generator/preview_generator.py).
require_relative "zer0_image_generator/version"

begin
  require "jekyll"
rescue LoadError
  # Standalone/non-Jekyll context — nothing to register.
end

require_relative "zer0_image_generator/command" if defined?(Jekyll::Command)
