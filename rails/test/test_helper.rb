# frozen_string_literal: true

ENV["RAILS_ENV"] ||= "test"
# The access guard reads these per request; a developer's shell must not
# change what the suite sees.
%w[ZER0_CMS_PASSWORD ZER0_CMS_USER ZER0_CMS_TRUST_DOCKER_GATEWAY].each { |key| ENV.delete(key) }

require_relative "../config/environment"
require "rails/test_help"
require "fileutils"
require "tmpdir"

# A private, writable copy of test/fixtures/jekyll-site — the fixture whose
# expected reader output Jekyll 4.4.1 itself generated — registered and synced.
module FixtureSite
  SOURCE = Rails.root.join("test/fixtures/jekyll-site")
  PNG = ["89504e470d0a1a0a0000000d4948445200000001000000010806000000" \
         "1f15c4890000000d4944415478da63f8cfc0f01f0005000201a5f3b9a90000000049454e44ae426082"].pack("H*")

  def build_site(name: "fixture")
    tmp = File.realpath(Dir.mktmpdir("zer0-cms-test-"))
    (@tmp_dirs ||= []) << tmp
    root = File.join(tmp, "site")
    FileUtils.cp_r(SOURCE.to_s, root)
    site = Site.create!(name: name, path: root)
    site.sync!
    site
  end

  def scratch_dir
    tmp = File.realpath(Dir.mktmpdir("zer0-cms-outside-"))
    (@tmp_dirs ||= []) << tmp
    tmp
  end

  def write_file(site, relative, content)
    path = File.join(site.path, relative)
    FileUtils.mkdir_p(File.dirname(path))
    File.binwrite(path, content)
    path
  end

  def with_env(values)
    saved = values.keys.to_h { |key| [key, ENV[key]] }
    values.each { |key, value| value.nil? ? ENV.delete(key) : ENV[key] = value }
    yield
  ensure
    saved.each { |key, value| value.nil? ? ENV.delete(key) : ENV[key] = value }
  end
end

module ActiveSupport
  class TestCase
    include FixtureSite

    setup { Rails.application.config.x.sites_dir = nil }
    teardown { Array(@tmp_dirs).each { |dir| FileUtils.rm_rf(dir) } }
  end
end

module ActionDispatch
  class IntegrationTest
    setup { host! "localhost" }

    # The edit form as a browser would submit it: every page[...] field with
    # its rendered value, checkboxes only when checked.
    def submitted_form_values
      values = {}
      css_select("form.form").first.css("input[name^='page['], textarea[name^='page['], select[name^='page[']").each do |node|
        name = node["name"][/\Apage\[(.+)\]\z/, 1]
        case node.name
        when "textarea" then values[name] = node.text.delete_prefix("\n")
        when "select" then values[name] = node.css("option[selected]").first&.[]("value").to_s
        else
          next if node["type"] == "checkbox" && !node.key?("checked")

          values[name] = node["value"].to_s
        end
      end
      values
    end
  end
end
