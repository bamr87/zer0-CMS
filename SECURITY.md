<!-- kit: community v0.1.0 · the fleet default SECURITY policy (UPS-REPO-14), with this repository's scope added. -->

# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| The latest release of each component (the extension, `zer0-image-generator`) and the `main` branch | ✅ |
| Anything older | ❌ |

Security fixes ship as patch releases through release-please.

## Reporting a vulnerability

**Do not open a public issue.** Report privately through GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) on this repository (**Security → Report a vulnerability**), or email **amr.abdel@gmail.com**.

Please include the component and version or commit, what an attacker can do, and the steps to reproduce.

## Response window

You will get an acknowledgement **within 7 days**. We then agree a fix timeline with you, and credit you in the advisory unless you ask us not to.

## Scope

What this repository runs, and where a report is most likely to land:

| Surface | Where | Notes |
| --- | --- | --- |
| The platform's admin | `content/` — `/admin/` | Wagtail sessions; CSRF on every form and on session-authenticated GraphQL mutations |
| The platform's APIs | `/api/v2/`, `/graphql/`, `/mcp/` | Agent tokens (`Authorization: Bearer zer0_…`, hashed at rest, revocable) act as one agent user with ordinary Wagtail permissions; browser origins are an allowlist (`CORS_ALLOWED_ORIGINS`); rates per address, person and token; every error is the envelope in `content/ops/README.md` and never a traceback |
| Agents and tools | `content/agents/` | Every tool declares its effect and runs as `agent:<slug>`, never a superuser; page text and user input are untrusted data; review agents hold no publish tool |
| The VS Code extension | `src/` | Zero shipped runtime dependencies; the webview is UI, never the gate; publishing, exec and scaffolding are off unless the person's own settings and Workspace Trust arm them |
| The image-generator panel | `packages/zer0-image-generator/web/` | Published on loopback only; confined paths; a nonce CSP. Being absorbed into the platform (ADR 0004); the Rails fleet CMS beside it was deleted (ADR 0008) |

Secrets this repository's automation uses, by name only (values live in GitHub secrets or a local `.env`, never in a committed file): `CONTENT_SECRET_KEY`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `FLEET_TOKEN`, `SENTRY_DSN`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_ACCESS_TOKEN`, the image providers' keys (`OPENAI_API_KEY`, `XAI_API_KEY`, `STABILITY_API_KEY`, `GEMINI_API_KEY`). The platform's logs redact the fleet's token shapes and `Authorization` values (`content/ops/logging.py`); a report that one still leaks is in scope.
