# frozen_string_literal: true

require "administrate/search"

# Administrate::Search with one change: the LIKE value is lowercased with
# String#downcase. Administrate 1.0 calls String#mb_chars, which Rails 8.1
# deprecates (removed in 8.2).
class DashboardSearch < Administrate::Search
  private

  def query_values
    fields_count = search_attributes.sum { |attr| searchable_fields(attr).count }
    ["%#{term.downcase}%"] * fields_count
  end
end
