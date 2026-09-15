# frozen_string_literal: true

require "administrate/field/base"

# A list of strings shown as chips and edited as one comma-separated input.
# The submitted text is split back into a list by PageEditor.
class TagListField < Administrate::Field::Base
  def self.searchable?
    false
  end

  def self.sortable?
    false
  end

  def items
    Array(data).map(&:to_s).reject(&:empty?)
  end

  def to_s
    items.join(", ")
  end
end
