"""`manage.py linkedin mcp --site PATH` — the lane over a site's own files as
Model Context Protocol tools, newline-delimited JSON-RPC on stdio, for Claude
Code or any MCP client working in a site's checkout (the Ruby lane's
`zer0-cms linkedin mcp`, ported).

Reads and previews are always available; `linkedin_draft` writes a pending
draft — a model drafts, a person approves. There is deliberately no approve
tool. `linkedin_publish` needs three things no model can supply:
`ZER0_LINKEDIN_MCP_PUBLISH=1` and `ZER0_LINKEDIN_PUBLISH=1` in the server's
environment and `confirm: true` on the call; it then runs the same
`Pipeline.publish` as every surface, so a draft nobody approved is still
refused, and never as a merged run. Every call re-reads the settings and the
queue from disk. The platform's own MCP server (`/mcp/`) carries the
platform's queue: `distribution.compose` and `distribution.publish`.
"""

import json

from mcp_server.protocol import INVALID_REQUEST, METHOD_NOT_FOUND, PARSE_ERROR, SUPPORTED_VERSIONS, error, result

from ..ledger import LedgerError
from ..linkedin import Error, plan
from .pipeline import Pipeline
from .site import Config, ConfigError, truthy

ARM_VARIABLE = "ZER0_LINKEDIN_MCP_PUBLISH"
READ = {"readOnlyHint": True, "openWorldHint": False}
WRITE = {"readOnlyHint": False, "destructiveHint": False}


def _tool(name, description, properties=None, required=(), annotations=READ):
    schema = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = list(required)
    return {"name": name, "description": description, "inputSchema": schema, "annotations": annotations}


TOOLS = [
    _tool(
        "linkedin_status",
        "The site's LinkedIn distribution state: author, API version health, queue counts, ledger, "
        "which credentials are present (never their values). With check: true, asks LinkedIn about the token.",
        {"check": {"type": "boolean"}},
        annotations={**READ, "openWorldHint": True},
    ),
    _tool(
        "linkedin_plan",
        "Every LinkedIn API call this lane can make — verb, path, scopes, what comes back. Nothing "
        "outside it can be called.",
    ),
    _tool(
        "linkedin_sources",
        "Pages that can be shared (live, titled, described, with a public URL). all: true "
        "includes pages already shared.",
        {"all": {"type": "boolean"}},
    ),
    _tool("linkedin_queue", "The draft queue: every draft with its status (pending, approved, published) and type."),
    _tool(
        "linkedin_preview",
        "The exact LinkedIn payload a draft would send, the brand guard's findings, and every "
        "blocker. No network call, no write.",
        {"draft": {"type": "string"}},
        ["draft"],
    ),
    _tool(
        "linkedin_draft",
        "Write a pending draft into the queue: an article share of a page (source, optional "
        "commentary) or a text update (update: true, message, slug). A person must approve it before it can publish.",
        {
            "source": {"type": "string"},
            "commentary": {"type": "string"},
            "update": {"type": "boolean"},
            "message": {"type": "string"},
            "slug": {"type": "string"},
        },
        annotations={**WRITE, "openWorldHint": False},
    ),
    _tool(
        "linkedin_posts",
        "The configured author's own recent LinkedIn posts.",
        {"count": {"type": "integer", "minimum": 1, "maximum": 100}},
        annotations={**READ, "openWorldHint": True},
    ),
    _tool(
        "linkedin_publish",
        "Publish one approved draft to LinkedIn. OFF unless the server was started with "
        "ZER0_LINKEDIN_MCP_PUBLISH=1 and ZER0_LINKEDIN_PUBLISH=1; needs confirm: true; refuses any draft the site's "
        "approval gate does not accept.",
        {"draft": {"type": "string"}, "confirm": {"type": "boolean"}},
        ["draft", "confirm"],
        annotations={**WRITE, "openWorldHint": True},
    ),
]


class Server:
    def __init__(self, site, *, env, pipeline_options=None):
        self.site, self.env = site, env
        self.options = pipeline_options or {}

    def run(self, lines, write) -> int:
        for line in lines:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                write(error(None, PARSE_ERROR, "parse error"))
                continue
            response = self.handle(message)
            if response is not None:
                write(response)
        return 0

    def handle(self, message):
        if not isinstance(message, dict):
            return error(None, INVALID_REQUEST, "invalid request")
        id_, method = message.get("id"), str(message.get("method") or "")
        if id_ is None:
            return None  # a notification
        if method == "initialize":
            asked = (message.get("params") or {}).get("protocolVersion")
            return result(
                id_,
                {
                    "protocolVersion": asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "zer0-linkedin", "title": "zer0-CMS LinkedIn lane"},
                    "instructions": "Draft LinkedIn posts for this site with linkedin_draft; a person approves them. "
                    "Preview before anything else. Publishing is off unless the operator armed it.",
                },
            )
        if method == "ping":
            return result(id_, {})
        if method == "tools/list":
            return result(id_, {"tools": TOOLS})
        if method == "tools/call":
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            return result(id_, self.call(str(params.get("name") or ""), arguments))
        return error(id_, METHOD_NOT_FOUND, f"method not found: {method}")

    def call(self, name: str, args: dict) -> dict:
        try:
            # The server never runs as a merged run: a draft must be approved, whatever acceptStatuses says.
            env = {k: v for k, v in self.env.items() if k != "ZER0_LINKEDIN_MERGED"}
            config = Config(self.site, env=env)
            data = self.dispatch(name, args, config, Pipeline(config, **self.options))
            return {
                "content": [{"type": "text", "text": data if isinstance(data, str) else json.dumps(data, indent=2)}],
                "isError": False,
            }
        except (ValueError, KeyError, ConfigError, LedgerError, Error) as e:
            return {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}

    def dispatch(self, name, args, config, pipeline):
        if name == "linkedin_status":
            return pipeline.status(check=args.get("check") is True)
        if name == "linkedin_plan":
            return {"calls": [c.as_dict() for c in plan.CALLS]}
        if name == "linkedin_sources":
            return [s.as_dict() for s in pipeline.sources() if args.get("all") is True or not s.urn]
        if name == "linkedin_queue":
            return [
                {"id": d.id, "path": d.relative, "status": d.status, "type": d.type, "source": d.text("source")}
                for d in pipeline.drafts()
            ]
        if name == "linkedin_preview":
            return pipeline.preview(pipeline.draft(args["draft"])).as_dict(config.root)
        if name == "linkedin_draft":
            if args.get("update") is True:
                created = pipeline.compose_update(str(args["message"]), slug=str(args["slug"]))
            else:
                created = pipeline.compose(args["source"], commentary=args.get("commentary"))
            return {
                "created": created.relative,
                "status": created.status,
                "preview": pipeline.preview(created).as_dict(config.root),
            }
        if name == "linkedin_posts":
            return pipeline.posts(count=int(args.get("count") or 10))
        if name == "linkedin_publish":
            if not truthy(self.env.get(ARM_VARIABLE)):
                raise ValueError(f"linkedin_publish is off: the operator must start this server with {ARM_VARIABLE}=1")
            if args.get("confirm") is not True:
                raise ValueError("linkedin_publish needs confirm: true")
            return pipeline.publish(pipeline.draft(args["draft"]), live=True).as_dict()
        raise ValueError(f"unknown tool {name}")
