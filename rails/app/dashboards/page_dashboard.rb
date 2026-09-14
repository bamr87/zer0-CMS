# frozen_string_literal: true

require "administrate/base_dashboard"

class PageDashboard < Administrate::BaseDashboard
  JSON_EACH = "EXISTS (SELECT 1 FROM json_each(pages.%<column>s) WHERE json_each.value = ?)"

  ATTRIBUTE_TYPES = {
    id: Field::Number.with_options(searchable: false),
    site: Field::BelongsTo,
    title: Field::String,
    description: Field::Text.with_options(searchable: true),
    author: Field::String,
    source_relative: Field::String.with_options(truncate: 90),
    relative: Field::String.with_options(searchable: false),
    kind: Field::String.with_options(searchable: false),
    collection: Field::String.with_options(searchable: false),
    state: StateField,
    status: Field::String.with_options(searchable: false),
    date: Field::DateTime,
    date_text: Field::String.with_options(searchable: false, sortable: false),
    lastmod: Field::DateTime,
    layout: Field::String.with_options(searchable: false),
    permalink: Field::String.with_options(searchable: false),
    preview: PreviewImageField,
    draft: Field::Boolean,
    published: Field::Boolean,
    future: Field::Boolean,
    tags: TagListField,
    categories: TagListField,
    front_matter: Field::Text.with_options(getter: ->(field) { JSON.pretty_generate(field.resource.front_matter || {}) }),
    error: Field::Text.with_options(searchable: false),
    digest: Field::String.with_options(searchable: false),
    bytes: Field::Number.with_options(searchable: false),
    mtime: Field::DateTime,
    body: MarkdownField
  }.freeze

  COLLECTION_ATTRIBUTES = %i[title collection kind state date site].freeze

  SHOW_PAGE_ATTRIBUTES = {
    "" => %i[site source_relative collection kind state date preview tags categories author description],
    "Front matter" => %i[status layout permalink lastmod draft published future front_matter],
    "File" => %i[error bytes mtime digest],
    "Body" => %i[body]
  }.freeze

  FORM_ATTRIBUTES_EDIT = {
    "" => %i[title description author date_text preview tags categories],
    "Publishing" => %i[status layout permalink draft published],
    "Body" => %i[body]
  }.freeze
  FORM_ATTRIBUTES = FORM_ATTRIBUTES_EDIT

  # Search terms match title, description, author and source path; these
  # narrow the result: `draft: live: future: error: collection:docs site:3
  # kind:post tag:ruby category:hacks author:amr`. `missing_preview:` (or
  # `missing_preview:<site id>`) asks the image engine which files it would
  # draw a preview for.
  COLLECTION_FILTERS = {
    draft: ->(resources) { resources.where(draft: true).or(resources.where(status: "draft")) },
    live: ->(resources) { resources.where(draft: false, published: true, future: false).where.not(status: "draft") },
    future: ->(resources) { resources.where(future: true) },
    error: ->(resources) { resources.where.not(error: [nil, ""]) },
    collection: ->(resources, name) { resources.where(collection: name) },
    site: ->(resources, id) { resources.where(site_id: id) },
    kind: ->(resources, kind) { resources.where(kind: kind) },
    author: ->(resources, name) { resources.where(author: name) },
    tag: ->(resources, name) { resources.where(format(JSON_EACH, column: "tags"), name) },
    category: ->(resources, name) { resources.where(format(JSON_EACH, column: "categories"), name) },
    missing_preview: ->(resources, site_id = nil) { ImageEngine.filter_missing(resources, site_id) }
  }.freeze

  def display_resource(page)
    page.to_s
  end
end
