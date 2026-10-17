# frozen_string_literal: true

# One piece produced in the SVG studio: a generator, its knobs, and the SVG
# that came out.
#
# The SVG is stored inline rather than as a file because these are small (a few
# KB — the generators are parametric, not hand-authored) and the studio's whole
# workflow is comparing variants side by side, which wants them queryable.
#
# Every generator is deterministic: generator + params + seed reproduces the
# bytes exactly. That is what makes a saved render a recipe rather than a
# snapshot, and it is pinned by the engine's golden tests.
class StudioRender < ApplicationRecord
  # Mirrors the ported generators. `banner` is the engine's own `local`
  # provider template, exposed here so the studio can sweep the real thing
  # rather than a lookalike.
  GENERATORS = %w[banner flowfield lsystem lowpoly mandala starmap invaders pixelquest].freeze

  belongs_to :run, optional: true

  validates :generator, presence: true, inclusion: { in: GENERATORS }
  validates :seed, presence: true, numericality: { only_integer: true }

  scope :favorites, -> { where(favorite: true) }
  scope :recent, -> { order(created_at: :desc) }
  scope :for_generator, ->(name) { where(generator: name) }

  def lint_clean?
    Array(lint["errors"]).empty? && Array(lint["warnings"]).empty?
  end

  def lint_errors
    Array(lint["errors"])
  end

  def lint_warnings
    Array(lint["warnings"])
  end

  # A stable label for the piece, matching the naming convention the committed
  # samples use (e.g. "lsystem-tree-verdant-7").
  def slug
    [generator, params["species"], params["palette"], seed].compact_blank.join("-")
  end
end
