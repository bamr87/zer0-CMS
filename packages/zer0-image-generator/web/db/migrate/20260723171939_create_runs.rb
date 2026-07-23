# frozen_string_literal: true

class CreateRuns < ActiveRecord::Migration[8.1]
  def change
    create_table :runs do |t|
      # Nullable: SVG-studio and library runs are not scoped to a Jekyll site.
      t.references :site, null: true, foreign_key: true
      # generate | dry_run | list_missing | enhance | studio | sweep | promote
      t.string :kind, null: false
      t.string :status, null: false, default: "pending"
      t.json :params, null: false, default: {}
      t.json :stats, null: false, default: {}
      # Streamed engine output, appended as the job runs so the UI can tail it.
      t.text :log, null: false, default: ""
      t.text :error
      t.datetime :started_at
      t.datetime :finished_at

      t.timestamps
    end

    add_index :runs, %i[status created_at]
    add_index :runs, :kind
  end
end
