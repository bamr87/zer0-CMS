# frozen_string_literal: true

require "administrate/field/base"

# A markdown textarea with a debounced live preview (the markdown-preview
# Stimulus controller posts to /admin/markdown_preview).
class MarkdownField < Administrate::Field::Base
  def self.searchable?
    false
  end

  def self.sortable?
    false
  end

  def to_s
    data.to_s
  end

  def html
    MarkdownRenderer.render(data)
  end

  def excerpt(length = 80)
    to_s.gsub(/\s+/, " ").strip.truncate(length)
  end
end
