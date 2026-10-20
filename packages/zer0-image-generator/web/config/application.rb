require_relative "boot"

require "rails/all"

# Require the gems listed in Gemfile, including any gems
# you've limited to :test, :development, or :production.
Bundler.require(*Rails.groups)

module Web
  class Application < Rails::Application
    # Initialize configuration defaults for originally generated Rails version.
    config.load_defaults 8.1

    # Please, add to the `ignore` list any other `lib` subdirectories that do
    # not contain `.rb` files, or that should not be reloaded or eager loaded.
    # Common ones are `templates`, `generators`, or `middleware`, for example.
    config.autoload_lib(ignore: %w[assets tasks])

    # The image engine lives one level up, in the gem's `lib/`. It is required
    # directly off $LOAD_PATH rather than declared as a Bundler path gem
    # because the gemspec depends on Jekyll, and a web app has no business
    # loading Jekyll. `engine.rb` is the pure-Ruby entry point — no Jekyll, no
    # Rails, stdlib only — so the same code serves the CLI and this app.
    ENGINE_LIB = Rails.root.join("..", "lib").expand_path.freeze
    $LOAD_PATH.unshift(ENGINE_LIB.to_s) unless $LOAD_PATH.include?(ENGINE_LIB.to_s)
    require "zer0_image_generator/engine"

    # Repo root, so runs can resolve tools/svg/library, docs/samples, and the
    # scratch dirs the SVG loop writes to.
    config.repo_root = Rails.root.join("..").expand_path

    config.time_zone = "UTC"
  end
end
