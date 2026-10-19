# AGENTS.md

Guidance for AI coding agents (Claude Code, Copilot, Cursor) working in **books**.

A shelf of book projects, plus a small Python app that manages them and an editor to write them in. Content lives in `library/<slug>/` as markdown and YAML and is the point of the repository; `src/bookshelf/` is a read model over it that adds status, validation, manuscript compilation, a dashboard, a local editor and a Claude-backed assistant. "Done" for a prose change means the chapter is continuous with its neighbours and `books validate` reports nothing new. "Done" for a code change means tests pass and any new check is documented in `docs/SCHEMA.md`.

## Stack & commands

Python 3.10+, standard library only at runtime except the optional `ai` extra (the Anthropic SDK). `pytest` for tests, `ruff` for lint. The studio is a stdlib HTTP server serving one hand-written page — no framework, no bundler, no build step.

```bash
# install dependencies:
pip install -e ".[dev]"        # or just: export PYTHONPATH=src
# run the app:
books studio --open            # the editor + AI assistant (needs the [ai] extra)
books list                     # also: show, new, add-chapter, stats, build, dashboard, serve, ask, context
# run tests:
python3 -m pytest
# lint:
ruff check src tests
# content checks:
books validate                 # schema + continuity across every book
python3 tools/unwrap-prose.py --check
```

## Conventions

- Conventional Commits: `type(scope): description` (`feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`ci`). Scope is the book slug for prose changes, the module for code.
- Default branch is `main` — branch from it and open a PR; never push to it directly.
- README-First, README-Last: read the nearest `README.md` before changing a
  directory, and update it after.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or
  leave empty exception handlers.
- Markdown is one paragraph per line — no soft wrapping. CI enforces it.

## Working here

- **Prose**: read the book's `outline.md`, the act guide in `guides/`, and the adjacent chapters before writing. Names are decided in `notes/characters.md`; open questions live in `notes/continuity.md`. Never put `(Chapter 8)` or a `[Placeholder]` in narrative text — both are validation findings.
- **Code**: no required runtime dependencies (the front matter parser has a stdlib fallback so `books validate` works in a bare checkout). The Anthropic SDK is the one exception and is optional -- `ai.py` imports it inside the client factory, and everything else must keep working without it. Only `cli.py` prints. A new check goes in `validate.py` with a code, a test, and a row in `docs/SCHEMA.md`.
- **Assistant**: `ai.py` builds every request from the book's own files. A new task is an entry in `TASKS`; changing what the model is given means changing `build_brief`/`build_local`, and `books context <slug>` shows the result without an API call. Model is `claude-opus-5-5` with adaptive thinking -- don't add `temperature`, `top_p` or `budget_tokens`, which that model rejects.
- Full agent brief: [`.github/copilot-instructions.md`](.github/copilot-instructions.md). Design rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Editor and assistant: [`docs/STUDIO.md`](docs/STUDIO.md).

## Fleet context

This repo is one of ~40 managed by the [bamr87/bamr87 dash](https://github.com/bamr87/bamr87) (registry: `_data/projects.yml`; tiered baseline: `docs/STANDARDS.md`). It is vendored there as a git submodule: commit and push changes **here** first — the hub only bumps its pointer afterwards. Shared CI, release, schema, and agent kits are seeded from the hub's `templates/`; prefer adopting those over hand-rolling equivalents.

This package lives in the zer0-CMS monorepo at `packages/books/`, and only the root `.github/workflows/` runs: `books.yml` installs `.[dev]`, then runs `pytest -q` and `ruff check src tests` on Python 3.10 and 3.12 (`bin/zer0 run test books` from the repository root does the same). The hub caller it replaced swallowed install failures, which is why the test suite adds `src/` to `sys.path` in `tests/conftest.py` and the package has no required dependencies.

Still missing for the baseline: a `LICENSE`. This repo holds both code and original fiction, which usually want different terms, so it needs an owner decision rather than a default.
