# `mcp_server/` — the content plane over MCP

> The content plane over MCP: the one tool registry served over Streamable HTTP and stdio, with the same checks as an agent run or a GraphQL/REST mutation.

The tool registry, served to MCP clients (M15). Three surfaces, one definition: an agent run, an MCP `tools/call` and a GraphQL/REST mutation all reach a tool through `registry.call`, with the same checks.

```bash
python manage.py agent_token seo --name "my editor"     # prints a bearer token once
python manage.py agent_token seo --list                    # the agent's tokens, by prefix
python manage.py agent_token seo --revoke zer0_AbCdEfG     # revoke one (logged as zer0.token.revoke)
# HTTP (Streamable HTTP, JSON responses): POST http://localhost:8000/mcp/ with Authorization: Bearer <token>
python manage.py mcp_stdio --agent seo                    # stdio, for a client on this machine
```

- **Principal.** A token resolves to one agent user; the agent's *live* definition decides what `tools/list` returns — exactly the tools `registry.call` would allow, narrowed further by the token's own `tools` list if it has one. A definition that has not passed its evals lists nothing.
- **Audit.** Every `tools/call` is a one-step `AgentRun` with trigger `mcp` and the call's trace id. A tool's answer names a run or a suggestion by its public id (`run_id`, `suggestion_id`: UUIDs), as every other surface does.
- **Errors.** A tool's refusal (policy, permission, invalid arguments) is a result with `isError: true`, which the model can read and act on; an unknown tool or a malformed request is a JSON-RPC error.
- **Transport.** POST only (GET is 405: no server-initiated streams), no batches, `MCP-Protocol-Version` checked when sent, and any `Origin` header outside `MCP_ALLOWED_ORIGINS` refused — MCP's rule against DNS rebinding.
- **Rate limits.** Every request spends a bucket first, as a REST request does (`ops/throttling.py`): the token's own, or the address's for a request without a valid token — so a failed sign-in is not free. Over the limit is HTTP 429 with `Retry-After` and a JSON-RPC error (`-32000`) whose `data` holds `code: rate.limited` and `retry_after`; a tool's own `rate` still holds inside it.

It is a Django view rather than a mounted FastMCP app (ADR 0001): the protocol surface is three methods, and one process with one auth path is simpler to secure than two.
