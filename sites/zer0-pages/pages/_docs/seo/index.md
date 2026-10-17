---
lastmod: 2026-06-14T06:00:00.000Z
title: "Jekyll SEO Features: Meta Tags, Sitemaps & Schema"
description: "Configure the Zer0-Mistakes theme's built-in SEO — Open Graph and Twitter meta tags, JSON-LD structured data, XML sitemaps, and a search index."
preview: /images/previews/seo.png
layout: default
categories:
    - docs
    - seo
tags:
    - seo
    - meta
    - sitemap
    - search
keywords:
    - jekyll seo
    - meta tags
    - open graph
    - structured data
    - xml sitemap
permalink: /docs/seo/
difficulty: beginner
estimated_reading_time: 5 minutes
sidebar:
    nav: docs
type: doc
aliases:
  - /docs/seo/
---

# SEO Features

The Zer0-Mistakes theme ships Open Graph and Twitter Card meta tags, JSON-LD structured data, an XML sitemap, and a search index — all enabled automatically with no plugin required.

## Features

| Feature | Purpose |
|---------|---------|
| [[_docs/seo/meta-tags|Meta Tags]] | Open Graph, Twitter Cards, canonical URLs |
| [[_docs/seo/sitemap]] | XML sitemap and JSON search index |
| [[_docs/features/breadcrumbs]] | Structured navigation markup |

## Quick Setup

Most SEO features work automatically. Configure site-wide defaults:

```yaml
# _config.yml
title: "Your Site Title"
description: "Your site description for search engines"
preview: /images/previews/seo.png
url: "https://yoursite.com"
author:
  name: "Your Name"
  twitter: "@yourusername"
og_image: "/assets/images/og-default.png"
```

## Per-Page SEO

Override in front matter:

```yaml
---
title: "Page Title"
description: "Page-specific description"
preview: /images/previews/seo.png
image: "/assets/images/page-image.png"
author: "Specific Author"
---
```

## Validation Tools

- [Google Rich Results Test](https://search.google.com/test/rich-results)
- [Facebook Sharing Debugger](https://developers.facebook.com/tools/debug/)
- [Twitter Card Validator](https://cards-dev.twitter.com/validator)

## Related

- [[_docs/seo/meta-tags|Meta Tags]]
- [[_docs/seo/sitemap]]
- [[_docs/features/breadcrumbs]]

## See also

- [[_docs/analytics/index|Analytics]]
- [[front-matter]]
- [[_docs/features/index|Features]]
- [[_docs/deployment/index|Deployment]]
