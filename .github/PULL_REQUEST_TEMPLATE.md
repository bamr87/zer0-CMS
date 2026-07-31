# Pull request

## What this changes

<!-- What does this do, and what does it look like from the outside? -->

## Why

<!-- The problem it solves. Link an issue if there is one — not required. -->

## How it was tested

<!--
  What you actually ran, and what it told you. `npm run compile` and
  `npm test` at minimum for extension changes; for `rails/`,
  `ruby -Ilib test/zer0_cms/test_abc_engine.rb`.
  If you skipped something, say so.
-->

## Checklist

- [ ] `npm run compile` passes (type-check + lint + all five bundles)
- [ ] `npm test` passes
- [ ] `src/core/` and `src/mcp/` still import no `vscode`
- [ ] No `innerHTML` added under `src/webview/`
- [ ] Every gate is still re-checked host-side — no new check that lives only in a webview
- [ ] The nearest `README.md` is updated (README-First, README-Last)

## Type of change

- [ ] Docs / refactor / dependency
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
