---
lastmod: 2026-06-16T00:00:00.000Z
title: Include Components
description: Guide to the 70+ reusable include components organized by category for maximum flexibility.
preview: /images/previews/include-components.png
layout: default
categories:
    - docs
    - customization
tags:
    - includes
    - components
    - templates
    - jekyll
permalink: /docs/customization/includes/
difficulty: intermediate
estimated_reading_time: 20 minutes
sidebar:
    nav: docs
type: doc
aliases:
  - /docs/customization/includes/
---

# Include Components

The Zer0-Mistakes theme includes 70+ reusable components organized by category.

## Overview

```text
_includes/
├── analytics/     # Analytics integrations
├── components/    # UI components
├── content/       # Content rendering
├── core/          # Core layout elements
├── docs/          # Documentation specific
├── landing/       # Landing page components
├── navigation/    # Navigation elements
└── stats/         # Statistics dashboard
```

## Using Includes

### Basic Usage

```liquid
{% include navigation/navbar.html %}
```

### With Parameters

```liquid
{% include components/post-card.html post=post %}
```

### Conditional Include

```liquid
{% if page.toc %}
  {% include content/toc.html %}
{% endif %}
```

## Analytics Includes

| Include | Purpose |
|---------|---------|
| `analytics/google-analytics.html` | Google Analytics 4 |
| `analytics/google-tag-manager-head.html` | GTM head script |
| `analytics/google-tag-manager-body.html` | GTM body noscript |
| `analytics/posthog.html` | PostHog analytics |

### Usage

```liquid
{% include analytics/posthog.html %}
```

## Component Includes

| Include | Purpose |
|---------|---------|
| `components/author-card.html` | Author information card |
| `components/cookie-consent.html` | GDPR cookie banner |
| `components/mermaid.html` | Mermaid diagram loader |
| `components/post-card.html` | Blog post card |
| `components/preview-image.html` | Preview image handler |
| `components/search-modal.html` | Search modal |
| `components/searchbar.html` | Deprecated Algolia-style search stub (use `search-modal.html`) |
| `components/theme-info.html` | Theme version modal |

### Post Card Example

```liquid
{% for post in site.posts limit: 3 %}
  {% include components/post-card.html post=post %}
{% endfor %}
```

### Author Card

```liquid
{% include components/author-card.html 
   name=page.author 
   avatar="/assets/images/avatar.png" 
%}
```

## Content Includes

| Include | Purpose |
|---------|---------|
| `content/giscus.html` | GitHub Discussions comments |
| `content/intro.html` | Page introduction |
| `content/seo.html` | SEO meta tags |
| `content/sitemap.html` | Sitemap entry |
| `content/toc.html` | Table of contents |

### TOC Include

```liquid
{% if page.toc != false %}
  {% include content/toc.html %}
{% endif %}
```

### Comments Include

```liquid
{% if page.comments != false and site.giscus.enabled %}
  {% include content/giscus.html %}
{% endif %}
```

## Core Includes

| Include | Purpose |
|---------|---------|
| `core/branding.html` | Site logo and title |
| `core/footer.html` | Page footer |
| `core/head.html` | HTML head section |
| `core/header.html` | Page header/navbar |

### Layout Usage

```html
<!DOCTYPE html>
<html>
  <head>
    {% include core/head.html %}
  </head>
  <body>
    {% include core/header.html %}
    {{ content }}
    {% include core/footer.html %}
  </body>
</html>
```

## Navigation Includes

| Include | Purpose |
|---------|---------|
| `navigation/breadcrumbs.html` | Breadcrumb trail |
| `navigation/nav_list.html` | Navigation list |
| `navigation/nav-tree.html` | Tree navigation |
| `navigation/navbar.html` | Main navbar |
| `navigation/sidebar-config.html` | Resolves the effective sidebar mode/title/icon (page → collection → site) |
| `navigation/sidebar-nav.html` | Renders the resolved sidebar mode |
| `navigation/sidebar-categories.html` | Categories/tags sidebar (posts by taxonomy term) |
| `navigation/sidebar-folders.html` | Collection sidebar (collapsible folder tree) |
| `navigation/sidebar-left.html` | Left sidebar panel |
| `navigation/sidebar-right.html` | Right sidebar (TOC) |

### Sidebar with Navigation

The sidebar mode comes from the `sidebar.nav` front matter key (or a collection/site default), not an include parameter:

```yaml
sidebar:
  nav: docs   # auto | collection | categories | tags | <_data/navigation file>
```

```liquid
{% include navigation/sidebar-left.html %}
```

See [[_docs/features/sidebar-navigation|Sidebar Navigation]] for the full
mode and option reference.

## Landing Page Includes

| Include | Purpose |
|---------|---------|
| `landing/landing-install-cards.html` | Installation options |
| `landing/landing-quick-links.html` | Quick action links |

### Usage

```liquid
{% include landing/landing-install-cards.html %}
```

## Stats Includes

| Include | Purpose |
|---------|---------|
| `stats/stats-categories.html` | Category statistics |
| `stats/stats-header.html` | Stats page header |
| `stats/stats-metrics.html` | Metrics display |
| `stats/stats-no-data.html` | Empty state |
| `stats/stats-overview.html` | Overview cards |
| `stats/stats-tags.html` | Tag cloud |

## Creating Custom Includes

### Basic Include

```html
<!-- _includes/components/custom.html -->
<div class="custom-component">
  <h3>{{ include.title }}</h3>
  <p>{{ include.content }}</p>
</div>
```

### With Parameters

```liquid
{% include components/custom.html 
   title="My Title" 
   content="My content" 
%}
```

### With Default Values

```html
{% assign title = include.title | default: "Default Title" %}
<h3>{{ title }}</h3>
```

### Conditional Content

```html
{% if include.show_icon %}
  <i class="bi bi-{{ include.icon }}"></i>
{% endif %}
```

## Best Practices

### Parameter Documentation

Add comments at the top of includes:

```html
<!--
  Include: post-card.html
  Parameters:
    - post (required): Post object
    - show_excerpt (optional): Show excerpt, default true
    - show_date (optional): Show date, default true
-->
```

### Error Handling

```liquid
{% if include.post %}
  <!-- render post card -->
{% else %}
  <!-- error: post required -->
{% endif %}
```

### Performance

- Avoid nested loops in includes
- Use captures for complex logic
- Cache expensive operations

## Overriding Theme Includes

### Copy and Modify

1. Copy include from theme to your `_includes/`
2. Modify as needed
3. Jekyll uses your version

### Check Theme Location

```bash
bundle show jekyll-theme-zer0
# Copy includes from gem location
```

## Troubleshooting

### Include Not Found

1. Check file path is correct
2. Verify file exists
3. Check for typos in filename

### Parameter Not Working

1. Verify parameter name matches
2. Check for required parameters
3. Debug with `{{ include | inspect }}`

### Infinite Loop

1. Check for circular includes
2. Add guards for recursion
3. Use depth limiting

## Related

- [[_docs/customization/layouts]]
- [[_docs/liquid/index|Jekyll Liquid]]
- [[_docs/bootstrap/index|Bootstrap Integration]]

## Technical Reference

For contributor-level details (component API reference, include parameters, extending the component library):

- [Components → docs/ui/components.md](https://github.com/bamr87/zer0-mistakes/blob/main/docs/ui/components.md)

## See also

- [[_docs/customization/index|Customization]]
- [[_docs/customization/layouts|Layouts]]
- [[_docs/bootstrap/index|Bootstrap Integration]]
