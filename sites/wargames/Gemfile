source "https://rubygems.org"

# Modern Jekyll + the remote-theme plugin (loads bamr87/zer0-mistakes from
# GitHub). The site is built and deployed via GitHub Actions
# (.github/workflows/jekyll-gh-pages.yml) rather than the legacy github-pages
# gem, so this pins current Jekyll and only the plugins the theme needs.
gem "jekyll", "~> 4.3"
gem "jekyll-remote-theme"

group :jekyll_plugins do
  gem "jekyll-feed"
  gem "jekyll-sitemap"
  gem "jekyll-seo-tag"
  gem "jekyll-include-cache"
end

# Ruby 3.0+ no longer ships webrick in the standard library (needed by serve).
gem "webrick", "~> 1.8"
