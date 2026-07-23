# frozen_string_literal: true

class LibraryEntriesController < ApplicationController
  def index
    # Empty on first visit — offer a one-click sync rather than auto-importing,
    # so the user sees where the data comes from.
    LibrarySync.call if LibraryEntry.none? && LibrarySync.manifest_path.file?
    @entries = LibraryEntry.order(:file)
    @entries = @entries.tagged(params[:tag]) if params[:tag].present?
    @tags = @entries.flat_map(&:tag_list).tally.sort_by { |_, n| -n }.first(24)
  rescue LibrarySync::Error => e
    @error = e.message
    @entries = LibraryEntry.order(:file)
  end

  def show
    @entry = LibraryEntry.find(params[:id])
    file = Rails.application.config.repo_root.join(@entry.file)
    @svg = file.file? ? file.read : nil
  end

  def sync
    count = LibrarySync.call
    redirect_to library_entries_path, notice: "Synced #{count} entries from MANIFEST.json."
  rescue LibrarySync::Error => e
    redirect_to library_entries_path, alert: e.message
  end
end
