# The illustration loop (`provider: claude`)

Since 0.10 the `claude` provider no longer authors a banner in one blind call. It plans, draws, shapes, **looks at the result at full and thumbnail size**, and edits until a critic is satisfied — then commits the best draft it saw, or the deterministic `local` art when nothing it drew could be made strict-clean.

```text
article.md
   │
   ▼
[1] PLAN      Claude → JSON scene graph (palette tokens, focal point, 3-4 layers)
   │
   ▼
[2] AUTHOR    Claude → SVG from plan + style card (headline as <text>, pre-broken)
   │
   ▼
[3] SHAPE     sanitize · <text>→<path> · round precision · strict lint   (no model)
   │   └─ lint fails ──▶ one targeted fix round, then the `local` banner
   ▼
[4] LOOK      rasterize at 1536px and 120px                               (no model)
   │
   ▼
[5] CRITIQUE  Claude vision → {works, fails[], next_change, overall, thumbnail_holds}
   │   └─ overall < claude_min_score, or the thumbnail fails ──▶ [2'] EDIT the
   │      current SVG with the critique (up to claude_rounds), back to [3]
   ▼
[6] COMMIT    best-of by score · front matter · one telemetry record
```

Steps 3, 4 and 6 are deterministic. At the defaults one banner costs three calls (plan, author, critique) plus at most one edit and its re-critique.

## Settings

All of these live in the `preview_images:` block of `_config.yml`, with an environment variable and a CLI flag each (CLI > env > config > default, like every other key).

| Key | Default | Flag | Meaning |
| --- | --- | --- | --- |
| `style_card` | `""` | `--style-card` | A card from `tools/svg/library/styles/` by name (`retro-pixel`, `flat-geometric`, …) or a path. Its Signature / Geometry / Palette / Do-Don't sections constrain the author; its Critique add-ons extend the critic. `""` keeps the prose `style` string only. |
| `palette` | `[]` | `--palette` | Six hex tokens `[bg, shadow, low-mid, mid, accent, highlight]`, a comma-separated string of them, or a `BANNER_PALETTES` name. Fixed tokens override whatever the plan proposes. |
| `claude_plan` | `true` | `--[no-]claude-plan` | Plan a scene graph first. With it on, the runner skips the raster-style art brief it sends other providers (the plan replaces it). |
| `claude_rounds` | `1` | `--rounds` | Critique-driven edit rounds. **`0` is the rollback**: one authored draft, shaped and linted, never rendered or reviewed. |
| `claude_min_score` | `7` | `--min-score` | Critic `overall` (0–10) that ends the loop. |
| `claude_require_thumbnail` | `true` | `--[no-]require-thumbnail` | The banner must also read at 120px to end the loop. |
| `svg_text` | `paths` | `--svg-text` | `paths` converts every `<text>` to outlines with a bundled font; `keep` leaves it; `forbid` strips it. |
| `svg_max_kb` | `300` | `--svg-max-kb` | Strict-lint size budget. Converted glyphs add 20–60 KB to a titled banner; the author is asked to stay under the budget minus that headroom. |
| `look_rasterizer` | `auto` | `--look-rasterizer` | What the loop LOOKS through — independent of `rasterizer`, which decides the committed OUTPUT, so an SVG-only site (`rasterizer: none`) still gets reviewed. `none` disables the critique. |
| `claude_budget_usd` | `0` | `--budget-usd` | Run-wide spend cap at list prices (shared across workers). Past it the loop skips plan → critique → edit, and finally authors nothing and ships the `local` banner. `0` = uncapped. |

Run-only flags: `--telemetry PATH` (one JSON record per banner, `-` for stdout), `--changed` + `--exclude-re REGEX` (illustrate git-new/modified markdown; a NEW article stamped with its section's shared placeholder is re-illustrated), `--inspect SVG [--critic] [-f ARTICLE]` (lint, optionally render + critique an existing banner; one JSON object on stdout), and `--shape SVG [--style-card NAME]` (run step 3 on a file in place; exits 1 unless strict-clean).

## The headline: authored as `<text>`, shipped as paths

The title is the most useful thing on a banner, and Claude lays it out far better with `<text>` than by hand-drawing glyph outlines — but a committed `<text>` renders in whatever font the viewer happens to have. So the loop does both. Before authoring, `fit_headline` breaks the title at word boundaries with the bundled font's real metrics (never mid-word — `CHAN-/DRAYA/AN-1` is exactly the defect it exists to prevent), caps the block at 30% of the frame height, and hands the author the lines, size, anchor and baselines. After authoring, `svg_text_to_paths` outlines every `<text>`/`<tspan>` with the same font, resolving `font-family`/`font-size`/`font-weight`/`text-anchor`/`letter-spacing`/`dominant-baseline` through inline style, simple CSS rules, attributes and inheritance; an overlong line is scaled to fit the frame. The `<g>` that replaces each `<text>` carries an `aria-label` with the original words.

Fonts ship in `lib/zer0_image_generator/fonts/` (Press Start 2P for the `retro-pixel` card, Inter Regular/Bold otherwise, all OFL — see its README). The reader is stdlib-only and pinned byte-for-byte by the Ruby twin `svg/text_to_paths.rb`. A standalone single-file install has no fonts and degrades to stripping text, with a note in telemetry.

## Degrade, never block — never ship broken

| Failure | What ships | `fallback` in telemetry |
| --- | --- | --- |
| plan reply unusable | the loop continues without a plan | — (`plan: false`) |
| author call fails | the `local` banner | `author_failed` |
| still not strict-clean after the fix round | the `local` banner | `lint` |
| an edit breaks lint | the best earlier draft | — |
| no rasterizer / critique fails | the current draft, unreviewed | — (`critic: null`) |
| budget spent before authoring | the `local` banner | `budget` |

A committed banner therefore never carries a dangling `url(#…)`, a raster payload or a `<text>` element.

## Telemetry (`banner/v1`)

One JSON object per committed banner. Additive changes only; renames bump the schema marker.

```json
{"schema": "banner/v1", "ts": "2026-10-20T04:07:58Z", "slug": "...", "article": "_posts/...md",
 "banner": "assets/images/previews/....svg", "kind": "svg", "kb": 41.2,
 "provider": "claude", "model": "claude-sonnet-5-5", "style_card": "retro-pixel",
 "plan": true, "calls": 5, "rounds_used": 1, "fix_round": false, "fallback": null,
 "rasterizer": "resvg", "lint": {"clean": true, "errors": [], "warnings": []},
 "text": {"mode": "paths", "converted": 2, "stripped": 0, "fitted": 0, "missing_glyphs": 0},
 "critic": {"overall": 7.5, "thumbnail_holds": true, "fails": [], "next_change": "..."},
 "tokens": {"input": 18234, "output": 9120}, "cost_usd": 0.127716}
```

`tokens`/`cost_usd` are `null` when the run rode the `claude` CLI (it reports no usage). Costs are list-price shadow prices: under a Claude Code OAuth token nothing is invoiced per token, but the numbers still rank and cap the work.

## One code path for dev and prod

The structured critique is the same shape the interactive forge uses (`.claude/workflows/svg-forge.js` `CRITIQUE_SCHEMA`; `svg/critique.schema.json`), and the forge's Finalize phase runs the production SHAPE step through `--shape`. `tools/svg/svg-check.py` is a thin CLI over the engine's `lint_svg()`. A test pins the schemas, the forge's required keys and the CLI's output to the engine, so the dev loop and the grow tick cannot drift apart again.

## Rasterizers

The loop's LOOK step and `rasterizer:` both walk `rsvg → resvg → inkscape → magick → playwright`. `resvg` (native binary, or `resvg-js` from `npm i -g @resvg/resvg-js-cli`) is the closest headless match to browser rendering; cairo-based tools mis-render `feTurbulence`. `auto` never reaches for the network — only an explicit `resvg` preference may fall through to `npx -y @resvg/resvg-js-cli`.
