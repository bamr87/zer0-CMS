"""What a strict MCP client checks before it lists one tool: the `initialize`
result as MCP's schema (2025-06-18) defines InitializeResult and its
Implementation, held as JSON Schema with nothing left loose. Claude Code
parses it this strictly, and refused the LinkedIn lane when serverInfo had no
version. Every Python MCP server here (`/mcp/` and `mcp_stdio`, the LinkedIn
lane, the X lane) answers through `mcp_server.protocol.initialize_result`, and
each server's test holds its reply to this schema.
"""

from jsonschema import Draft202012Validator

from mcp_server.protocol import SUPPORTED_VERSIONS

IMPLEMENTATION = {
    "type": "object",
    "required": ["name", "version"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

INITIALIZE_RESULT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["protocolVersion", "capabilities", "serverInfo"],
    "properties": {
        "protocolVersion": {"enum": list(SUPPORTED_VERSIONS)},
        "capabilities": {
            "type": "object",
            "properties": {
                "tools": {
                    "type": "object",
                    "properties": {"listChanged": {"type": "boolean"}},
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "serverInfo": IMPLEMENTATION,
        "instructions": {"type": "string"},
    },
    "additionalProperties": False,
}

VALIDATOR = Draft202012Validator(INITIALIZE_RESULT)


def check_initialize(result: dict) -> dict:
    """Every way `result` breaks the schema, as one failure; else the server's serverInfo."""
    problems = [
        f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in VALIDATOR.iter_errors(result)
    ]
    assert not problems, problems
    return result["serverInfo"]
