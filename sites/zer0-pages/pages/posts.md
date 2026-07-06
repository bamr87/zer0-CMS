---
layout: index
title: All Posts
description: Browse all articles and blog posts from the Zer0-Mistakes community
keywords:
  primary: [blog posts, articles, tutorials]
  secondary: [jekyll, development, web]
type: page
---

# All Posts

Browse all articles and blog posts from the Zer0-Mistakes community. The list below is generated automatically from the `_posts` collection, newest first, with drafts hidden.

```dataview
TABLE date AS Date, description AS Summary
FROM "_posts"
WHERE type = "post" AND draft != true
SORT date DESC
```
