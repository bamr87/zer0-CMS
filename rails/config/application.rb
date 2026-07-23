# frozen_string_literal: true

require_relative "boot"

require "rails"
require "action_controller/railtie"
require "action_view/railtie"

require "zer0_cms"

module Zer0CmsWeb
  # The Rails host for the ABC content engine. Deliberately thin: it owns HTTP,
  # forms, and views; all book logic lives in Zer0Cms::Abc (lib/zer0_cms), the
  # same code the CLI and tests drive.
  class Application < Rails::Application
    config.load_defaults 7.1
    config.api_only = false
    config.eager_load = ENV.fetch("RAILS_ENV", "development") == "production"
    config.secret_key_base = ENV.fetch("SECRET_KEY_BASE", "dev-only-not-a-secret")

    # Where `Export` writes book bundles. Point this at a sibling drsai checkout.
    config.x.drsai_site_root = ENV.fetch("DRSAI_SITE_ROOT", File.expand_path("../../../drsai", __dir__))

    config.hosts.clear # dev convenience; scope this in a real deployment
  end
end
