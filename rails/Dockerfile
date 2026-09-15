# syntax=docker/dockerfile:1
#
# zer0-CMS: the fleet CMS (Rails 8.1 on Administrate) and the ABC wizard.
# The build context is rails/ (see rails/.dockerignore); docker-compose.yml at
# the repository root builds it as the `cms` service.
#
# Three stages. `base` carries only what runs: sqlite, jemalloc, and python3 +
# PyYAML + librsvg for the image-engine bridge (the released
# zer0-image-generator gem's engine is Python; rsvg-convert turns its local
# SVG into a PNG). `build` adds the toolchain, installs the locked bundle
# deployment-style and precompiles the assets. The final stage copies both
# and runs as an unprivileged user.

# Matches rails/.ruby-version and the Ruby that resolved Gemfile.lock.
ARG RUBY_VERSION=4.0.5
FROM docker.io/library/ruby:$RUBY_VERSION-slim AS base

WORKDIR /app

ENV RAILS_ENV=production \
    BUNDLE_PATH=/usr/local/bundle \
    BUNDLE_DEPLOYMENT=1 \
    BUNDLE_WITHOUT=test \
    BUNDLE_APP_CONFIG=/usr/local/bundle/.bundle-config \
    RAILS_LOG_TO_STDOUT=1 \
    LANG=C.UTF-8

RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
      curl \
      libjemalloc2 \
      libsqlite3-0 \
      libyaml-0-2 \
      librsvg2-bin \
      python3 \
      python3-yaml && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------

FROM base AS build

RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y build-essential git pkg-config libyaml-dev && \
    rm -rf /var/lib/apt/lists/*

# Gemfile and Gemfile.lock (and .ruby-version, which the Gemfile reads) first,
# so the bundle layer caches independently of the app. Install the exact
# Bundler the lock was written with: an older one refuses a newer BUNDLED WITH.
COPY .ruby-version Gemfile Gemfile.lock ./
RUN gem install bundler -v "$(tail -1 Gemfile.lock | tr -d ' ')" --no-document && \
    bundle install --jobs 4 && \
    rm -rf /usr/local/bundle/cache/*.gem && \
    find /usr/local/bundle -name "*.c" -delete && \
    find /usr/local/bundle -name "*.o" -delete

COPY . .

# Propshaft serves digested files from public/assets in production. The dummy
# secret exists only for this step and is never baked into the image.
RUN SECRET_KEY_BASE_DUMMY=1 bin/rails assets:precompile

# ---------------------------------------------------------------------------

FROM base

ARG UID=1000
ARG GID=1000

COPY --from=build /usr/local/bundle /usr/local/bundle
COPY --from=build /app /app

# storage/ is where compose mounts the named SQLite volume; a fresh named
# volume takes this directory's ownership, so the database stays writable.
# On Linux, build with --build-arg UID=$(id -u) --build-arg GID=$(id -g) to
# write to bind-mounted sites as their owner.
RUN groupadd --system --gid "$GID" rails && \
    useradd --system --uid "$UID" --gid "$GID" --create-home --shell /usr/sbin/nologin rails && \
    mkdir -p /sites storage log tmp && \
    chown -R rails:rails storage log tmp
USER rails:rails

EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=40s --retries=12 \
  CMD curl -fsS http://localhost:3000/up || exit 1
ENTRYPOINT ["/app/bin/docker-entrypoint"]
CMD ["bin/rails", "server", "-b", "0.0.0.0", "-p", "3000"]
