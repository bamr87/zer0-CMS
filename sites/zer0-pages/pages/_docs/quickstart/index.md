---
lastmod: 2026-06-23T00:00:00.000Z
title: Zer0-Mistakes Quickstart Guides
description: Pick the fastest path to a live Zer0-Mistakes site — a three-file remote-theme starter, the fork-and-deploy GitHub Pages workflow, or a step-by-step series.
preview: /images/docs/quickstart/theme-home.png
layout: default
categories:
  - docs
  - quickstart
tags:
  - quickstart
  - getting-started
  - github-pages
  - remote-theme
keywords:
  - quickstart
  - jekyll
  - github-pages
  - remote-theme
  - theme
author: bamr87
permalink: /docs/quickstart/
difficulty: beginner
estimated_reading_time: 5 minutes
sidebar:
  nav: docs
type: doc
aliases:
  - /docs/quickstart/
---

# Quickstart Guides

This hub points you at the fastest route from zero to a published
Zer0-Mistakes site. Every guide below is self-contained — start with the one
that matches how much you want to own.

![The Zer0-Mistakes theme home page rendered locally, showing the navbar and hero section](/assets/images/docs/quickstart/theme-home.png)

## Choose your path

| Guide | Best for | Time |
| --- | --- | --- |
| [[_docs/quickstart/bare-minimum|Bare-Minimum Remote-Theme Starter]] | Trying the theme with the fewest files (`_config.yml`, `Gemfile`, `index.md`) | ~5 min |
| [[_docs/quickstart/fork-and-deploy|Fork & Deploy to GitHub Pages]] | A real site you own and customize, deployed on GitHub Pages | ~15 min |

## What you need first

All paths assume you have:

- A [GitHub](https://github.com/) account.
- [Git](https://git-scm.com/) installed locally (or you can work entirely in the GitHub web UI for the remote-theme path).
- Optionally [Docker](https://www.docker.com/) for the recommended local development loop.

If you have never built a Jekyll site before, the
[[_docs/getting-started/index|Getting Started overview]] covers installing those
tools first.

## Two ways to consume the theme

There are two supported models, and the guides above cover both:

1. **Remote theme** — your repository keeps only your content and
   configuration, and pulls layouts/includes/styles from
   `bamr87/zer0-mistakes` at build time. Lowest maintenance; start with the
   [[_docs/quickstart/bare-minimum|Bare-Minimum Starter]].
2. **Fork** — you copy the whole theme into your repository so you can edit
   layouts and styles directly. Most control; follow
   [[_docs/quickstart/fork-and-deploy|Fork & Deploy]].

## Next steps

- New to the theme's structure? Read the
  [[_docs/getting-started/index|Getting Started overview]].
- Ready to publish? Every path ends at the
  [[_docs/deployment/github-pages|Deploy to GitHub Pages]] reference.
- Want to customize the look? See the
  [[_docs/getting-started/theme-guide|Theme Guide]].
