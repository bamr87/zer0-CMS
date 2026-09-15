# frozen_string_literal: true

require "administrate/base_dashboard"

class AssetDashboard < Administrate::BaseDashboard
  ATTRIBUTE_TYPES = {
    id: Field::Number.with_options(searchable: false),
    site: Field::BelongsTo,
    relative: Field::String,
    ext: Field::String.with_options(searchable: false),
    bytes: Field::Number.with_options(searchable: false),
    mtime: Field::DateTime,
    thumbnail: PreviewImageField.with_options(getter: :relative, root_relative: true)
  }.freeze

  COLLECTION_ATTRIBUTES = %i[thumbnail relative ext bytes mtime site].freeze
  SHOW_PAGE_ATTRIBUTES = %i[thumbnail site relative ext bytes mtime].freeze
  FORM_ATTRIBUTES = [].freeze

  COLLECTION_FILTERS = {
    site: ->(resources, id) { resources.where(site_id: id) },
    ext: ->(resources, ext) { resources.where(ext: ext.to_s.downcase) }
  }.freeze

  def display_resource(asset)
    asset.relative
  end
end
