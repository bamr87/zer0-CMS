# tools/svg/library — the SVG example + style library

Reference material for the authoring loop: curated example SVGs with tracked provenance, plus style cards an agent can follow, imitate, or extend. The goal is that "make me an SVG of X" starts from a style decision and working exemplars, not from a blank viewBox.

## Layout

```
library/
  MANIFEST.json      one entry per example: file, title, source, license, tags, lint status
  styles/            style cards — one per named visual style
    refs/            one strict-lint mini exemplar per card, rendered and critiqued before commit
  external/          downloaded examples, one directory per source, files kept pristine
    LICENSES.md      per-source license summary and obligations
```

## How an agent services an SVG request

1. **Decide the style.** Match the brief against `styles/*.md`; each card's Signature section is a set of testable constraints, not vibes. If no card fits, the closest card plus a note is better than freelancing.
2. **Find exemplars.** Search `MANIFEST.json` by tags for examples worth reading — both subject matches ("rocket") and style matches ("mono-line"). Read 1-3 before drawing anything.
3. **Reuse, adapt, or generate.** An external file may be used as-is or modified within its license (see below). For original work, start from the card's Seed recipe.
4. **Close the loop.** Every iteration: `svg-check.py` (deterministic lint) → `svg-render.sh` → *read the PNG* → name the flaw → change one variable. The `svg-art` skill holds the critique vocabulary; the card's Critique add-ons extend it per style.
5. **Full auto:** the `svg-forge` workflow (`.claude/workflows/svg-forge.js`) runs the whole loop multi-agent: style-diverse parallel drafts → `svg-critic` scoring → winner refined one variable per round → strict-lint finalize. Invoke with `args: {brief, out, drafts, rounds, style}`.

## Licensing rules

Every external file carries its license in `MANIFEST.json` and `external/LICENSES.md`. The obligations that matter when reusing or modifying:

- **MIT / ISC** (feather, lucide, bootstrap, heroicons, tabler): free to use and modify; keep the license notice with substantial copies.
- **CC-BY 4.0** (twemoji): free to use and modify, but published work must credit the source.
- **CC-BY-SA 4.0** (openmoji): as CC-BY, plus **derivatives must carry the same license** — do not fold modified OpenMoji art into differently-licensed work.
- **CC0 / Public domain** (wikimedia picks): no restrictions; provenance is recorded anyway.

When a request needs a modified external file, prefer MIT/ISC/CC0 sources; reach for share-alike sources only for as-is use or when the output can honor the license.

## On-demand sourcing and the cache (FreeSVG)

The committed `external/` set is deliberately small; the deep catalog is [FreeSVG.org](https://freesvg.org) — public-domain (CC0) vector art behind a small authenticated API — reached through `tools/svg/freesvg.py`, which exists to make "is there already a good SVG of this?" a cheap first question instead of an API bill.

```
python3 tools/svg/freesvg.py search "rocket"     # cache-first catalog search
python3 tools/svg/freesvg.py fetch 12345         # download into the cache, linted
python3 tools/svg/freesvg.py promote 12345       # graduate a keeper into external/freesvg/ + manifest
python3 tools/svg/freesvg.py status              # cache + auth health
python3 tools/svg/freesvg.py prune --max-mb 50   # trim, oldest first
```

Every layer is cached under `library/cache/freesvg/` (git-ignored, safe to delete): the JWT is reused until expiry, search results live 7 days, item metadata 30 days, and downloaded files are immutable so they never refetch. A fresh cache entry never touches the network; `--refresh` forces one; if the network is down and a stale entry exists, the stale entry is served with a warning. In practice a working session makes API calls only for genuinely new queries.

Credentials go in the environment or the git-ignored `.env` as `FREESVG_EMAIL` / `FREESVG_PASSWORD` (the API is registered-users-only). Without credentials every command degrades to a clear error and the rest of the library keeps working.

Fetched art is CC0, so drafts may adapt it freely: trace, simplify, restyle to a style card, or compose it into a scene. Only `promote`d files enter git and the manifest — the cache is working memory, not the library.

## Adding to the library

1. Download the pristine file into `external/<source>/<source>-<name>.svg` — never reformat it.
2. Vet the license (for Wikimedia: check `LicenseShortName` via the Commons API before keeping anything).
3. Lint it: `python3 tools/svg/svg-check.py <file>` — errors disqualify; warnings get recorded.
4. Append a `MANIFEST.json` entry: `file`, `title`, `source_url`, `license`, `license_url`, `tags` (subject + style), `lint`, `size_kb`.
5. New styles get a card in `styles/` (follow the existing section structure) plus a strict-lint mini exemplar in `styles/refs/`, rendered and critiqued before commit.

First-party pieces (this repo's own samples and style refs) are listed in the manifest too, tagged `first-party`, so tag search covers everything from one place.
