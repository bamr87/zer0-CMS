# frozen_string_literal: true

# Zer0Cms — the ABC generator, the Ruby half of zer0-CMS.
#
# "ABC generator" and not "content engine": the phrase `content engine` is
# already taken in this repository by the `.cms/` contract engine the VS Code
# extension drives (src/core/contract/), and two things with one name is one
# thing nobody can grep for.
#
# The VS Code extension in this repo EDITS content; this library GENERATES it.
# Its first — and so far only — content type is the children's ABC book: a
# themed A–Z alphabet turned into a toddler picture book, illustrated by the
# zer0-image-generator plugin and published by drsai into the zer0-mistakes
# `books` collection.
#
# The extension was once a fork of Front Matter CMS and kept its interaction
# design on purpose, but has shared no code with it since 0.1.0; see
# ../../ATTRIBUTION.md.
#
# The whole generator is stdlib-only Ruby so the headless wizard (`bin/zer0-cms`)
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
