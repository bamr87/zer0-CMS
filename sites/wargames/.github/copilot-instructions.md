# Wargames — GitHub Copilot Instructions

## Project overview

- **Site title**: Wargames
- **Author**: bamr87
- **Theme**: zer0-mistakes (remote)
- **GitHub**: https://github.com/bamr87/zer0-mistakes

## Key commands

```bash
docker compose up                          # Start dev server
bundle exec jekyll build                   # Build site
bundle exec jekyll doctor                  # Check for issues
```

## Conventions

- Posts go in `pages/_posts/` with layout `article`
- Docs go in `pages/_docs/`
- Theme layouts in `_layouts/`, includes in `_includes/`
- Custom styles in `_sass/` (Bootstrap 5 base)
- Navigation configured in `_data/navigation/main.yml`

## Content front matter

```yaml
---
title: "Post Title"
layout: article
categories: [Category]
tags: [tag1, tag2]
date: YYYY-MM-DD
---
```
