# frozen_string_literal: true

class CreateArtifacts < ActiveRecord::Migration[8.1]
  def change
    create_table :artifacts do |t|
      t.references :run, null: false, foreign_key: true
      # png | svg — what the engine actually wrote.
      t.string :kind, null: false
      # Absolute path on disk. Artifacts land inside the target site (or the
      # scratch dir for studio runs) rather than in the app's storage, because
      # the point of a run is wiring images into a Jekyll site's assets.
      t.string :path, null: false
      t.integer :byte_size
      # Provider, model, prompt, seed, Claude critique — whatever the run knew.
      t.json :metadata, null: false, default: {}

      t.timestamps
    end

    add_index :artifacts, :path
  end
end
