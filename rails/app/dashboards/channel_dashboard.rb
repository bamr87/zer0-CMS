# frozen_string_literal: true

require "administrate/base_dashboard"

# Channels: the accounts a site may publish as. The token columns are
# deliberately absent from every attribute list — the form cannot set one and
# no page renders one; a token arrives only through LinkedIn's consent flow.
class ChannelDashboard < Administrate::BaseDashboard
  ATTRIBUTE_TYPES = {
    id: Field::Number,
    site: Field::BelongsTo,
    provider: Field::String.with_options(searchable: false),
    name: Field::String,
    author_urn: Field::String,
    member_urn: Field::String,
    scopes: Field::String.with_options(searchable: false),
    connected_at: Field::DateTime,
    expires_at: Field::DateTime,
    refresh_expires_at: Field::DateTime,
    checked_at: Field::DateTime,
    last_error: Field::Text.with_options(searchable: false),
    created_at: Field::DateTime,
    updated_at: Field::DateTime
  }.freeze

  COLLECTION_ATTRIBUTES = %i[name site author_urn connected_at expires_at].freeze
  SHOW_PAGE_ATTRIBUTES = %i[site provider author_urn member_urn scopes connected_at expires_at refresh_expires_at checked_at
                            last_error].freeze
  FORM_ATTRIBUTES = %i[site name author_urn].freeze

  COLLECTION_FILTERS = {
    connected: ->(resources) { resources.where.not(connected_at: nil) },
    failing: ->(resources) { resources.where.not(last_error: [nil, ""]) }
  }.freeze

  def display_resource(channel)
    channel.to_s
  end
end
