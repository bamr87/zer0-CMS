---
schema: "0.1"
coverage: listed
---

# SCHEMA — _docs

> Docs collection — topic-organized documentation for the site and the zer0-mistakes theme, published under /docs/.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `analytics/` | dir | Web analytics integration docs (Google Analytics, Tag Manager) | |
| `bootstrap/` | dir | Bootstrap 5 integration docs | |
| `customization/` | dir | Theme customization docs — layouts, includes, navigation, styles, author profiles | |
| `deployment/` | dir | Deployment guides — GitHub Pages, Netlify, custom domain, remote-theme checklist | |
| `development/` | dir | Development-process docs — CI/CD, testing, releases, security, agents, scripts | |
| `docker/` | dir | Docker-based local development docs | |
| `features/` | dir | One page per theme feature (search, TOC, comments, dashboards, diagrams, ...) | |
| `getting-started/` | dir | Orientation guides — quick start and theme guide | |
| `jekyll/` | dir | Jekyll fundamentals — collections, pagination, code highlighting | |
| `liquid/` | dir | Liquid templating docs | |
| `obsidian/` | dir | Obsidian vault integration docs — authoring workflow, graph, syntax, performance | |
| `quickstart/` | dir | Fastest-path setup guides — bare minimum starter and fork-and-deploy | |
| `ruby/` | dir | Ruby language docs | |
| `seo/` | dir | SEO docs — meta tags, sitemap, AIEO | |
| `index.md` | file | /docs/ landing page | |
| `*.md` | pattern | Standalone top-level doc pages (installation, front-matter, ruby-101, troubleshooting) | |

## Placement

- New doc page → the matching topic directory as a kebab-case `.md` file.
- New topic → a directory with `index.md` + `SCHEMA.md`, plus a section in `_data/navigation/docs.yml`.
