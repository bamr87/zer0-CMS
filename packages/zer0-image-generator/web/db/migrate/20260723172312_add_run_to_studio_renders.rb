# frozen_string_literal: true

class AddRunToStudioRenders < ActiveRecord::Migration[8.1]
  def change
    # Nullable: the generators are pure Ruby and render in milliseconds, so the
    # studio renders synchronously and only associates a Run when a piece came
    # out of a queued batch (a seed sweep), not for every interactive render.
    add_reference :studio_renders, :run, null: true, foreign_key: true
  end
end
