Rails.application.routes.draw do
  # Load-balancer / uptime health check and Docker healthcheck target.
  get "up" => "rails/health#show", as: :rails_health_check

  root "dashboard#show"

  resources :sites do
    # A site's `preview_images:` block, edited as a form and round-tripped back
    # into _config.yml.
    resource :config, only: %i[show update], controller: "site_configs"
    # Content files and their preview status.
    resources :content, only: %i[index], controller: "site_content"
    # Launching a run is site-scoped (it needs a site); a run's own pages are
    # not, so they live at the top level below.
    resources :runs, only: %i[index new create]
    member { post :rescan }
  end

  # A run's own pages, and the cross-site index of every run.
  resources :runs, only: %i[index show] do
    member { post :cancel }
  end

  resources :credentials, except: %i[show]

  # The interactive image forge: Claude directs, a renderer produces, and OpenAI
  # can process a version further.
  resources :compositions do
    member { post :compose } # regenerate on the same brief
  end
  resources :composition_images, only: [] do
    member do
      post :enhance   # further processing with OpenAI
      post :favorite
    end
  end

  # The SVG studio: a knob form per generator, plus saved renders.
  namespace :studio do
    root "renders#index"
    # `new` is the knob form (generator chosen via ?generator=…); preview
    # renders without saving, sweep queues a contact sheet.
    resources :renders, only: %i[index new show create destroy] do
      collection do
        post :preview
        post :sweep
      end
      member { post :favorite }
    end
  end

  # The example/style library and FreeSVG sourcing.
  resources :library_entries, only: %i[index show], path: "library" do
    collection { post :sync } # re-project MANIFEST.json into the DB
  end
  namespace :freesvg do
    get :search
    post :promote
  end

  # Serves generated artifacts (PNGs/SVGs) that live outside public/ — inside a
  # registered site or the studio scratch dir — for preview in the UI.
  get "files/*path" => "files#show", as: :file, format: false
end
