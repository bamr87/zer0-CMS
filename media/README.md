# `media/` — the design system

Four stylesheets and the extension's icons. The build copies every `*.css` here into `dist/media/` (see the `copy-media` plugin in `esbuild.js`), which is one of the two directories a webview may load from; the other is `dist/`.

| File | Loaded by | What it owns |
|---|---|---|
| `tokens.css` | all three webviews | The `--z-*` token layer. **The only file in the repository allowed to name a VS Code theme variable.** |
| `base.css` | all three webviews | Reset, 13px root, the global control look, and the shared widget kernel that `src/webview/shared/components.ts` builds. |
| `panel.css` | `zer0Cms.panel` | Panel layout, collapsible sections, the eighteen field controls, tag pills, drop zones, the three-state validation border, the char-limit counter, the SEO tables, the governance block. |
| `dashboard.css` | `zer0Cms.dashboard`, the agent panel | Shell, tab bar, toolbars, content cards (grid *and* list), tables, modals, slide-overs, the folder tree, the four distribution lanes, pagination. |

Load order is `tokens.css` → `base.css` → the surface stylesheet. All three are linked with the page nonce; nothing is inlined and nothing is fetched.

## The one rule

**Only `tokens.css` may name a VS Code theme custom property.** Every other selector, in CSS *and* in TypeScript, goes through a `--z-*` token. CI greps for violations.

That indirection is what makes a vanilla rewrite maintainable where the Tailwind original was not: the fork it replaces had roughly four hundred inline `bg-[var(…theme colour…)]` arbitrary values, so retheming one control meant finding every site that had hard-coded the same theme key. Here it is one line.

## Derived tokens

Six values cannot be expressed as an alias — an alpha wash, a darkened border, a theme-flipped translucent surface:

| Token | Derivation |
|---|---|
| `--z-ok-bg` | `--z-ok` at 5 % alpha |
| `--z-warn-bg` | `--z-warn` at 5 % alpha |
| `--z-border-active` | `--z-border` darkened 30 % (lightened in dark themes) |
| `--z-overlay` | `--z-bg` at 75 % alpha |
| `--z-translucent` | `rgba(255,255,255,.1)` dark / `rgba(0,0,0,.1)` light |
| `--z-btn-solid` | `--z-btn-bg` with any alpha stripped |

`updateDerivedTokens()` in `src/webview/shared/dom.ts` recomputes them on load and on every `document.body` attribute mutation, reading the already-resolved `--z-*` sources rather than the theme variables. The values in `tokens.css` are the pre-script fallbacks so a first paint is never broken.

## Themes

All three stylesheets must read correctly in light, dark and high-contrast. Two mechanisms carry that:

- `--z-border` and `--z-border-group` resolve through
VS Code's `contrastBorder` colour with a fallback. That colour only exists in HC themes, so hairlines appear there automatically with no extra selector.
- Filled surfaces (`.z-card`, `.z-tag`, `.z-status`, zebra table rows, the
translucent group boxes) get explicit `body.vscode-high-contrast` / `body.vscode-high-contrast-light` overrides at the bottom of each file, because HC themes deliberately flatten backgrounds and a hover state expressed only as a background colour becomes invisible.

## Metrics

Front Matter's, on purpose — reproducing the interaction design was the point of the rewrite. `html { font-size: 13px }` in `base.css` is load-bearing: every `rem` figure was measured against that root, so changing it rescales the UI rather than the type.

Panel: `1rem 1.25rem` section padding, 22px file rows with negative side margins so hover bleeds to the edge, `.25rem` control radii, `2px` pills, `3px` badges, 26px line-height secondary link-buttons, 1px dashed drop zones at `brightness(85%)` → 100 % on hover.

Dashboard: 16px horizontal gutter (20px on list rows), 24px content top padding, 16px card grid gap at 1/2/3/4/5 columns from 0/640/768/1024/1536, 144px card images, 448px slide-over, 512px modal (672px wide variant), 500ms slide transition, `PAGE_LIMIT = 16` pagination.

## Icons

Codicons only, rendered as `<i class="codicon codicon-{name}">` by `icon()` in `dom.ts`. The extension draws **no SVG icons of its own**; `codicon.css` and `codicon.ttf` are copied out of the `@vscode/codicons` devDependency into `dist/media/` by the `copy-media` plugin in `esbuild.js`, and a missing file there is a build error rather than a warning. A webview does not get codicons for free — without them every `icon()` call site renders an empty element and every icon-only control becomes an invisible box, which is a failure that looks exactly like a working build. All three shells link `dist/media/codicon.css` **before** `tokens.css`, and the three sizing rules in `base.css` are written as `.codicon[class*='codicon-']` so they outrank `codicon.css`'s own `font` shorthand.

## Adding a rule

1. If it needs a colour, check `tokens.css` for a token first. Add one there if
   there is none — never reach for a theme variable at the call site.
2. Put shared widget chrome in `base.css`, surface layout in `panel.css` or
   `dashboard.css`.
3. Check it in a dark, a light and a high-contrast theme before calling it done.
