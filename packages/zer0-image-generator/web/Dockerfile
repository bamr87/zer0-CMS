# syntax=docker/dockerfile:1
#
# zer0-image-generator web app.
#
# Two stages: `development` (the default target for docker compose — includes
# the rasterizer chain, python3 for the port's differential tests, and dev
# gems) and `production` (slim, precompiled, no build toolchain).
#
# Build context is the REPOSITORY ROOT, not web/ — the app loads the engine
# from ../lib, so the image needs both trees.

# Matches the Ruby that resolved Gemfile.lock. Bumping this without
# regenerating the lock risks a Bundler that cannot read `BUNDLED WITH`.
ARG RUBY_VERSION=4.0.5
FROM docker.io/library/ruby:$RUBY_VERSION-slim AS base

WORKDIR /app/web

ENV BUNDLE_PATH=/usr/local/bundle \
    BUNDLE_WITHOUT="" \
    RAILS_LOG_TO_STDOUT=1 \
    LANG=C.UTF-8 \
    # Keep Bundler's config out of the bind-mounted app tree, so a dev machine's
    # web/.bundle/config can never override the container's bundle path.
    BUNDLE_APP_CONFIG=/usr/local/bundle/.bundle-config

# librsvg2-bin is the engine's preferred rasterizer (`rsvg-convert`): fastest
# and most predictable of the chain, and the one CI uses. ImageMagick provides
# the `montage` used for seed contact sheets, and is also the engine's
# third-choice rasterizer. Both are runtime deps, not build deps.
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
      curl \
      libjemalloc2 \
      libsqlite3-0 \
      librsvg2-bin \
      imagemagick \
      fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------

FROM base AS build

RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y build-essential git pkg-config && \
    rm -rf /var/lib/apt/lists/*

COPY web/Gemfile ./
# The Gemfile is app-only (the engine is required off $LOAD_PATH, not as a
# path gem), so this layer caches independently of the engine source.
# Install the exact Bundler the lockfile was written with: an older Bundler
# refuses a newer `BUNDLED WITH`, and that failure is opaque at build time.
RUN gem install bundler -v "$(tail -1 Gemfile.lock | tr -d ' ')" --no-document && \
    bundle config set --local path /usr/local/bundle && \
    bundle install --jobs 4 && \
    rm -rf /usr/local/bundle/cache/*.gem && \
    find /usr/local/bundle -name "*.c" -delete && \
    find /usr/local/bundle -name "*.o" -delete

COPY web/ /app/web/
COPY lib/ /app/lib/

RUN bundle exec bootsnap precompile app/ lib/ config/ || true

# ---------------------------------------------------------------------------
# Development: the target `docker compose` builds. Keeps python3 so the
# engine port's differential tests (Ruby output vs the Python oracle) can run
# inside the container, and keeps tools/ + test/ for the same reason.

FROM build AS development

RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y python3 python3-yaml && \
    rm -rf /var/lib/apt/lists/*

ENV RAILS_ENV=development

# Sites are bind-mounted here by compose; create it so a run with no mount
# fails with a clear "no sites registered" rather than a missing-path error.
RUN mkdir -p /sites

EXPOSE 3000
# Same entrypoint as production: it runs db:prepare before the server so the
# SQLite databases (including Solid Queue's) exist in the fresh named volume.
ENTRYPOINT ["/app/web/bin/docker-entrypoint"]
CMD ["bin/rails", "server", "-b", "0.0.0.0", "-p", "3000"]

# ---------------------------------------------------------------------------

FROM base AS production

ENV RAILS_ENV=production \
    BUNDLE_WITHOUT="development:test"

COPY --from=build /usr/local/bundle /usr/local/bundle
COPY --from=build /app /app

# Precompile without needing the real secret: assets must not bake one in.
# SECRET_KEY_BASE_DUMMY is the Rails 8 idiom for "booting only to precompile" —
# it also tells the encryption initializer not to demand real secrets yet.
RUN SECRET_KEY_BASE_DUMMY=1 bundle exec rails assets:precompile

RUN groupadd --system --gid 1000 rails && \
    useradd --system --uid 1000 --gid 1000 --create-home rails && \
    mkdir -p /sites db log storage tmp && \
    chown -R rails:rails /app /sites db log storage tmp
USER 1000:1000

EXPOSE 3000
ENTRYPOINT ["/app/web/bin/docker-entrypoint"]
CMD ["bin/rails", "server", "-b", "0.0.0.0", "-p", "3000"]
