---
schema: "0.1"
coverage: listed
---

# SCHEMA — development

> Docs on the development process behind the site and theme.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `index.md` | file | Development topic landing page | |
| `*.md` | pattern | One doc page per process concern (CI/CD, testing, releases, security, agents, devcontainer) | |

## Placement

- New development doc page → a kebab-case `.md` file here, linked from `index.md` and `_data/navigation/docs.yml`.
