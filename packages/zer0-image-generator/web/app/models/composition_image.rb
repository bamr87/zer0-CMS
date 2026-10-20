# frozen_string_literal: true

# One version an image passed through: the initial render, a Claude-review
# revision, or an OpenAI-enhanced follow-up. Bytes live on disk (under the forge
# scratch dir) and are served through FilesController; the row records where and
# how each version came to be.
class CompositionImage < ApplicationRecord
  STAGES = %w[render revision enhanced].freeze

  STAGE_LABELS = {
    "render" => "Rendered", "revision" => "Claude revision", "enhanced" => "OpenAI enhanced"
  }.freeze

  belongs_to :composition

  validates :stage, inclusion: { in: STAGES }
  validates :path, presence: true
  validates :kind, inclusion: { in: %w[png svg] }

  scope :ordered, -> { order(:position, :id) }

  def pathname = Pathname.new(path)
  def exists? = pathname.file?
  def filename = File.basename(path)

  # Was this image's brief actually written/revised by Claude (not merely
  # requested — a local render or a failed Claude call is not claude-directed).
  def claude_directed? = metadata["claude_directed"] == true

  def stage_label = STAGE_LABELS.fetch(stage, stage)
end
