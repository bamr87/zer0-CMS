"""The platform's operational baseline (ops/README.md).

Probes (`/healthz`, `/readyz`, `/version`), the request id every response and
log line carries, JSON logging with secret redaction, the one error envelope
for REST, GraphQL and MCP, API throttling, the OpenAPI document and optional
error reporting. No models: everything here is middleware, views and settings.
"""
