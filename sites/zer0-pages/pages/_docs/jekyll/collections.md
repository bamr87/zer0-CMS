---
lastmod: 2026-06-14T00:00:00.000Z
title: Jekyll Collections
description: Organized content collections for posts, docs, and notes with custom permalinks.
preview: /images/previews/jekyll-collections.png
layout: default
categories:
    - docs
    - jekyll
tags:
    - collections
    - jekyll
    - content
    - organization
permalink: /docs/jekyll/collections/
difficulty: intermediate
estimated_reading_time: 15 minutes
sidebar:
    nav: docs
type: doc
aliases:
  - /docs/jekyll/collections/
---

# Jekyll Collections

The Zer0-Mistakes theme uses Jekyll collections to organize different content types with custom permalinks and layouts.

## Available Collections

| Collection | Location | Permalink | Layout |
|------------|----------|-----------|--------|
| `posts` | `pages/_posts/` | pretty post permalinks (built-in collection) | `article` |
| `docs` | `pages/_docs/` | `/docs/:path/` | `default` |
| `notes` | `pages/_notes/` | `/notes/:path/` | `note` |
| `moc` | `pages/_moc/` | `/moc/:path/` | `default` |

## Configuration

### Collection Definition

```yaml
# _config.yml
collections:
  docs:
    output: true
    permalink: /docs/:path/
  notes:
    output: true
    permalink: /notes/:path/
  moc:
    output: true
    permalink: /moc/:path/
```

`posts` is Jekyll's built-in collection and needs no entry here.

### Collection Defaults

```yaml
# _config.yml
defaults:
  # Posts
  - scope:
      path: ""
      type: posts
    values:
      layout: article

  # Documentation
  - scope:
      path: ""
      type: docs
    values:
      layout: default

  # Notes
  - scope:
      path: ""
      type: notes
    values:
      layout: note
```

## Creating Content

### Posts

Create in `pages/_posts/`:

```yaml
---
title: "My Blog Post"
date: 2025-01-25
categories: [technology, jekyll]
tags: [tutorial, beginner]
preview: /images/previews/jekyll-collections.png
---

Post content here...
```

Filename format: `YYYY-MM-DD-title-slug.md`

### Documentation

Create in `pages/_docs/`:

```yaml
---
title: "Getting Started"
description: "Quick start guide for new users"
permalink: /docs/getting-started/
difficulty: beginner
estimated_reading_time: 10 minutes
---

Documentation content...
```

### Notes

Create in `pages/_notes/`:

```yaml
---
title: "Git Commands Cheatsheet"
description: "Quick reference for everyday git"
type: note
---
```

## Accessing Collections

### In Templates

```liquid
<!-- Loop through all docs -->
{% for doc in site.docs %}
  <a href="{{ doc.url }}">{{ doc.title }}</a>
{% endfor %}

<!-- Filter by category -->
{% assign tutorials = site.docs | where: "category", "tutorials" %}

<!-- Sort by date -->
{% assign recent = site.posts | sort: "date" | reverse %}
```

### Collection Properties

```liquid
{{ site.docs.size }}         <!-- Number of docs -->
{{ site.docs.first.title }}  <!-- First doc title -->
{{ site.posts.last.date }}   <!-- Last post date -->
```

## Custom Collections

### Creating New Collection

1. **Add to config**:

```yaml
collections:
  tutorials:
    output: true
    permalink: /tutorials/:title/
```

1. **Set defaults**:

```yaml
defaults:
  - scope:
      path: "pages/_tutorials"
      type: tutorials
    values:
      layout: tutorial
```

1. **Create directory**:

```bash
mkdir pages/_tutorials
```

1. **Add content**:

```yaml
---
title: "My Tutorial"
difficulty: beginner
---
```

## Organization Strategies

### By Category

```text
pages/_docs/
├── getting-started/
│   ├── index.md
│   └── quick-start.md
├── features/
│   ├── index.md
│   └── feature-name.md
└── customization/
    ├── index.md
    └── styles.md
```

### By Date

```text
pages/_posts/
├── 2025-01-25-first-post.md
├── 2025-01-24-second-post.md
└── 2025-01-23-third-post.md
```

### By Topic

```text
pages/_notes/
├── git-commands.md
├── docker-commands.md
└── jekyll-front-matter.md
```

## Permalinks

### Permalink Variables

| Variable | Description |
|----------|-------------|
| `:collection` | Collection name |
| `:path` | Path from collection root |
| `:name` | Filename without extension |
| `:title` | Slugified title |
| `:basename` | Filename without date |
| `:year` | 4-digit year |
| `:month` | 2-digit month |
| `:day` | 2-digit day |

### Custom Permalinks

```yaml
# In front matter
---
permalink: /my-custom-url/
---
```

### Pretty URLs

```yaml
# _config.yml
permalink: pretty  # Adds trailing slash
```

## Collection Pages

### Index Pages

Create collection index pages:

```yaml
# pages/_docs/index.md
---
title: Documentation
layout: collection
collection: docs
---

Welcome to the documentation...
```

### Collection Layout

```html
<!-- _layouts/collection.html -->
---
layout: default
---

<h1>{{ page.title }}</h1>

{% assign items = site[page.collection] | sort: "title" %}
{% for item in items %}
  <article>
    <h2><a href="{{ item.url }}">{{ item.title }}</a></h2>
    <p>{{ item.description }}</p>
  </article>
{% endfor %}
```

## Best Practices

### Naming Conventions

- Use lowercase for directories
- Use hyphens in filenames
- Keep URLs short and descriptive

### Front Matter

- Always include `title`
- Add `description` for SEO
- Use consistent date format

### Organization

- Group related content
- Use index pages for sections
- Keep hierarchy shallow

## Troubleshooting

### Collection Not Appearing

1. Verify `output: true` in config
2. Check directory path matches config
3. Ensure files have front matter

### Wrong Permalink

1. Check permalink pattern in config
2. Verify front matter permalink
3. Clear Jekyll cache

### Missing Defaults

1. Verify scope path is correct
2. Check type matches collection name
3. Restart Jekyll server

## Related

- [[_docs/jekyll/index|Jekyll Configuration]]
- [[_docs/customization/layouts]]
- [[_docs/front-matter|Front Matter]]

## See also

- [[_docs/jekyll/index|Jekyll]]
- [[front-matter]]
- [[_docs/liquid/index|Liquid]]
