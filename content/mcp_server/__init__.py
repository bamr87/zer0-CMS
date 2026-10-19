"""The content plane's MCP server (M15): the tool registry, served over MCP's
Streamable HTTP transport at /mcp/ and over stdio by `manage.py mcp_stdio`.
Named `mcp_server`, not `mcp`, so it never shadows the `mcp` package."""
