# frozen_string_literal: true

# One image a composition produced at a pipeline stage. Each stage is a distinct
# version so the workspace can show the lineage: the initial render, a
# Claude-review revision, and any OpenAI-enhanced follow-ups.
class CreateCompositionImages < ActiveRecord::Migration[8.1]
  def change
    create_table :composition_images do |t|
      t.references :composition, null: false, foreign_key: true
      # render | revision (Claude asked for a redo) | enhanced (further AI pass).
      t.string :stage, null: false
      # Which engine produced these pixels: local | openai | xai | ... The brief
      # may have been Claude-directed regardless — that's recorded in metadata.
      t.string :vendor, null: false
      # The exact prompt sent to the renderer (Claude's brief, or the template).
      t.text :prompt
      # Claude's review verdict/critique of this image, if it was reviewed.
      t.text :critique
      # Absolute path on disk (under the forge scratch dir). png or svg.
      t.string :path, null: false
      t.string :kind, null: false, default: "png"
      t.integer :byte_size
      t.integer :position, null: false, default: 0
      t.boolean :favorite, null: false, default: false
      t.json :metadata, null: false, default: {}

      t.timestamps
    end

    add_index :composition_images, %i[composition_id position]
  end
end
