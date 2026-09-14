# frozen_string_literal: true

require_relative "boot"

require "rails"
require "active_record/railtie"
require "action_controller/railtie"
require "action_view/railtie"
require "propshaft"
require "importmap-rails"
require "turbo-rails"
require "stimulus-rails"

require "zer0_cms"

module Zer0CmsWeb
  # Rails host for the fleet CMS platform. The VS Code extension in ../../src
  # still edits content in the editor; this app is the browser control panel
  # for every zer0-themed Jekyll site mounted under /sites. ABC generation
  # stays in Zer0Cms::Abc — the same classes the CLI drives.
  class Application < Rails::Application
    config.load_defaults 7.1
    config.api_only = false
    config.eager_load = ENV.fetch("RAILS_ENV", "development") == "production"
    config.secret_key_base = ENV.fetch("SECRET_KEY_BASE", "dev-only-not-a-secret")
    config.hosts.clear
    config.x.sites_dir = ENV.fetch("SITES_DIR", "/sites")
    config.x.drsai_site_root = ENV.fetch("DRSAI_SITE_ROOT", File.expand_path("../../../drsai", __dir__))
  end
end
