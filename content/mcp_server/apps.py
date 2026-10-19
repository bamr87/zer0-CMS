"""App config for `mcp_server`."""

from django.apps import AppConfig


class McpServerConfig(AppConfig):
    name = "mcp_server"
    verbose_name = "MCP server"
    default_auto_field = "django.db.models.BigAutoField"
