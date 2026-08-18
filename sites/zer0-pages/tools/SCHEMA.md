---
schema: "0.1"
coverage: listed
---

# SCHEMA — tools

> Repo tooling seeded by the bamr87 dash.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `schema_lint.py` | file | Vendored Pyramid Schema linter — `python3 tools/schema_lint.py check .` validates every SCHEMA.md against reality | |
| `unwrap-prose.py` | file | One-paragraph-per-line markdown fixer — `--check` gates in `markdown-oneline.yml`, `--write` repairs soft-wrapped prose | |
