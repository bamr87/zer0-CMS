# frozen_string_literal: true

# An interactive image-creation session: a brief, the knobs, and the images it
# produced. Distinct from a Run (which is a batch generation over a Jekyll
# site's front matter) — a Composition is a single image the user is iterating
# on, directed by Claude and rendered by the chosen provider.
class CreateCompositions < ActiveRecord::Migration[8.1]
  def change
    create_table :compositions do |t|
      t.string :title, null: false
      # The article/description text fed to Claude's art director.
      t.text :brief, null: false, default: ""
      t.string :style
      t.string :style_modifiers
      # Renderer that produces pixels: openai | xai | stability | gemini | local.
      t.string :provider, null: false, default: "local"
      t.string :model
      t.string :size
      t.string :quality
      # claude (Claude writes the brief) | template (fixed prompt).
      t.string :prompt_engine, null: false, default: "claude"
      # claude (Claude vision-reviews) | none.
      t.string :review_engine, null: false, default: "claude"
      t.string :status, null: false, default: "draft"
      t.text :log, null: false, default: ""
      t.text :error

      t.timestamps
    end

    add_index :compositions, %i[status created_at]
  end
end
