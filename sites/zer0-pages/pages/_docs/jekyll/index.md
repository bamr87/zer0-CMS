---
lastmod: 2026-06-14T00:00:00.000Z
title: Jekyll
description: Jekyll basics and Zer0-Mistakes development workflow (Docker-first).
preview: /images/previews/jekyll.png
layout: default
categories:
    - docs
    - jekyll
tags:
    - jekyll
    - getting-started
    - docker
permalink: /docs/jekyll/
difficulty: beginner
estimated_reading_time: 10 minutes
prerequisites:
    - Docker Desktop (recommended) or Ruby + Bundler
sidebar:
    nav: docs
draft: false
type: doc
aliases:
  - /docs/jekyll/
---

# Jekyll

Jekyll is the static site generator that powers Zer0-Mistakes. This section covers everything you need to work with Jekyll effectively.

## Quick Start

### Prerequisites

- Complete the [[_docs/installation|Installation Guide]]
- Have Docker Desktop running (or Ruby + Bundler installed)

### Run Locally

```bash
# With Docker (recommended)
docker-compose up

# Without Docker
bundle exec jekyll serve --config "_config.yml,_config_dev.yml"
```

Your site will be available at [http://localhost:4000](http://localhost:4000).

## Key Concepts

### Directory Structure

| Directory | Purpose |
|-----------|---------|
| `_layouts/` | Page templates (HTML with Liquid) |
| `_includes/` | Reusable components |
| `_data/` | Site data files (YAML, JSON) |
| `_sass/` | Stylesheet partials |
| `pages/` | Content collections |
| `assets/` | Static files (CSS, JS, images) |

### Configuration Files

| File | Purpose |
|------|---------|
| `_config.yml` | Production configuration |
| `_config_dev.yml` | Development overrides |
| `Gemfile` | Ruby dependencies |

### Content Collections

Zer0-Mistakes organizes content in collections under `pages/`:

- `_posts/` - Blog posts
- `_docs/` - Documentation
- `_quests/` - Tutorials and learning paths
- `_about/` - About pages

## Essential Commands

```bash
# Build the site
docker-compose exec jekyll jekyll build

# Build with verbose output
docker-compose exec jekyll jekyll build --verbose

# Check for configuration issues
docker-compose exec jekyll jekyll doctor

# Clean build artifacts
docker-compose exec jekyll jekyll clean
```

## Documentation Topics

### Configuration & Setup

- [[_docs/jekyll/index|Jekyll Configuration]] — Site settings and options
- [[_docs/front-matter|Front Matter]] — Page metadata and options
- [[_docs/jekyll/code-highlighting|Code Highlighting]] — Syntax highlighting
- [[_docs/jekyll/pagination]] — Post navigation

### Features

See the [[_docs/features/index|Features]] section for:

- [[_docs/features/mermaid-diagrams|Mermaid Diagrams]] — Flowcharts and diagrams
- [[_docs/features/mathjax-math|MathJax Math]] — Mathematical notation
- [[_docs/features/giscus-comments|Giscus Comments]] — GitHub Discussions comments
- [[_docs/features/posthog-analytics|PostHog Analytics]] — Privacy-first analytics

### Deployment

See the [[_docs/deployment/index|Deployment]] section for:

- [[_docs/deployment/github-pages|GitHub Pages]] — Free hosting with GitHub
- [[_docs/deployment/netlify]] — Advanced hosting features
- [[_docs/deployment/custom-domain|Custom Domain]] — Use your own domain

## Resources

- [Official Jekyll Documentation](https://jekyllrb.com/docs/)
- [Jekyll GitHub Repository](https://github.com/jekyll/jekyll)
- [Liquid Template Language](https://shopify.github.io/liquid/)

## Related

- [[_docs/ruby/index|Ruby & Bundler]] — Ruby dependency management
- [[_docs/liquid/index|Liquid Templating]] — Template language reference
- [[_docs/docker/index|Docker Development]] — Container-based workflow

## See also

- [[_docs/liquid/index|Liquid]]
- [[_docs/ruby/index|Ruby]]
- [[_docs/docker/index|Docker]]
- [[_docs/customization/index|Customization]]
- [[front-matter]]
