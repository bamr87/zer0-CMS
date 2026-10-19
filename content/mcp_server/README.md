# `mcp_server/` — the content plane over MCP

The tool registry, served to MCP clients (M15). Three surfaces, one definition: an agent run, an MCP `tools/call` and a GraphQL/REST mutation all reach a tool through `registry.call`, with the same checks.

```bash
python manage.py agent_token seo --name "my editor"     # prints a bearer token once
# HTTP (Streamable HTTP, JSON responses): POST http://localhost:8000/mcp/ with Authorization: Bearer <token>
python manage.py mcp_stdio --agent seo                    # stdio, for a client on this machine
```

- **Principal.** A token resolves to one agent user; the agent's *live* definition decides what `tools/list` returns — exactly the tools `registry.call` would allow, narrowed further by the token's own `tools` list if it has one. A definition that has not passed its evals lists nothing.
- **Audit.** Every `tools/call` is a one-step `AgentRun` with trigger `mcp` and the call's trace id.
- **Errors.** A tool's refusal (policy, permission, invalid arguments) is a result with `isError: true`, which the model can read and act on; an unknown tool or a malformed request is a JSON-RPC error.
- **Transport.** POST only (GET is 405: no server-initiated streams), no batches, `MCP-Protocol-Version` checked when sent, and any `Origin` header outside `MCP_ALLOWED_ORIGINS` refused — MCP's rule against DNS rebinding.

It is a Django view rather than a mounted FastMCP app (ADR 0001): the protocol surface is three methods, and one process with one auth path is simpler to secure than two.
