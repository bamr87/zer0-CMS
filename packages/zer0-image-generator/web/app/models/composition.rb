# frozen_string_literal: true

# An interactive image-creation session.
#
# The workflow mirrors the engine's three stages — analyze (Claude writes an art
# brief), produce (a renderer makes the image), review (Claude inspects it) —
# but driven interactively for a single image rather than as a batch over a
# site's front matter. "Process further with OpenAI" then runs the enhance/edit
# stage on a chosen version.
class Composition < ApplicationRecord
  RENDERERS = %w[openai xai stability gemini local].freeze
  PROMPT_ENGINES = %w[claude xai template].freeze
  REVIEW_ENGINES = %w[claude xai none].freeze
  STATUSES = %w[draft working ready failed].freeze

  has_many :images, class_name: "CompositionImage", dependent: :destroy

  validates :title, presence: true
  validates :provider, inclusion: { in: RENDERERS }
  validates :prompt_engine, inclusion: { in: PROMPT_ENGINES }
  validates :review_engine, inclusion: { in: REVIEW_ENGINES }
  validates :status, inclusion: { in: STATUSES }

  scope :recent, -> { order(created_at: :desc) }

  def working? = status == "working"
  def latest_image = images.order(position: :desc, id: :desc).first

  def start!
    update!(status: "working", error: nil)
  end

  def ready!
    update!(status: "ready")
  end

  def fail!(message)
    update!(status: "failed", error: message)
  end

  # Single-UPDATE append so concurrent stage output can't lose lines.
  def append_log(text)
    return if text.blank?

    self.class.where(id: id).update_all(
      ["log = COALESCE(log, '') || ?, updated_at = ?", text, Time.current]
    )
  end

  # Whether this composition's chosen pipeline needs Claude (art direction or
  # review). Used to warn when no Claude credential is configured.
  def uses_claude?
    (prompt_engine == "claude" || review_engine == "claude") && provider != "local"
  end

  def uses_xai_llm?
    (prompt_engine == "xai" || review_engine == "xai") && provider != "local"
  end
end
