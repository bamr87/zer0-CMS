# frozen_string_literal: true

# One invocation of the engine, queued and executed by a background job.
#
# Runs are the app's audit trail: every generation, dry run, studio render and
# library promotion lands here with the parameters it used and the log it
# produced, so a result is always traceable back to the settings that made it.
class Run < ApplicationRecord
  # `generate` and `enhance` cost money; `dry_run` and `list_missing` are the
  # safe reconnaissance modes and are what the UI defaults to.
  KINDS = %w[generate dry_run list_missing enhance studio sweep promote].freeze
  STATUSES = %w[pending running succeeded failed cancelled].freeze
  TERMINAL_STATUSES = %w[succeeded failed cancelled].freeze

  # Site-scoped kinds must have a site; studio/library kinds must not.
  SITE_KINDS = %w[generate dry_run list_missing enhance].freeze

  belongs_to :site, optional: true
  has_many :artifacts, dependent: :destroy

  validates :kind, presence: true, inclusion: { in: KINDS }
  validates :status, presence: true, inclusion: { in: STATUSES }
  validate :site_presence_matches_kind

  scope :recent, -> { order(created_at: :desc) }
  scope :active, -> { where(status: %w[pending running]) }
  scope :finished, -> { where(status: TERMINAL_STATUSES) }

  def finished?
    TERMINAL_STATUSES.include?(status)
  end

  def running?
    status == "running"
  end

  def duration
    return nil unless started_at

    (finished_at || Time.current) - started_at
  end

  def start!
    update!(status: "running", started_at: Time.current)
  end

  def finish!(stats: {})
    update!(status: "succeeded", stats: stats, finished_at: Time.current)
  end

  def fail!(message)
    update!(status: "failed", error: message, finished_at: Time.current)
  end

  # Appends to the log with a single UPDATE rather than read-modify-write, so
  # concurrent engine workers streaming into the same run cannot lose lines.
  def append_log(text)
    return if text.blank?

    self.class.where(id: id).update_all(
      ["log = COALESCE(log, '') || ?, updated_at = ?", text, Time.current]
    )
  end

  private

  def site_presence_matches_kind
    if SITE_KINDS.include?(kind) && site_id.blank?
      errors.add(:site, "is required for a #{kind} run")
    elsif !SITE_KINDS.include?(kind) && site_id.present?
      errors.add(:site, "does not apply to a #{kind} run")
    end
  end
end
