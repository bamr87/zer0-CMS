# Pull request

## What this changes

<!-- What does this do, and what does it look like from the outside? -->

## Why

<!-- The problem it solves. Link an issue if there is one — not required. -->

## How it was tested

<!--
What you actually ran, and what it told you. `npm run compile` and `npm test` at minimum for extension changes; for `content/`, `python -m pytest -q`; for `web/`, `npm test`. If you skipped something, say so. -->

## Checklist

- [ ] `npm run compile` passes (type-check + lint + all five bundles) — skip if `content/**` or `web/**` only
- [ ] `npm test` passes — skip if `content/**` or `web/**` only
- [ ] `cd content && python -m pytest -q -m "not slow"` passes — skip if `src/**` only
- [ ] `src/core/` and `src/mcp/` still import no `vscode`
- [ ] No `innerHTML` added under `src/webview/`
- [ ] Every gate is still re-checked host-side — no new check that lives only in a webview
- [ ] The nearest `README.md` is updated (README-First, README-Last)

## Type of change

- [ ] Docs / refactor / dependency
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
