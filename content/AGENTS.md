# AGENTS.md — the content plane (`content/`)

Guidance for AI coding agents working in `content/`, the Django + Wagtail content plane. The repository-wide rules — the plane boundary, the agent safety rules, the workflow — are in the root [`AGENTS.md`](../AGENTS.md); this file adds what holds inside this project. [`README.md`](README.md) maps the apps; ADR 0001 says why they exist.

"Done" for a change here means `python -m pytest -q` (with `-m "not slow"` as the fast loop) and `python manage.py makemigrations --check --dry-run` pass, `ruff check . && ruff format --check .` are clean, `python manage.py run_evals --all --recorded` passes, and the three committed schemas are current: `schemas/graphql/schema.graphql` (`manage.py graphql_schema --out …`), `schemas/content/ai-schema.json` (`manage.py wagtail_ai_schema --out …`) and `schemas/openapi/openapi.json` (`manage.py spectacular --format openapi-json --urlconf ops.openapi --fail-on-warn --file …`). CI runs the suite on SQLite and on Postgres with pgvector (`content.yml`).

## Invariants

- **Every content change goes through the registry or the accept flow.** A tool is the only way an agent touches content (`agents/registry.py`), and `suggestions.services.accept` is the only way a suggestion becomes a revision. Both call `cms.services.save_draft` / `publish`, which run in one transaction. Never add a second path that writes pages for an agent, and never call a tool function directly from a surface — call `registry.call`.
- **Tools declare an effect and run as an agent user.** `read`, `propose`, `write`, `publish`; the registry checks the narrower of the agent's and the page's policy, the agent's tools list (and the token's), the principal (`agent:<slug>`, active, never staff or superuser), Wagtail permissions as that user, and the rate. A review agent never gets a `publish` tool. A new tool needs an input schema with `additionalProperties: false` (`obj()`), and the cheapest effect that is true.
- **Agents start at `suggest`; promotion is earned.** A definition goes live only through `AgentDefinition.publish()`, which runs the eval gate; raising the policy also needs the accept rate. Change an agent by editing `agents/definitions/<slug>.yaml`, never by setting `live` or `policy` on a row.
- **Tests never call a model.** Use `FakeLLM` in unit tests and recordings (`agents/recordings/`, placeholders instead of ids) for eval scenarios. A prompt change makes its recordings stale on purpose: re-record, don't loosen the digest check.
- **One revision per accepted outcome.** Accept a run's suggestions together; a tool that writes (`content.draft_revision`) writes one revision for all its ops. Intermediate work lives in `AgentStep` rows, not in revisions.
- **An event is emitted in the transaction that made the change.** `outbox.services.emit` refuses otherwise. A new event type is a schema in `schemas/events/` (and an example) first, with contract tests on both planes; a breaking change is a new version.
- **Agent review is never a workflow's last task.** Approving the last task publishes the page as the approver, and an agent never publishes; `AgentReviewTask` rejects with that reason when it is last.
- **Order-preserving JSON where order is content.** `BasePage.front_matter` is an `OrderedJSONField` because Postgres `jsonb` sorts keys; use it for any JSON whose key order a person wrote.
- **The Jekyll bridge is exact.** An unchanged page exports its stored source byte for byte; a changed page renders typed fields over its original front matter (dates stay the original string unless the date changed). The importer never overwrites a page an editor changed in Wagtail (`--force` aside). `test_the_real_sites_round_trip_byte_for_byte` holds every site in this repository to that.
- **Vectors live in `graph.Embedding`, never on a page row** (a revision would copy them), keyed by model and content hash.
- **Vendored here:** `agents/data/abc_lexicons/*.yml` are byte-identical copies of `rails/lib/zer0_cms/abc/lexicons/*.yml`, declared in the root `workspace.yml`. Edit the source and run `bin/zer0 vendor --write`.
- **Every non-2xx is the envelope.** A REST view raises `ops.errors.ApiError` (or `Invalid`, `Forbidden`, `NotFound`, `Conflict`, `Unavailable`) or a DRF exception and never returns `Response({"error": …})`; a GraphQL resolver raises `GraphQLError` for an error the client should read; MCP keeps JSON-RPC errors. `/healthz` touches nothing — a probe view is `non_atomic_requests` and never reads the database; what needs a dependency belongs in `/readyz`'s checks (`ops/README.md`).
- **Nothing logs a secret.** Log through `logging` (the handler redacts token shapes and `Authorization` values); never print a token, and never put one in an exception message that a `500` could carry — the envelope hides the message, the log does not.

## Conventions

- Every module opens with a docstring saying what it is and why it exists; every app has the README its code points to.
- Ruff is the linter and formatter (`pyproject.toml`); no blind `except` without a comment saying why, no `# type: ignore`.
- Migrations are generated (`makemigrations`), never hand-written, except the pgvector extension step in `graph/migrations/0001_initial.py`.
