# frozen_string_literal: true

require "administrate/base_dashboard"

class SiteDashboard < Administrate::BaseDashboard
  ATTRIBUTE_TYPES = {
    id: Field::Number,
    name: Field::String,
    path: Field::String,
    source_subdir: Field::String.with_options(searchable: false),
    collections_dir: Field::String.with_options(searchable: false),
    pages_count: Field::Number,
    assets_count: Field::Number,
    last_synced_at: Field::DateTime,
    sync_error: Field::Text.with_options(searchable: false),
    created_at: Field::DateTime,
    updated_at: Field::DateTime
  }.freeze

  COLLECTION_ATTRIBUTES = %i[name path pages_count assets_count last_synced_at].freeze
  SHOW_PAGE_ATTRIBUTES = %i[path source_subdir collections_dir pages_count assets_count last_synced_at sync_error].freeze
  FORM_ATTRIBUTES = %i[name path].freeze

  COLLECTION_FILTERS = {
    unsynced: ->(resources) { resources.where(last_synced_at: nil) },
    failing: ->(resources) { resources.where.not(sync_error: [nil, ""]) }
  }.freeze

  def display_resource(site)
    site.name
  end
end
