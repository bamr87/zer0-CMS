# frozen_string_literal: true

# Unit test for the Ruby command layer's Mercenary→argv translation —
# runs with a bare stdlib ruby (no Jekyll needed): the Jekyll constants the
# class body references are stubbed before the require.
#
#     ruby test/test_command.rb

module Jekyll
  class Command; end
end

require "minitest/autorun"
require_relative "../lib/zer0_image_generator/command"

class TestBuildArgv < Minitest::Test
  def build(options)
    Zer0ImageGenerator::Command.new.build_argv(options)
  end

  # Mercenary stores option values under the SYMBOL passed to c.option
  # (config[map[option]] = x) — the regression in <= 0.2.1 looked up the
  # string form and silently dropped every flag.
  def test_symbol_keys_forward_flags
    argv = build(dry_run: true, provider: "local", batch: 3)
    assert_equal ["--dry-run", "--provider", "local", "--batch", "3"], argv
  end

  def test_string_keys_still_accepted
    argv = build("list_missing" => true, "collection" => "docs")
    assert_equal ["--collection", "docs", "--list-missing"], argv
  end

  def test_false_and_nil_omit_the_flag
    assert_equal [], build(dry_run: false, provider: nil)
  end

  def test_booleans_pass_bare_and_values_pass_through
    argv = build(force: true, front_matter_key: "image")
    assert_equal ["--force", "--front-matter-key", "image"], argv
  end

  def test_argv_order_follows_switch_table
    argv = build(collections_dir: "pages", verbose: true, file: "a.md")
    assert_equal ["--verbose", "--file", "a.md", "--collections-dir", "pages"], argv
  end
end
