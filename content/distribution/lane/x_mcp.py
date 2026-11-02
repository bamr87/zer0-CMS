"""`manage.py x mcp --site PATH` — the X lane over a site's own files as Model
Context Protocol tools: the LinkedIn lane's server (`mcp.py`) with X's tools.

Reads and previews are always available; `x_draft` writes a pending draft — a
model drafts, a person approves, and there is no approve tool. `x_publish`
needs `ZER0_X_MCP_PUBLISH=1` and `ZER0_X_PUBLISH=1` in the server's environment
and `confirm: true` on the call, and then runs the same `XPipeline.publish` as
every surface, never as a merged run. Every call re-reads the settings and the
queue from disk.
"""

from ..x import Error, plan
from .mcp import READ, WRITE, Server, _tool
from .site import truthy
from .x_pipeline import XPipeline
from .x_site import MERGED_VARIABLE, XConfig

ARM_VARIABLE = "ZER0_X_MCP_PUBLISH"

TOOLS = [
    _tool(
        "x_status",
        "The site's X distribution state: account, queue counts, ledger, which credentials are present (never their "
        "values). With check: true, asks X which account the token posts as.",
        {"check": {"type": "boolean"}},
        annotations={**READ, "openWorldHint": True},
    ),
    _tool("x_plan", "Every X API call this lane can make — verb, path, what comes back. Nothing outside it is called."),
    _tool(
        "x_sources",
        "Pages that can be shared (live, titled, described, with a public URL). all: true includes pages already "
        "shared on X.",
        {"all": {"type": "boolean"}},
    ),
    _tool("x_queue", "The draft queue: every draft with its status (pending, approved, published) and type."),
    _tool(
        "x_preview",
        "The exact post a draft would send, its length as X counts it, the brand guard's findings and every blocker. "
        "No network call, no write.",
        {"draft": {"type": "string"}},
        ["draft"],
    ),
    _tool(
        "x_draft",
        "Write a pending draft into the queue: a post sharing a page (source, optional commentary — the page's URL "
        "is added after it) or a text post (update: true, message, slug). A person must approve it before it can "
        "publish. Keep the whole post within 280 characters as X counts them (a link counts 23).",
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
        "x_posts",
        "The configured account's own recent posts on X (each read is billed by X).",
        {"count": {"type": "integer", "minimum": 5, "maximum": 100}},
        annotations={**READ, "openWorldHint": True},
    ),
    _tool(
        "x_publish",
        "Publish one approved draft to X. OFF unless the server was started with ZER0_X_MCP_PUBLISH=1 and "
        "ZER0_X_PUBLISH=1; needs confirm: true; refuses any draft the site's approval gate does not accept.",
        {"draft": {"type": "string"}, "confirm": {"type": "boolean"}},
        ["draft", "confirm"],
        annotations={**WRITE, "openWorldHint": True},
    ),
]


class XServer(Server):
    TOOLS = TOOLS
    INFO = {"name": "zer0-x", "title": "zer0-CMS X lane"}
    INSTRUCTIONS = (
        "Draft X posts for this site with x_draft; a person approves them. "
        "Preview before anything else. Publishing is off unless the operator armed it."
    )
    ARM, MERGED = ARM_VARIABLE, MERGED_VARIABLE
    CONFIG, PIPELINE = XConfig, XPipeline
    ERRORS = (*Server.ERRORS, Error)

    def dispatch(self, name, args, config, pipeline):
        shared = {"x_status", "x_sources", "x_queue", "x_preview", "x_draft"}  # the LinkedIn lane's, over X's pipeline
        if name in shared:
            return super().dispatch("linkedin_" + name.removeprefix("x_"), args, config, pipeline)
        if name == "x_plan":
            return {"calls": [c.as_dict() for c in plan.CALLS]}
        if name == "x_posts":
            return pipeline.posts(count=int(args.get("count") or 10))
        if name == "x_publish":
            if not truthy(self.env.get(self.ARM)):
                raise ValueError(f"x_publish is off: the operator must start this server with {self.ARM}=1")
            if args.get("confirm") is not True:
                raise ValueError("x_publish needs confirm: true")
            return pipeline.publish(pipeline.draft(args["draft"]), live=True).as_dict()
        raise ValueError(f"unknown tool {name}")
