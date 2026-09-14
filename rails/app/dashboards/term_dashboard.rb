# frozen_string_literal: true

require "administrate/base_dashboard"

class TermDashboard < Administrate::BaseDashboard
  ATTRIBUTE_TYPES = {
    id: Field::Number.with_options(searchable: false),
    site: Field::BelongsTo,
    kind: Field::String.with_options(searchable: false),
    name: Field::String,
    pages_count: Field::Number.with_options(searchable: false)
  }.freeze

  COLLECTION_ATTRIBUTES = %i[name kind pages_count site].freeze
  SHOW_PAGE_ATTRIBUTES = %i[site kind name pages_count].freeze
  FORM_ATTRIBUTES = [].freeze

  COLLECTION_FILTERS = {
    tag: ->(resources) { resources.where(kind: "tag") },
    category: ->(resources) { resources.where(kind: "category") },
    author: ->(resources) { resources.where(kind: "author") },
    site: ->(resources, id) { resources.where(site_id: id) }
  }.freeze

  def display_resource(term)
    term.to_s
  end
end
