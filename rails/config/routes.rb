# frozen_string_literal: true

Rails.application.routes.draw do
  root "abc_books#new"

  # The ABC book wizard.
  get  "abc/new",     to: "abc_books#new",     as: :new_abc_book
  post "abc/preview", to: "abc_books#preview", as: :preview_abc_book
  post "abc/export",  to: "abc_books#export",  as: :export_abc_book

  # JSON: the art-style catalog + bundled themes (drives the form's menus / an SPA).
  get "abc/catalog.json", to: "abc_books#catalog"
end
