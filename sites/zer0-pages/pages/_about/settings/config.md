---
title: Configuration Utility
preview: /images/previews/configuration-utility.png
layout: admin
icon: bi-gear
excerpt: View, manage, and update your Jekyll theme configuration from one place.
lastmod: 2026-04-04T00:00:00.000Z
config-dir: pages/_about/settings
config-file: _config.yml
permalink: /about/config/
sidebar: false
type: about
aliases:
  - /about/config/
---

View, manage, and update your Jekyll theme configuration from one place.

> [!note] Live-site component
> The interactive Configuration Utility — the config viewer, the config editor, the raw-YAML export, the quick-reference cards (Site URL, Repository, Theme Skin, Collections), and the environment table — renders on the published Jekyll site. It reads the live `_config.yml` and site variables, which are not available in the Obsidian vault. Secrets (API keys, tokens, passwords) are redacted before display.

## Regenerate the config snapshot

Copy the live `_config.yml` into this settings directory for documentation purposes.

### Bash

```bash
cd ~/github/zer0-mistakes
# Wraps the copy in Liquid raw markers so config comments that mention
# Liquid tags render literally (scripts/bin/validate checks for drift).
# The awk string-splits keep this page itself Liquid-safe.
awk 'BEGIN{print "{" "% raw %" "}"} {print} END{print "{" "% endraw %" "}"}' \
  _config.yml > pages/_about/settings/_config.yml
```

### PowerShell

```powershell
cd ~/github/zer0-mistakes
$raw = "{" + "% raw %" + "}"; $end = "{" + "% endraw %" + "}"
$body = Get-Content _config.yml -Raw
Set-Content -Encoding UTF8 pages/_about/settings/_config.yml `
  -Value ($raw + "`n" + $body + $end + "`n")
```

## Shortcuts

- [View on GitHub](https://github.com/bamr87/zer0-mistakes/blob/main/_config.yml) — Open `_config.yml` in the repo
- [Edit on GitHub](https://github.com/bamr87/zer0-mistakes/edit/main/_config.yml) — Open the in-browser editor
- [Jekyll Docs](https://jekyllrb.com/docs/configuration/) — Official configuration reference
- [YAML Spec](https://yaml.org/spec/1.2.2/) — YAML 1.2.2 specification
