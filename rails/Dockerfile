# syntax=docker/dockerfile:1
#
# zer0-CMS fleet CMS (Rails 8.1 on Administrate) + ABC wizard. Build context is rails/.

FROM docker.io/library/ruby:4.0.5-slim

WORKDIR /app

ENV BUNDLE_PATH=/usr/local/bundle \
    BUNDLE_APP_CONFIG=/usr/local/bundle/.bundle-config \
    RAILS_LOG_TO_STDOUT=1 \
    LANG=C.UTF-8

RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
      build-essential \
      curl \
      git \
      libsqlite3-dev \
      libyaml-dev \
      sqlite3 && \
    rm -rf /var/lib/apt/lists/*

COPY .ruby-version Gemfile Gemfile.lock ./
RUN gem install bundler --no-document && bundle install --jobs 4

COPY . .

EXPOSE 3000
ENTRYPOINT ["/app/bin/docker-entrypoint"]
CMD ["bin/rails", "server", "-b", "0.0.0.0", "-p", "3000"]
