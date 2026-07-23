# CLAUDE.md

Guidance for AI coding agents (Claude Code, Copilot, Cursor) working in **zer0-CMS**.

zer0-CMS has two halves. `src/` is the **VS Code extension** (an AI-augmented fork of Front Matter CMS) that *edits* content. `rails/` is the **content engine** — a Ruby on Rails app + stdlib-only Ruby library that *generates* content, starting with children's **ABC / alphabet books**: it writes the words, composes a text-free illustration prompt per letter (art styles shared with the `zer0-image-generator` plugin), and exports a Jekyll board book for **drsai** to publish. "Done" for an engine change means `ruby -Ilib test/zer0_cms/*.rb` passes and the wizard still emits a valid ABC Book Spec.

## Stack & commands

```bash
# ── ABC content engine (rails/) — stdlib-only, no bundler needed ──
cd rails
ruby bin/zer0-cms styles                        # list ABC art styles
ruby bin/zer0-cms themes                         # list bundled A–Z lexicons
ruby bin/zer0-cms new --theme "IT systems" --out ../../drsai   # draft + export a book
ruby -Ilib test/zer0_cms/test_abc_engine.rb      # engine tests (zero network)
bundle install && bin/rails server               # optional web wizard → :3000

# ── VS Code extension (src/) ──
npm install
npm run build
npm test
```

## Conventions

- Conventional Commits: `type(scope): description` (`feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`ci`).
- Default branch is `main` — branch from it and open a PR; never push to it directly.
- README-First, README-Last: read the nearest `README.md` before changing a
  directory, and update it after.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or
  leave empty exception handlers.

## Fleet context

This repo is one of ~40 managed by the [bamr87/bamr87 dash](https://github.com/bamr87/bamr87) (registry: `_data/projects.yml`; tiered baseline: `docs/STANDARDS.md`). It is vendored there as a git submodule: commit and push changes **here** first — the hub only bumps its pointer afterwards. Shared CI, release, schema, and agent kits are seeded from the hub's `templates/`; prefer adopting those over hand-rolling equivalents.
