# frozen_string_literal: true

# A file a run produced, recorded by absolute path.
#
# The bytes are deliberately NOT copied into the app's storage: a preview image
# only has value sitting in the target site's assets directory with front
# matter pointing at it, so the app records where it went instead of owning it.
class Artifact < ApplicationRecord
  KINDS = %w[png svg].freeze

  belongs_to :run

  validates :kind, presence: true, inclusion: { in: KINDS }
  validates :path, presence: true

  scope :images, -> { where(kind: "png") }

  def pathname
    Pathname.new(path)
  end

  # An artifact can vanish between runs — the user may rebuild, clean, or move
  # the site — so every read path has to tolerate its absence.
  def exists?
    pathname.file?
  end

  def filename
    File.basename(path)
  end
end
