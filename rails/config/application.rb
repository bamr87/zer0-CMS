# frozen_string_literal: true

require_relative "boot"

require "rails"
require "active_record/railtie"
require "action_controller/railtie"
require "action_view/railtie"
require "rails/test_unit/railtie"

Bundler.require(*Rails.groups)

require "ipaddr"
require "zer0_cms"

module Zer0CmsWeb
  # The fleet CMS on Administrate (docs/PLATFORM.md). Git is the source of
  # truth; the SQLite database is an index of what Jekyll reads, rebuilt by
  # Site#sync! from Zer0Cms::Cms::Catalog. Writes go to disk through
  # PageEditor and Zer0Cms::Cms::Writer, never through ActiveRecord.
  class Application < Rails::Application
    config.load_defaults 8.1
    config.time_zone = "UTC"

    # lib/zer0_cms is plain Ruby required above; nothing under lib/ is
    # autoloaded or eager loaded.
    config.autoload_lib(ignore: %w[tasks zer0_cms])

    # DNS-rebinding guard: only loopback hosts unless the operator names more.
    extra_hosts = ENV.fetch("ZER0_CMS_HOSTS", "").split(",").map(&:strip).reject(&:empty?)
    config.hosts = ["localhost", IPAddr.new("127.0.0.1"), IPAddr.new("::1"), "[::1]", *extra_hosts]

    # Jekyll roots live under SITES_DIR (the /sites bind mount in Docker).
    # Outside a container an unset SITES_DIR means "any absolute path".
    config.x.sites_dir = ENV["SITES_DIR"].presence || ("/sites" if File.exist?("/.dockerenv"))

    # ABC export needs an explicit target; there is no default.
    config.x.drsai_site_root = ENV["DRSAI_SITE_ROOT"].presence

    if ENV["RAILS_LOG_TO_STDOUT"].present?
      config.logger = ActiveSupport::TaggedLogging.logger($stdout)
    end
  end
end
