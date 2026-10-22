"""The tool registry: one definition, three surfaces (note §2.5).

A tool is a function registered with `@tool(...)`: a JSON Schema for its
input, an effect (`read`, `propose`, `write`, `publish`), the permissions it
needs and an optional rate. The runner (agents/runner.py), the MCP server
(mcp_server/) and the GraphQL/REST mutations all call `registry.call()`, so
every check below is written once and holds on every surface:

1. **The tool exists and this caller may use it** — it is in the agent's
   `tools` list (and in the token's, when the caller has one). A review agent
   is never offered a `publish` tool, whatever its list says.
2. **The arguments match the schema** — validated before the function runs.
3. **The principal is an agent user** — `agent:<slug>`, active, not staff,
   not superuser. There is no service-account path.
4. **The policy allows the effect** — the narrower of the agent's policy and
   the target page's (`off` < `suggest` < `draft` < `auto`). `read` needs
   anything but `off`; `propose` needs `suggest`; `write` needs `draft` and a
   live (eval-passed) definition; `publish` needs `auto`.
5. **The permissions hold** — as that user, through Wagtail's own page
   permission tester when the tool targets a page; and when the call acts for
   a person (`ToolContext.on_behalf_of`: a run a person asked for, whose
   prompt and tools they chose), that person must be able to edit the page
   too, so a run never reads a draft its starter could not.
6. **The rate holds** — per agent user and tool, in the cache.

The call then runs in its own transaction and is recorded as an `AgentStep`
of the caller's run, with its arguments, result, latency and any error.
`check()` asks the same questions (all but the rate) without calling, for a
surface that queues work which will end in a call — the AI layer's runs on a
page ask it when they are requested.
"""

import time
from dataclasses import dataclass, field

from django.core.cache import cache
from django.db import transaction
from jsonschema import Draft202012Validator

from cms.models import POLICY_AUTO, POLICY_DRAFT, POLICY_OFF, POLICY_ORDER, POLICY_SUGGEST

from .principals import is_agent_user

EFFECTS = ("read", "propose", "write", "publish")
MIN_POLICY = {"read": POLICY_SUGGEST, "propose": POLICY_SUGGEST, "write": POLICY_DRAFT, "publish": POLICY_AUTO}
PAGE_PERMISSION_TESTS = {
    "wagtailcore.add_page": "can_add_subpage",
    "wagtailcore.change_page": "can_edit",
    "wagtailcore.publish_page": "can_publish",
    "wagtailcore.delete_page": "can_delete",
}


class ToolError(Exception):
    """A refused or failed call. `code` is one of: not_found, not_allowed,
    invalid_args, permission_denied, policy, rate_limited, failed."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def as_dict(self):
        return {"error": self.code, "message": self.message}


@dataclass(frozen=True)
class Tool:
    name: str
    fn: object
    description: str
    input_schema: dict
    effect: str
    perms: tuple = ()
    rate: str | None = None
    page_arg: str | None = None

    @property
    def annotations(self) -> dict:
        """MCP tool annotations derived from the effect."""
        return {
            "title": self.name,
            "readOnlyHint": self.effect == "read",
            "destructiveHint": self.effect in ("write", "publish"),
            "idempotentHint": self.effect == "read",
            "openWorldHint": False,
        }

    def spec(self) -> dict:
        """The provider-neutral function spec a model sees."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class ToolContext:
    user: object
    agent: object  # AgentDefinition (the run's config) — required: every principal is an agent
    run: object = None
    trigger: str = "manual"
    token: object = None
    extra: dict = field(default_factory=dict)
    on_behalf_of: object = None  # the person whose request this is; a page tool then needs their edit right too

    @property
    def policy(self) -> str:
        return self.agent.policy if self.agent is not None else POLICY_OFF


class Registry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> Tool:
        if t.effect not in EFFECTS:
            raise ValueError(f"{t.name}: effect must be one of {EFFECTS}")
        if t.name in self._tools and self._tools[t.name].fn is not t.fn:
            raise ValueError(f"tool {t.name} is registered twice")
        Draft202012Validator.check_schema(t.input_schema)
        self._tools[t.name] = t
        return t

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError("not_found", f"no tool named {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[Tool]:
        return [self._tools[n] for n in self.names()]

    # ── who may call what ──────────────────────────────────────────────────
    def refusal(self, t: Tool, ctx: ToolContext) -> ToolError | None:
        """Why `ctx` may not even see `t`, or None."""
        agent = ctx.agent
        if agent is None:
            return ToolError("not_allowed", "a tool call needs an agent")
        if t.name not in (agent.tools or []):
            return ToolError("not_allowed", f"{t.name} is not in {agent.slug}'s tools")
        if ctx.token is not None and ctx.token.tools and t.name not in ctx.token.tools:
            return ToolError("not_allowed", f"{t.name} is not in this token's tools")
        if t.effect == "publish" and agent.role == "review":
            return ToolError("not_allowed", "review agents never get publish tools")
        return None

    def for_context(self, ctx: ToolContext) -> list[Tool]:
        return [t for t in self.all() if self.refusal(t, ctx) is None]

    # ── the call ───────────────────────────────────────────────────────────
    def call(self, name: str, args: dict | None, ctx: ToolContext) -> dict:
        from .tracing import span

        args = dict(args or {})
        t = self.get(name)
        started = time.monotonic()
        step = self._open_step(ctx, t, args)
        try:
            with span(f"tool {t.name}", tool=t.name, effect=t.effect, agent=getattr(ctx.agent, "slug", None)):
                self._check(t, args, ctx)
                with transaction.atomic():
                    result = t.fn(ctx, **args)
        except ToolError as e:
            self._close_step(step, started, error=str(e), result=e.as_dict())
            raise
        except Exception as e:  # noqa: BLE001 — a tool's own failure is reported to the caller, never swallowed
            self._close_step(step, started, error=f"{type(e).__name__}: {e}")
            raise ToolError("failed", f"{type(e).__name__}: {e}") from e
        self._close_step(step, started, result=result)
        return result

    def check(self, name: str, args: dict | None, ctx: ToolContext) -> None:
        """Raise the `ToolError` a call would be refused with — every check but the rate, which only a call
        spends — without running the tool or recording a step: a surface asks before it queues work for one."""
        self._check(self.get(name), dict(args or {}), ctx, rate=False)

    def _check(self, t: Tool, args: dict, ctx: ToolContext, *, rate: bool = True):
        refusal = self.refusal(t, ctx)
        if refusal:
            raise refusal
        problems = sorted(Draft202012Validator(t.input_schema).iter_errors(args), key=lambda e: list(e.path))
        if problems:
            raise ToolError(
                "invalid_args", "; ".join(f"{'/'.join(map(str, p.path)) or '(args)'}: {p.message}" for p in problems)
            )
        if not is_agent_user(ctx.user):
            raise ToolError(
                "permission_denied", "tools run as an active agent user (agent:<slug>), never as a superuser"
            )
        page = self._target_page(t, args)
        self._check_policy(t, ctx, page)
        self._check_perms(t, ctx.user, page)
        person = ctx.on_behalf_of
        if person is not None and page is not None and not page.permissions_for_user(person).can_edit():
            raise ToolError("permission_denied", f"page {page.pk} is not one {person} may edit, and the run is theirs")
        if rate:
            self._check_rate(t, ctx.user)

    @staticmethod
    def _target_page(t: Tool, args: dict):
        if not t.page_arg or args.get(t.page_arg) is None:
            return None
        from wagtail.models import Page

        page = Page.objects.filter(pk=args[t.page_arg]).first()
        if page is None:
            raise ToolError("not_found", f"no page {args[t.page_arg]}")
        return page.specific

    @staticmethod
    def _check_policy(t: Tool, ctx: ToolContext, page):
        policy = ctx.policy
        if page is not None and hasattr(page, "effective_policy"):
            policy = page.effective_policy(policy)
        needed = MIN_POLICY[t.effect]
        if POLICY_ORDER.index(policy) < POLICY_ORDER.index(needed):
            where = f" on page {page.pk}" if page is not None else ""
            raise ToolError(
                "policy", f"{t.name} ({t.effect}) needs policy {needed}; {ctx.agent.slug} has {policy}{where}"
            )
        if t.effect in ("write", "publish") and not ctx.agent.live and ctx.trigger != "eval":
            raise ToolError(
                "policy", f"{t.effect} needs a live definition that passed its evals; {ctx.agent.slug} is not live"
            )

    @staticmethod
    def _check_perms(t: Tool, user, page):
        for perm in t.perms:
            if page is not None and perm in PAGE_PERMISSION_TESTS:
                if not getattr(page.permissions_for_user(user), PAGE_PERMISSION_TESTS[perm])():
                    raise ToolError("permission_denied", f"{user.username} lacks {perm} on page {page.pk}")
            elif not user.has_perm(perm):
                raise ToolError("permission_denied", f"{user.username} lacks {perm}")

    @staticmethod
    def _check_rate(t: Tool, user):
        if not t.rate:
            return
        count, unit = t.rate.split("/")
        window = {"s": 1, "m": 60, "h": 3600}[unit]
        key = f"zer0:rate:{user.pk}:{t.name}:{int(time.time() // window)}"
        cache.add(key, 0, timeout=window * 2)
        if cache.incr(key) > int(count):
            raise ToolError("rate_limited", f"{t.name} allows {t.rate} per agent")

    # ── steps ──────────────────────────────────────────────────────────────
    @staticmethod
    def _open_step(ctx: ToolContext, t: Tool, args: dict):
        if ctx.run is None:
            return None
        from .models import AgentStep

        return AgentStep.objects.create(
            run=ctx.run, idx=ctx.run.next_step_index(), kind=AgentStep.TOOL, name=t.name, args=args, user=ctx.user
        )

    @staticmethod
    def _close_step(step, started, result=None, error=""):
        if step is None:
            return
        step.latency_ms = int((time.monotonic() - started) * 1000)
        step.result = result if isinstance(result, dict) else {"value": result}
        step.error = error
        step.save(update_fields=["latency_ms", "result", "error"])


registry = Registry()


def tool(name: str, *, effect: str, description: str, input_schema: dict, perms=(), rate=None, page_arg=None):
    """Register `fn(ctx, **args) -> dict` as a tool."""

    def decorate(fn):
        registry.register(
            Tool(
                name=name,
                fn=fn,
                description=description,
                input_schema=input_schema,
                effect=effect,
                perms=tuple(perms),
                rate=rate,
                page_arg=page_arg,
            )
        )
        return fn

    return decorate


def obj(properties: dict, required=()) -> dict:
    """A JSON Schema object with no extra properties — the shape every tool takes."""
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}
