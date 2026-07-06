---
type: meta
title: "Log"
updated: 2026-07-05
---

# Log

Append-only. Newest entries on top.

## 2026-07-05 — Vault conversion
- Converted `pages/` (zer0-mistakes Jekyll content) into an Obsidian vault with claude-obsidian.
- Backed up pristine Jekyll tree to `../.backups/pages-jekyll-20260705-200505/` (197 files).
- Rewrote 302 permalink links → wikilinks across 173 notes (fence-aware; assets/external links left intact).
- Rewrote 241 pre-existing bare concept links (`[[Jekyll]]`…) → path-qualified via a title map.
- Augmented frontmatter on 173 notes with `type` + `aliases`.
- Re-authored 18 dynamic Liquid listing pages as Dataview pages; converted 3 `.html` → `.md`.
- Cleaned unfenced Liquid from 24 pages (`{% raw %}`, `{% include %}` widgets, `{{ site.* }}`).
- Built 7 MOCs (`_moc/Home` + one per collection).
- Scaffolded `.obsidian/`, `.raw/`, `wiki/`, `_moc/`, `_templates/`.
- Final lint: 662 wikilinks, 4 intentional unresolved (template placeholders + 2 future-page stubs), 0 stray Liquid, 0 `.html`.
