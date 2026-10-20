# frozen_string_literal: true

class CreateStudioRenders < ActiveRecord::Migration[8.1]
  def change
    create_table :studio_renders do |t|
      # banner | flowfield | lsystem | lowpoly | mandala | starmap | invaders |
      # pixelquest — the ported generator that produced this piece.
      t.string :generator, null: false
      # The generator's knobs (palette, species, iterations, ...). Kept as a
      # blob rather than columns because each generator has its own knob set.
      t.json :params, null: false, default: {}
      t.integer :seed, null: false, default: 1
      t.text :svg
      t.string :png_path
      # svg-check findings, so the studio can show lint inline with the render.
      t.json :lint, null: false, default: {}
      t.boolean :favorite, null: false, default: false

      t.timestamps
    end

    add_index :studio_renders, %i[generator seed]
    add_index :studio_renders, :favorite
  end
end
