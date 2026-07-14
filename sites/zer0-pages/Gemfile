# frozen_string_literal: true

source "https://rubygems.org"

gem "jekyll", "~> 4.3"

# zer0-mistakes theme, consumed as the published gem. For local theme
# development you may temporarily use:
#   gem "jekyll-theme-zer0", path: "../github/zer0-mistakes"
# but the committed Gemfile must reference the published gem.
gem "jekyll-theme-zer0", "~> 1.25"

group :jekyll_plugins do
  gem "jekyll-seo-tag"
  gem "jekyll-sitemap"
  gem "jekyll-feed"
  # {% include_cached %} — required by the theme's root layout and footer.
  gem "jekyll-include-cache"
  # `jekyll preview-images` — AI preview/social banners, extracted from the
  # zer0-mistakes theme (see `preview_images:` in _config.yml).
  gem "zer0-image-generator", "~> 0.2"
end

# `jekyll serve` on Ruby >= 3.0 (webrick is no longer bundled with Ruby).
gem "webrick", "~> 1.8"

# Stdlib gems extracted from Ruby's default set (needed on Ruby >= 3.4).
gem "base64"
gem "csv"
gem "logger"
