# frozen_string_literal: true

# A projection of one entry in tools/svg/library/MANIFEST.json.
#
# The manifest on disk stays the source of truth — it is what ships with the
# repo and what a human reviews in a diff. This table exists so the library is
# searchable and filterable in the UI, and is re-synced from the manifest
# rather than authored here.
#
# Provenance is not decorative: the library README makes source_url and license
# an obligation for anything sourced externally, so an entry missing them is a
# licensing problem, not a cosmetic gap.
class LibraryEntry < ApplicationRecord
  FIRST_PARTY = "first-party (this repository)"

  validates :file, presence: true, uniqueness: true
  validate :external_entries_carry_provenance

  scope :first_party, -> { where(source_url: FIRST_PARTY) }
  scope :external, -> { where.not(source_url: FIRST_PARTY) }
  scope :tagged, ->(tag) { where("tags LIKE ?", "%\"#{tag}\"%") }

  def first_party?
    source_url == FIRST_PARTY
  end

  def tag_list
    Array(tags)
  end

  def lint_clean?
    lint == "clean"
  end

  private

  def external_entries_carry_provenance
    return if first_party?
    return if source_url.present? && license.present?

    errors.add(:base, "external entries must carry a source_url and a license")
  end
end
