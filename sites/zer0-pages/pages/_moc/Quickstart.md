---
title: "Quickstart Map"
type: page
---

# Quickstart Map

The fastest path from zero to a running **zer0-mistakes** Jekyll site. Follow the steps in order — each one builds on the last — or jump straight to whatever you need.

## The Getting-Started Path

1. [[_quickstart/index|Quick Start Guide]] — the overview and install entry point. Pick the path that fits your goal and get running in under five minutes.
2. [[_quickstart/machine-setup|Machine Setup]] — install Docker, Git, and the essential tools on macOS, Windows, or Linux.
3. [[_quickstart/jekyll-setup|Jekyll Setup]] — start the Docker-first dev server, create content, and customize your theme.
4. [[_quickstart/github-setup|GitHub Setup & Deployment]] — fork the theme, configure SSH keys, and deploy to GitHub Pages.
5. [[_quickstart/personalization|Site Personalization & Configuration]] — dial in site identity, branding, analytics, and generate your `_config.yml`.

## All Quickstart Pages

```dataview
TABLE description AS Summary, quickstart.step AS Step
FROM "_quickstart"
WHERE type = "quickstart"
SORT quickstart.step ASC
```
