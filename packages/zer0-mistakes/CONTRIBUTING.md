---
title: "Contributing to Zer0-Mistakes"
description: "How to propose a change to the Zer0-Mistakes theme: where pull requests go, setting up with Docker, branches and commits, the tests to run, and what reviewers expect."
layout: default
permalink: /contributing/
tags: [contributing, development, documentation, docker, jekyll, ai-collaboration]
categories: [Documentation, Development]
lastmod: 2026-10-22T00:00:00.000Z
author: "Zer0-Mistakes Development Team"
keywords:
  primary: ["contributing guide", "developer documentation", "open source"]
  secondary: ["jekyll theme", "docker development", "github copilot", "coding standards"]
difficulty_level: "intermediate"
estimated_reading_time: "5 minutes"
---

# 🤝 Contributing to Zer0-Mistakes

Thank you for helping. Bug reports, documentation fixes, components, layouts, accessibility work and translations are all welcome, whether you write the change yourself or with an AI assistant. Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md); report unacceptable behaviour to [support@zer0-mistakes.com](mailto:support@zer0-mistakes.com).

[`AGENTS.md`](AGENTS.md) is the canonical guide to working in this repository — commands, layout, conventions and the invariants not to break — for people and agents alike. This page is the short path through it.

## Where changes go

The theme lives in [bamr87/zer0-CMS](https://github.com/bamr87/zer0-CMS) under `packages/zer0-mistakes/`, and `bamr87/zer0-mistakes` is becoming its read-only mirror. Open issues and pull requests against **bamr87/zer0-CMS**.

## Set up

You need [Docker Desktop](https://www.docker.com/products/docker-desktop) and [Git](https://git-scm.com/); the [GitHub CLI](https://cli.github.com/) is optional. Ruby with Bundler and Node 20 are needed only to run the gem, release and Playwright tooling outside Docker.

```bash
gh repo fork bamr87/zer0-CMS --clone
cd zer0-CMS/packages/zer0-mistakes
bundle install && npm ci
docker-compose up          # live reload at http://localhost:4000
```

`_config.yml` is the production configuration and `_config_dev.yml` the local override that loads the theme from your working tree; Docker serves both. Without Docker, run `bundle exec jekyll serve --config '_config.yml,_config_dev.yml'`. If something will not start, see the [contributor troubleshooting guide](docs/development/troubleshooting.md) or the [user one](https://zer0-mistakes.com/docs/troubleshooting/).

## Make the change

- **Branch off `main`**, one concern per pull request: `feature/`, `fix/`, `docs/`, `refactor/`, `test/` or `chore/` ([change workflow](.github/skills/change-workflow/SKILL.md)).
- **Follow the file-scoped rules** for the area you touch — layouts, includes, Sass, scripts, tests, docs and more each have an instruction file in `.github/instructions/`; the [agent-guidance reference](docs/reference/agent-guidance.md) shows which file covers which path.
- **Write Conventional Commits** (`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, optionally with a scope such as `layouts` or `sass`). release-please reads them to choose the next version, so never bump the version yourself.
- **Record user-visible changes** under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md).
- **Update the docs in the same pull request:** user guides in `pages/_docs/`, contributor docs in `docs/` ([documentation guidelines](.github/instructions/documentation.instructions.md)). Some files are generated — `AGENTS.md` lists them and the command that regenerates each.

## Test it

```bash
./scripts/bin/validate --quick     # preflight: files, versions, YAML, config contract
./scripts/bin/test                 # lib + theme + integration tiers
docker-compose exec -T jekyll bundle exec jekyll build --config '_config.yml,_config_dev.yml'   # any layout, include or Sass change
npm run test:smoke                 # Playwright smoke tier
```

A UI or behavioural change also needs a regression test and before/after screenshots ([visual evidence](.github/skills/visual-evidence/SKILL.md)); check it on a phone, a tablet and a desktop width, with the keyboard alone, and in light and dark mode. Every suite and target is in the [command reference](docs/reference/commands.md); how the suites are organised is in the [testing guide](docs/development/testing.md).

## Open the pull request

Fill in the pull-request template: its checklist is the definition of done. The `zer0-mistakes` workflow at the zer0-CMS root runs the quality checks, the test suites and the gem build on every pull request that touches the theme. A maintainer reviews and merges; releases to [RubyGems](https://rubygems.org/gems/jekyll-theme-zer0) are cut automatically afterwards ([release automation](docs/systems/release-automation.md)).

## Ways to help

- **Theme:** layouts, reusable includes, responsive behaviour, accessibility, performance.
- **Tooling:** the Docker setup, the installer, scripts, tests and CI.
- **Docs:** clearer guides, tutorials, configuration reference, troubleshooting entries.
- **Community:** triage issues, answer questions in Discussions, review pull requests.

Start small if you are new — a documentation fix is a fine first pull request — and discuss a large feature in an issue before you build it.

## Getting help

Ask in [GitHub Discussions](https://github.com/bamr87/zer0-mistakes/discussions), report bugs in [GitHub Issues](https://github.com/bamr87/zer0-CMS/issues), read the documentation at [zer0-mistakes.com](https://zer0-mistakes.com/docs/), or email [support@zer0-mistakes.com](mailto:support@zer0-mistakes.com). Security reports follow [SECURITY.md](SECURITY.md).
