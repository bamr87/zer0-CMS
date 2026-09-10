# `media/` — the design system

Four stylesheets and the extension's icons. The build copies every `*.css` here into `dist/media/` (see the `copy-media` plugin in `esbuild.js`), which is one of the two directories a webview may load from; the other is `dist/`.

| File | Loaded by | What it owns |
|---|---|---|
| `tokens.css` | all three webviews | The `--z-*` token layer. **The only file in the repository allowed to name a VS Code theme variable.** |
| `base.css` | all three webviews | Reset, 13px root, the global control look, the shared widget kernel that `src/webview/shared/components.ts` builds — status pills, tables, empty states, gated buttons, key/value lists, staged forms and the agent transcript — and the layout utilities that replaced the CSP-dead inline styles. |
| `panel.css` | `zer0Cms.panel` | Panel layout, collapsible sections, the eighteen field controls, tag pills, drop zones, the three-state validation border, the char-limit counter, the SEO tables, the governance block. |
| `dashboard.css` | `zer0Cms.dashboard` | Shell, tab bar, toolbars, content cards (grid *and* list), modals, slide-overs, the folder tree, the four distribution lanes, pagination, and the Fleet route's own columns. |

Load order is `tokens.css` → `base.css` → the surface stylesheet. All three are linked with the page nonce; nothing is inlined and nothing is fetched.

## The one rule

**Only `tokens.css` may name a VS Code theme custom property.** Every other selector, in CSS *and* in TypeScript, goes through a `--z-*` token.

That indirection is what makes a vanilla rewrite maintainable where the Tailwind original was not: the fork it replaces had roughly four hundred inline `bg-[var(…theme colour…)]` arbitrary values, so retheming one control meant finding every site that had hard-coded the same theme key. Here it is one line.

**`src/test/styling.test.ts` is the grep.** This file has claimed CI ran one since it was written; until that suite existed, nothing did. It walks `media/*.css` and every shipped `src/**/*.ts`, and fails on a `--vscode-` outside `tokens.css` — plus the positive half, so a token layer that stopped resolving theme variables fails too.

## The other rule: no inline styles

`el()` has **no `style` prop**, and `src/test/styling.test.ts` fails the build if one comes back. Every shell serves `default-src 'none'` with `style-src <cspSource> 'nonce-…'`, and a nonce cannot apply to an attribute — so an inline `style` is dropped by the browser with no console error and no visible failure. Eleven call sites in `src/webview/panel/**` carried one and had all been silently doing nothing since the day they were written.

They are classes now, in `base.css`: `.z-hidden`, `.z-center`, `.z-dim`, `.z-anchor`, `.z-row` (`--tight` / `--wide`), `.z-inset`, `.z-label__text`, `.z-label__suffix`. If you need a value CSS cannot know, put a class on the node and a rule here; if you need a *colour*, add a token to `tokens.css` first.

## Where a widget's rules live

The kernel widgets are in `base.css` because all three surfaces build them from `shared/components.ts` — `.z-status` and its five variants, `.z-table` / `.z-table__scroll` / `.z-table__num`, `.z-emptystate`, `.z-gated` / `.z-blockers`, `.z-kv`, `.z-form`. They used to live in `dashboard.css`, which meant the panel could construct a table it had no rules for.

**`.z-status--unknown` is not a shade of `.z-status--neutral`.** It is unfilled, dashed and italic, because a cell nobody has asked about must not render like a cell whose answer happens to be "no" — the Fleet route's four honest switch states are where the rule comes from. `--scheduled` and `--draft` remain as aliases of `--warn` and `--danger` for the two files that still emit them.

The agent transcript and diff rules (`#z-agent`, `.z-agent__*`, and `.z-agent__diff .is-add` / `.is-del` / `.is-meta`) are here too. They were forty rules in a `<style>` block inside `src/agent/agentPanel.ts`, re-served with a fresh nonce on every render for no reason other than that they had nowhere else to live. `diffView()` in `shared/components.ts` emits the same class names, so an agent approval card and a lane-scaffold preview show a diff the same way. The body rule is written `body:has(> #z-agent)` rather than bare, because this stylesheet is loaded by all three webviews and only one of them is a full-height column.

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

Codicons only, rendered as `<i class="codicon codicon-{name}">` by `icon()` in `dom.ts`. The extension draws **no SVG icons of its own** — `svgEl()` in `src/webview/shared/svg.ts` exists for figures (a sparkline, a gauge, a timeline), never for iconography; `codicon.css` and `codicon.ttf` are copied out of the `@vscode/codicons` devDependency into `dist/media/` by the `copy-media` plugin in `esbuild.js`, and a missing file there is a build error rather than a warning. A webview does not get codicons for free — without them every `icon()` call site renders an empty element and every icon-only control becomes an invisible box, which is a failure that looks exactly like a working build. All three shells link `dist/media/codicon.css` **before** `tokens.css`, and the three sizing rules in `base.css` are written as `.codicon[class*='codicon-']` so they outrank `codicon.css`'s own `font` shorthand.

## Adding a rule

1. If it needs a colour, check `tokens.css` for a token first. Add one there if
   there is none — never reach for a theme variable at the call site.
2. Put shared widget chrome in `base.css`, surface layout in `panel.css` or
`dashboard.css`. "Shared" means `shared/components.ts` builds it; if two surfaces could render the widget, its rules cannot live in one surface's file.
3. Never an inline `style` — see above. The CSP drops it silently.
4. Check it in a dark, a light and a high-contrast theme before calling it done.
HC themes flatten backgrounds, so anything expressed only as a background colour needs a `body.vscode-high-contrast` override at the bottom of the file.
