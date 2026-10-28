# `ops/` — the operational baseline

What an operator, a load balancer and a log pipeline need from the platform, and nothing a content feature needs: no models, no admin, no tools. The fleet's standard is the hub's `specs/BACKEND.md` and `specs/OPERATIONS.md`; each module below names the rows it satisfies.

| Module | What it is | Rows |
|---|---|---|
| `views.py` | `/healthz` (liveness, touches nothing), `/readyz` (database, cache, Redis — 503 with `checks` when one is down), `/version` (`name`, `version`, `commit`, `built_at`). Plain Django views outside `ATOMIC_REQUESTS`, so a dead database cannot turn liveness into a 500. | BE-10, BE-11 |
| `readiness.py` | The checks `/readyz` runs, each bounded (0.5 s on Redis). | BE-10 |
| `context.py` | The request id: bound for the request's duration, echoed from `X-Request-Id` when it is safe to log, else a UUID4. | BE-04 |
| `middleware.py` | `RequestIdMiddleware` (first in `MIDDLEWARE`: `X-Request-Id` and `X-App-Version` on every response), `AccessLogMiddleware` (one line per request, probes excepted), `SecurityHeadersMiddleware` (`Permissions-Policy`, a report-only CSP). | BE-04, OPS-11, OPS-23 |
| `logging.py` | `JsonFormatter` (`ts level msg logger request_id trace_id app version` + extras), `TextFormatter`, `RedactionFilter` and `ContextFilter`; `redact()` scrubs `sk-ant-`, `ghp_`, `github_pat_`, `AIza`, this platform's `zer0_` (agent) and `zer0u_` (person) tokens and `Authorization` values. `ExceptionReporterFilter` (`DEFAULT_EXCEPTION_REPORTER_FILTER`) redacts the same shapes in the frame variables of Django's error reports and keeps `sensitive_variables` hidden with `DEBUG` on too. `LOG_FORMAT` is `json` or `text`. | OPS-10, OPS-12 |
| `errors.py` | The envelope and the handlers that produce it (below). | BE-20, BE-21, BE-22 |
| `throttling.py` | Per anonymous address, per person, per agent token; `429` + `Retry-After`; an empty rate turns a scope off. | BE-05 |
| `openapi.py` | The document's URLconf (`SERVE_URLCONF`), the envelope's schema and the agent-token security scheme. | BE-12, BE-31 |
| `sentry.py` | Error reporting when `SENTRY_DSN` is set, release-tagged, request-id-tagged, and redacted: every string in an event — the message, each exception's value, every frame's variables — goes through `redact()`. | OPS-13 |
| `apps.py` | System check `ops.E001`: `CORS_ALLOW_ALL_ORIGINS` with credentials is refused. | BE-06 |

## The envelope

Every non-2xx a REST path returns, whoever answers it:

```json
{"error": {"code": "resource.not_found", "message": "not found", "status": 404,
           "details": [], "request_id": "6f1c…", "retry_after": null}}
```

A view raises `ops.errors.ApiError` (or `Invalid`, `Forbidden`, `NotFound`, `Conflict`, `Locked`, `Unavailable`) or any DRF exception; `drf_exception_handler` renders it. What Django answers itself — an unknown path, a CSRF failure, a crash — is rendered by the `handler400/403/404/500` views in `config/urls.py` when the path is an API path (`/api/`, `/graphql/`, `/mcp/`, the probes) or the request asks for `application/json`; HTML paths keep Django's pages. A validation failure is `422` with one `details` entry per field. A crash is `internal.error` with the request id and nothing else; the log line with the same id holds the traceback.

| Code | Status | When |
|---|---|---|
| `auth.required` | 401 | no credentials (`WWW-Authenticate: Bearer`) |
| `auth.invalid_token` | 401 | a bearer token that is unknown, revoked or inactive |
| `auth.forbidden` | 403 | signed in, not allowed |
| `auth.csrf_failed` | 403 | a session-authenticated POST without the CSRF token, or a sign-in without it |
| `auth.invalid_credentials` | 400 | a sign-in (`/api/v2/session/login`) with a wrong username or password |
| `request.malformed` | 400 | unparsable body or query |
| `request.method_not_allowed` | 405 | |
| `request.unsupported_media_type` | 415 | |
| `request.not_acceptable` | 406 | |
| `validation.failed` | 422 | per-field `details` |
| `resource.not_found` | 404 | |
| `resource.conflict` | 409 | a run that is refused, a suggestion that can no longer be decided |
| `resource.locked` | 409 | a page a Wagtail lock keeps from the caller — another person's lock, a workflow task's, or a scheduled publish's (cancel it to edit); the message says which |
| `rate.limited` | 429 | `retry_after` and the `Retry-After` header |
| `upstream.unavailable` | 503 | a dependency the request needed is down |
| `internal.error` | 500 | |

Two surfaces keep their own protocol's shape and carry the same ids: **GraphQL** keeps its `errors` array and adds `extensions.code` (`graphql.invalid` for a parse or validation error, the resolver's own code or `graphql.error` for an error raised on purpose, `internal.error` for a crash — with the message replaced) and `extensions.request_id`; **MCP** keeps JSON-RPC errors and adds `data.request_id` over HTTP (a crash is `-32603`), and nothing over stdio, where there is no request.

## Origins

Two allowlists on purpose: `CORS_ALLOWED_ORIGINS` decides which browser origins may call `/api/`, `/graphql/` and `/mcp/` at all (the admin stays same-origin); `MCP_ALLOWED_ORIGINS` is MCP's own DNS-rebinding rule on `/mcp/` and is checked after it.

## The OpenAPI document

`schemas/openapi/openapi.json` is generated and committed, and CI fails when it drifts, like the GraphQL SDL and the agent schema. It covers the platform's own endpoints under `/api/v2/`; Wagtail's `pages`, `images` and `documents` viewsets build their serializer per request and cannot be introspected, so they are documented by Wagtail and listed in the description. The docs UI is at `/api/v2/docs/` where `API_DOCS_ENABLED` is true (development and tests; off in production by default).

It is the same document whichever database generates it, and `content.yml` checks it on SQLite and on Postgres. A ModelSerializer gives a writable integer field the bounds Django reads from the database (`connection.ops.integer_field_range`: 64-bit on SQLite, 16- or 32-bit on Postgres), so a field the API only answers with is read-only (`read_only_fields`), and one it accepts is declared with the bounds the API means; `tests/ops/test_openapi.py` fails on any bound that is a database's integer range.

```bash
cd content && python manage.py spectacular --format openapi-json --urlconf ops.openapi --fail-on-warn --file ../schemas/openapi/openapi.json
```

## Settings

`LOG_FORMAT`, `LOG_LEVEL`, `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS`, `THROTTLE_ANON_RATE`, `THROTTLE_PRINCIPAL_RATE`, `NUM_PROXIES`, `PERMISSIONS_POLICY`, `CSP_REPORT_ONLY`, `CSP_REPORT_URI`, `API_DOCS_ENABLED`, `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`, `GIT_SHA`, `BUILT_AT` — all in `content/.env.example`, all read once in `config/settings/base.py`.
