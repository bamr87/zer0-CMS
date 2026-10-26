# The Jekyll-theme option's Jekyll 4 server (PLAN P2, ADR 0006 decision 4).
#
# Jekyll 4.4.1 with exactly the plugins and dependencies the Jekyll 4 sites were
# recorded with in P1 — every gem and version of their `built_with`
# (web/site/fixtures/<site>/manifest.json) — on the Ruby those recordings used
# (ruby:3.3, Ruby 3.3.12), so a build here reproduces them. Ruby lives in this
# image only: nothing in the repository is Ruby, and no Gemfile pins these
# (ADR 0006 decision 1). tools/jekyll_theme.py builds the image (its tag carries
# a digest of this file) and runs `jekyll build` in it; the other server, GitHub
# Pages' own builder, needs no file here. Change a version only together with a
# re-recording that says why.
FROM ruby:3.3.12-trixie

RUN gem install --no-document --ignore-dependencies \
      addressable:2.9.0 base64:0.3.0 bigdecimal:4.1.3 colorator:1.1.0 concurrent-ruby:1.3.8 \
      csv:3.3.6 em-websocket:0.5.3 eventmachine:1.2.7 ffi:1.17.4 forwardable-extended:2.6.0 \
      google-protobuf:4.36.2 http_parser.rb:0.8.1 i18n:1.15.2 json:2.21.2 kramdown:2.5.2 \
      kramdown-parser-gfm:1.1.0 liquid:4.0.4 listen:3.10.1 logger:1.7.0 mercenary:0.4.0 \
      openssl:4.0.2 pathutil:0.16.2 public_suffix:7.0.5 rake:13.4.2 rb-fsevent:0.11.2 \
      rb-inotify:0.11.1 rexml:3.4.4 rouge:4.7.0 rubyzip:3.7.0 safe_yaml:1.0.5 \
      sass-embedded:1.106.1 terminal-table:3.0.2 unicode-display_width:2.6.0 webrick:1.9.2 \
      jekyll:4.4.1 jekyll-sass-converter:3.1.0 jekyll-watch:2.2.1 \
      jekyll-feed:0.18.0 jekyll-include-cache:0.3.1 jekyll-paginate:1.1.0 \
      jekyll-remote-theme:0.6.2 jekyll-seo-tag:2.9.1 jekyll-sitemap:1.4.0

WORKDIR /srv/site
ENTRYPOINT ["jekyll"]
