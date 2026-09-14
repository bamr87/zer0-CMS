# frozen_string_literal: true

# One content file as Jekyll reads it: a page, post, draft or collection
# document. The row is an index entry; the file on disk is the truth, and
# PageEditor is the only writer.
class Page < ApplicationRecord
  belongs_to :site

  # Form-only values, read from the file by PageEditor for the editor. They
  # are never persisted: the index keeps derived values (a title falls back to
  # the slug), the form must show what the file actually says.
  attribute :body, :string
  attribute :date_text, :string
  attribute :base_digest, :string

  STATES = %w[error draft unpublished future live].freeze

  scope :drafts, -> { where(draft: true).or(where(status: "draft")) }
  scope :live, -> { where(draft: false, published: true, future: false).where.not(status: "draft") }

  def to_s
    title.presence || source_relative
  end

  def state
    return "error" if error.present?
    return "draft" if draft || status == "draft"
    return "unpublished" unless published
    return "future" if future

    "live"
  end
end
