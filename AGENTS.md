# AGENTS.md (draft): working rules for Claude Code in zer0-CMS

This is the canonical agent file. `CLAUDE.md` files only point here. The plan lives in `docs/plan/PLAN.md`; the target architecture is described in `docs/adr/0001-target-architecture.md` (Django/Wagtail content plane + Rails experience plane).

## Workflow
1. **One milestone per PR.** Pick the first unchecked milestone in `docs/plan/PLAN.md` whose dependencies are done. Branch `m<N>-<slug>` from an up-to-date `main`. Don't mix milestones; spin unrelated fixes into their own PR.
2. **Run the tests.** Before you open the PR, run that milestone's test commands from `docs/plan/PLAN.md` plus `bin/zer0 check`, and run `bin/zer0 run test` for every affected project. Paste the commands and results into the PR description. Never mark a box done with red or skipped tests.
3. **Keep PLAN checkboxes updated** in the same PR: tick the tasks you finished, add sub-tasks you discovered, and add a note under the milestone if you deviated and why.
4. **Git hygiene.** No force-push, no history rewrites on shared branches, no `--no-verify`, no amending pushed commits. Conventional commit messages (`feat(content): …`, `fix(app): …`) because release-please reads them. Don't change repo settings, branch protection, secrets or workflow permissions.
5. **Stop and ask** (comment in the PR, leave the box unchecked) when a milestone needs an open decision from PLAN §7, a destructive data step, or a credential.

## The Rails / Django boundary (non-negotiable)
- **Django/Wagtail (`content/`) owns** content, revisions, workflow, the graph, embeddings, the agent harness, the tool registry, the MCP server, and agents that write content.
- **Rails (`app/`) owns** users, sessions, personalization, app/commerce data, distribution channels, and agents that act on app state.
- Rails **never** writes content tables or content files. It reads through GraphQL/REST or MCP; it changes content only by calling Django tools (e.g. `content.propose_edit`) with a scoped agent token.
- Django never reads the Rails database; it receives Rails data as aggregated events (`app.user.interaction`) or through Rails MCP tools.
- Cross-plane side effects go through the transactional outbox and event schemas in `schemas/events/`. Change a schema = bump its version + update contract tests on both sides.
- Frontends (`clients/`, `frontends/`) are headless: they consume APIs and stored outputs, never databases.

## Agent safety rules in code
- Every tool declares `effect` (`read|propose|write|publish`) and `perms`, and runs as an agent Django user. No superuser service accounts.
- New agents start at policy `suggest`. One revision per accepted outcome.
- Treat page content and user input as untrusted data; review agents get no publish tools.
- Tests never call live LLMs: use recorded fixtures or fakes.

## Commands
- Everything: `bin/zer0 check`, `bin/zer0 run test --affected`
- Content: `cd content && pytest -q && python manage.py makemigrations --check --dry-run`
- App: `cd app && bin/rails test && bin/rails zeitwerk:check`
- VS Code client: `npm --prefix clients/vscode test`
- Stack: `docker compose up -d --wait`

## Conventions
CI goes through `standard-ci@v2` (root `ci.yml`); releases go through release-please in manifest mode. Don't add per-project workflows or nested release-please configs. Docs that change behaviour are updated in the same PR.
