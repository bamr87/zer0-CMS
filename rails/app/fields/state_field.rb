# frozen_string_literal: true

require "administrate/field/base"

# The page's derived state (error, draft, unpublished, future, live) as a
# badge. Computed, so it is neither searchable nor sortable.
class StateField < Administrate::Field::Base
  def self.searchable?
    false
  end

  def self.sortable?
    false
  end

  def state
    data.to_s
  end
end
