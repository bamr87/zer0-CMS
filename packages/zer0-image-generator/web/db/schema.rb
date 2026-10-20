# This file is auto-generated from the current state of the database. Instead
# of editing this file, please use the migrations feature of Active Record to
# incrementally modify your database, and then regenerate this schema definition.
#
# This file is the source Rails uses to define your schema when running `bin/rails
# db:schema:load`. When creating a new database, `bin/rails db:schema:load` tends to
# be faster and is potentially less error prone than running all of your
# migrations from scratch. Old migrations may fail to apply correctly if those
# migrations use external dependencies or application code.
#
# It's strongly recommended that you check this file into your version control system.

ActiveRecord::Schema[8.1].define(version: 2026_07_23_200322) do
  create_table "artifacts", force: :cascade do |t|
    t.integer "byte_size"
    t.datetime "created_at", null: false
    t.string "kind", null: false
    t.json "metadata", default: {}, null: false
    t.string "path", null: false
    t.integer "run_id", null: false
    t.datetime "updated_at", null: false
    t.index ["path"], name: "index_artifacts_on_path"
    t.index ["run_id"], name: "index_artifacts_on_run_id"
  end

  create_table "composition_images", force: :cascade do |t|
    t.integer "byte_size"
    t.integer "composition_id", null: false
    t.datetime "created_at", null: false
    t.text "critique"
    t.boolean "favorite", default: false, null: false
    t.string "kind", default: "png", null: false
    t.json "metadata", default: {}, null: false
    t.string "path", null: false
    t.integer "position", default: 0, null: false
    t.text "prompt"
    t.string "stage", null: false
    t.datetime "updated_at", null: false
    t.string "vendor", null: false
    t.index ["composition_id", "position"], name: "index_composition_images_on_composition_id_and_position"
    t.index ["composition_id"], name: "index_composition_images_on_composition_id"
  end

  create_table "compositions", force: :cascade do |t|
    t.text "brief", default: "", null: false
    t.datetime "created_at", null: false
    t.text "error"
    t.text "log", default: "", null: false
    t.string "model"
    t.string "prompt_engine", default: "claude", null: false
    t.string "provider", default: "local", null: false
    t.string "quality"
    t.string "review_engine", default: "claude", null: false
    t.string "size"
    t.string "status", default: "draft", null: false
    t.string "style"
    t.string "style_modifiers"
    t.string "title", null: false
    t.datetime "updated_at", null: false
    t.index ["status", "created_at"], name: "index_compositions_on_status_and_created_at"
  end

  create_table "credentials", force: :cascade do |t|
    t.text "api_key"
    t.datetime "created_at", null: false
    t.string "label"
    t.datetime "last_used_at"
    t.string "provider", null: false
    t.datetime "updated_at", null: false
    t.index ["provider"], name: "index_credentials_on_provider", unique: true
  end

  create_table "library_entries", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "file", null: false
    t.string "license"
    t.string "license_url"
    t.string "lint"
    t.float "size_kb"
    t.string "source_url"
    t.json "tags", default: [], null: false
    t.string "title"
    t.datetime "updated_at", null: false
    t.index ["file"], name: "index_library_entries_on_file", unique: true
  end

  create_table "runs", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.text "error"
    t.datetime "finished_at"
    t.string "kind", null: false
    t.text "log", default: "", null: false
    t.json "params", default: {}, null: false
    t.integer "site_id"
    t.datetime "started_at"
    t.json "stats", default: {}, null: false
    t.string "status", default: "pending", null: false
    t.datetime "updated_at", null: false
    t.index ["kind"], name: "index_runs_on_kind"
    t.index ["site_id"], name: "index_runs_on_site_id"
    t.index ["status", "created_at"], name: "index_runs_on_status_and_created_at"
  end

  create_table "sites", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.datetime "last_scanned_at"
    t.string "name", null: false
    t.text "notes"
    t.string "path", null: false
    t.string "source_subdir", default: "", null: false
    t.datetime "updated_at", null: false
    t.index ["path"], name: "index_sites_on_path", unique: true
  end

  create_table "studio_renders", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.boolean "favorite", default: false, null: false
    t.string "generator", null: false
    t.json "lint", default: {}, null: false
    t.json "params", default: {}, null: false
    t.string "png_path"
    t.integer "run_id"
    t.integer "seed", default: 1, null: false
    t.text "svg"
    t.datetime "updated_at", null: false
    t.index ["favorite"], name: "index_studio_renders_on_favorite"
    t.index ["generator", "seed"], name: "index_studio_renders_on_generator_and_seed"
    t.index ["run_id"], name: "index_studio_renders_on_run_id"
  end

  add_foreign_key "artifacts", "runs"
  add_foreign_key "composition_images", "compositions"
  add_foreign_key "runs", "sites"
  add_foreign_key "studio_renders", "runs"
end
