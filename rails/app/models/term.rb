# frozen_string_literal: true

# A tag, category or author, counted over one site's pages.
class Term < ApplicationRecord
  KINDS = %w[tag category author].freeze

  belongs_to :site

  validates :kind, inclusion: { in: KINDS }

  def to_s
    "#{kind}: #{name}"
  end

  # The pages filter for this term, in Administrate's search syntax. Names
  # with whitespace cannot be a filter argument, so they fall back to a
  # plain text search.
  def pages_search
    return "site:#{site_id} #{name}" if name.match?(/\s/)

    "site:#{site_id} #{kind}:#{name}"
  end
end
