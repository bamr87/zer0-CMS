# frozen_string_literal: true

require "minitest/autorun"
require "fileutils"
require "tmpdir"
require_relative "../../lib/zer0_cms/cms/writer"

class TestWriter < Minitest::Test
  def test_create_writes_dated_post
    Dir.mktmpdir do |dir|
      FileUtils.mkdir_p(File.join(dir, "_posts"))
      File.write(File.join(dir, "_config.yml"), "title: t\n")
      path = Zer0Cms::Cms::Writer.create(dir, collection: "posts", title: "Hello World", body: "Hi\n")
      assert File.exist?(path)
      text = File.read(path)
      assert_includes text, "title: Hello World"
      assert_includes text, "Hi\n"
      assert_match(/#{Date.today.iso8601}-hello-world\.md\z/, path.to_s)
    end
  end
end
