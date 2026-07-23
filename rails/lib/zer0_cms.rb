# frozen_string_literal: true

# Zer0Cms — the Ruby content engine at the heart of the zer0-CMS Rails app.
#
# The VS Code extension in this repo (a Front Matter CMS fork) edits content;
# this engine GENERATES it. Its first content type is the children's ABC book:
# a themed A–Z alphabet turned into a toddler picture book, illustrated by the
# zer0-image-generator plugin and published by drsai into the zer0-mistakes
# `books` collection.
#
# The whole engine is stdlib-only Ruby so the headless wizard (`bin/zer0-cms`)
# and its tests run without Rails or bundler; the Rails app under ../app + ../config
# is a thin web wrapper over exactly these classes.

require_relative "zer0_cms/version"
require_relative "zer0_cms/abc"

module Zer0Cms
  ROOT = File.expand_path("..", __dir__)

  # Absolute path to a bundled data/schema/lexicon file.
  def self.data_path(*parts)
    File.join(__dir__, "zer0_cms", *parts)
  end
end
