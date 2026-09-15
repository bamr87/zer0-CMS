# frozen_string_literal: true

# An image under a site's assets/, images/ or preview output directory.
class Asset < ApplicationRecord
  belongs_to :site

  def to_s
    relative
  end
end
