# frozen_string_literal: true

Rails.application.routes.draw do
  namespace :admin do
    resources :sites do
      post :sync, on: :member
      post :discover, on: :collection
    end
    resources :pages do
      post :duplicate, on: :member
      post :generate_preview, on: :member
    end
    resources :assets, only: %i[index show]
    resources :terms, only: %i[index show]
    post "markdown_preview", to: "markdown_previews#create", as: :markdown_preview

    # LinkedIn distribution (docs/DISTRIBUTION.md): the accounts a site posts
    # as, and the queue → approve → publish path over a site's own files.
    resources :channels do
      member do
        post :connect
        post :check
        post :disconnect
      end
    end
    get "distribution", to: "distribution#index", as: :distribution
    scope "distribution/:site_id", controller: :distribution, as: :distribution, constraints: { draft: /[A-Za-z0-9][A-Za-z0-9._-]*/ } do
      get "/", action: :show, as: :site
      post "drafts", action: :create_draft, as: :drafts
      get "drafts/:draft", action: :draft, as: :draft
      post "drafts/:draft/approve", action: :approve, as: :approve
      post "drafts/:draft/publish", action: :publish, as: :publish
      post "statistics", action: :statistics, as: :statistics
    end

    root to: "sites#index"
  end

  root to: redirect("/admin")

  # Where LinkedIn returns the account owner after consent.
  get "oauth/linkedin/callback", to: "linkedin_callbacks#show", as: :linkedin_callback

  # Images inside a registered site, by absolute path (thumbnails, media).
  get "files/*path", to: "files#show", as: :file, format: false

  get  "abc/new",          to: "abc_books#new",     as: :new_abc_book
  post "abc/preview",      to: "abc_books#preview", as: :preview_abc_book
  post "abc/export",       to: "abc_books#export",  as: :export_abc_book
  get  "abc/catalog.json", to: "abc_books#catalog", as: :abc_catalog

  get "up", to: "rails/health#show", as: :rails_health_check
end
