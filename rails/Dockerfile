# syntax=docker/dockerfile:1
#
# zer0-CMS ABC wizard. Build context is rails/.

FROM docker.io/library/ruby:3.3-slim

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

COPY Gemfile ./
RUN gem install bundler --no-document && bundle install --jobs 4

COPY . .

EXPOSE 3000
ENTRYPOINT ["/app/bin/docker-entrypoint"]
CMD ["bundle", "exec", "puma", "-b", "tcp://0.0.0.0:3000", "config.ru"]
