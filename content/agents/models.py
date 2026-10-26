"""The harness's tables (note §4).

- `AgentDefinition` — what an agent is: prompt, model, tools, policy, budget.
  A snippet with revisions and a draft/live state: editors change a draft,
  and a revision goes live only when its eval suite passes (`publish()`
  below), so the row is always the configuration that last passed.
- `AgentRun` / `AgentStep` — every run and every model call, tool call and
  human decision inside it. The run table is the checkpoint (PLAN-D3): a run
  can be inspected, resumed or replayed from its steps.
- `Memory` — scoped long-term memory that editors can read and change.
- `EvalCase` / `EvalResult` — the suite a definition must pass.
- `AgentToken` — a scoped bearer token that maps an MCP or REST caller to one
  agent user. Only a hash is stored.

`AgentRun.objects.visible_to(user)` is the one scope every surface reads runs
through (TARGET.md § Rules): REST, GraphQL and the run's event stream.

Each agent acts as its own Django user, `agent:<slug>`, in the `Agents` group
and its own `agent:<slug>` group, which holds its Wagtail page and collection
permissions (agents/principals.py). There is no superuser path.
"""

import hashlib
import secrets
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.models import DraftStateMixin, RevisionMixin

from cms.models import POLICY_CHOICES, POLICY_ORDER, POLICY_SUGGEST, stable_hash

ROLE_AUTHOR = "author"
ROLE_REVIEW = "review"
ROLE_ENRICH = "enrich"
ROLE_CHOICES = [
    (ROLE_AUTHOR, "Author — drafts and edits content"),
    (ROLE_REVIEW, "Review — passes or fails a workflow task; never publishes"),
    (ROLE_ENRICH, "Enrich — graph, media and metadata"),
]


class EvalGateError(Exception):
    """A revision that has not passed its eval suite cannot go live."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


class AgentDefinition(DraftStateMixin, RevisionMixin, models.Model):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_AUTHOR)
    system_prompt = models.TextField(blank=True)
    model = models.CharField(
        max_length=120, blank=True, help_text="A LiteLLM model id, e.g. anthropic/claude-sonnet-5-5."
    )
    tools = models.JSONField(default=list, blank=True, help_text="The tool names this agent may call.")
    policy = models.CharField(max_length=16, choices=POLICY_CHOICES, default=POLICY_SUGGEST)
    max_steps = models.PositiveSmallIntegerField(default=8)
    budget_usd = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.5000"))
    handler = models.CharField(
        max_length=200,
        blank=True,
        help_text="A dotted path to a deterministic handler; when set, the runner calls it instead of a model.",
    )
    profile = models.JSONField(default=dict, blank=True, help_text="Agent-specific settings, e.g. a book profile.")
    _revisions = GenericRelation("wagtailcore.Revision", related_query_name="agentdefinition")

    panels = [
        MultiFieldPanel([FieldPanel("slug"), FieldPanel("name"), FieldPanel("description"), FieldPanel("role")]),
        FieldPanel("system_prompt"),
        MultiFieldPanel(
            [
                FieldPanel("model"),
                FieldPanel("tools"),
                FieldPanel("policy"),
                FieldPanel("max_steps"),
                FieldPanel("budget_usd"),
                FieldPanel("handler"),
                FieldPanel("profile"),
            ],
            heading="Runtime",
        ),
    ]

    class Meta:
        ordering = ["slug"]

    def __str__(self):
        return self.slug

    @property
    def revisions(self):
        return self._revisions

    @property
    def username(self) -> str:
        return f"agent:{self.slug}"

    @property
    def user(self):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.get(username=self.username)

    @property
    def prompt_version(self) -> str:
        """Changes whenever anything that shapes the agent's output changes."""
        return stable_hash(
            {"system": self.system_prompt, "model": self.model, "tools": sorted(self.tools), "profile": self.profile}
        )[:12]

    def policy_rank(self) -> int:
        return POLICY_ORDER.index(self.policy)

    def publish(self, revision, *args, skip_eval_gate=False, **kwargs):
        """Go live with `revision` only if its eval suite passed (M14)."""
        if not skip_eval_gate:
            from .evals import gate

            result = gate(self, revision)
            if not result.passed:
                raise EvalGateError(result.reasons)
        return super().publish(revision, *args, **kwargs)


class AgentRunQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The runs `user` may read: every run for a superuser, its own runs
        for an agent user, and for a person the runs they started and the runs
        whose suggestions they may decide — a reviewer reads the run behind
        what they review."""
        from suggestions.models import Suggestion

        if user is None or not user.is_authenticated or not user.is_active:
            return self.none()
        if user.is_superuser:
            return self
        if user.username.startswith("agent:"):
            return self.filter(agent__slug=user.username.removeprefix("agent:"))
        reviewed = Suggestion.objects.visible_to(user).filter(run__isnull=False).values("run_id")
        return self.filter(models.Q(started_by=user) | models.Q(pk__in=reviewed))


class AgentRun(models.Model):
    QUEUED, RUNNING, WAITING, SUCCEEDED, FAILED, REFUSED, CANCELLED = (
        "queued",
        "running",
        "waiting",
        "succeeded",
        "failed",
        "refused",
        "cancelled",
    )
    STATUS_CHOICES = [(s, s) for s in (QUEUED, RUNNING, WAITING, SUCCEEDED, FAILED, REFUSED, CANCELLED)]
    FINAL = (SUCCEEDED, FAILED, REFUSED, CANCELLED)
    TRIGGERS = ["manual", "graphql", "rest", "mcp", "workflow", "event", "schedule", "eval", "import"]

    agent = models.ForeignKey(AgentDefinition, on_delete=models.PROTECT, related_name="runs")
    revision = models.ForeignKey(
        "wagtailcore.Revision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="The definition revision this run used.",
    )
    trigger = models.CharField(max_length=16, choices=[(t, t) for t in TRIGGERS])
    target_ct = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    target = GenericForeignKey("target_ct", "target_id")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=QUEUED, db_index=True)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    tokens = models.PositiveIntegerField(default=0)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    started_by_event = models.CharField(max_length=64, blank=True)
    parent_run = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    trace_id = models.CharField(max_length=32, blank=True, db_index=True)
    schema_version = models.CharField(max_length=16, blank=True, help_text="The exported block schema the run saw.")
    prompt_version = models.CharField(max_length=12, blank=True)
    llm_backend = models.CharField(max_length=32, blank=True)
    legacy_ref = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = AgentRunQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.agent.slug} run {self.pk} ({self.status})"

    @property
    def is_final(self) -> bool:
        return self.status in self.FINAL

    def config(self) -> AgentDefinition:
        """The definition as this run sees it: its pinned revision, else live."""
        if self.revision_id:
            return self.revision.as_object()
        return self.agent

    def next_step_index(self) -> int:
        last = self.steps.order_by("-idx").values_list("idx", flat=True).first()
        return 0 if last is None else last + 1

    def finish(self, status, output=None, error=""):
        self.status = status
        if output is not None:
            # Merged, not replaced: a tool (review.submit_verdict) may already
            # have recorded part of the outcome on the run.
            self.output = {**(self.output or {}), **output}
        self.error = error
        self.finished_at = timezone.now()


class AgentStep(models.Model):
    LLM, TOOL, HUMAN = "llm", "tool", "human"
    KIND_CHOICES = [(k, k) for k in (LLM, TOOL, HUMAN)]

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    idx = models.PositiveIntegerField()
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    name = models.CharField(max_length=120)
    args = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["run", "idx"]
        constraints = [models.UniqueConstraint(fields=["run", "idx"], name="one_step_per_index")]

    def __str__(self):
        return f"{self.run_id}#{self.idx} {self.kind}:{self.name}"


class Memory(models.Model):
    SCOPES = ["global", "site", "section", "page", "user", "agent"]

    scope = models.CharField(max_length=16, choices=[(s, s) for s in SCOPES])
    scope_id = models.CharField(max_length=64, blank=True)
    key = models.CharField(max_length=120)
    value = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_by_run = models.ForeignKey(AgentRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "memories"
        constraints = [models.UniqueConstraint(fields=["scope", "scope_id", "key"], name="one_memory_per_key")]

    def __str__(self):
        return f"{self.scope}:{self.scope_id}:{self.key}"


class EvalCase(models.Model):
    agent = models.ForeignKey(AgentDefinition, on_delete=models.CASCADE, related_name="eval_cases")
    name = models.SlugField(max_length=80)
    input = models.JSONField(default=dict, blank=True)
    checks = models.JSONField(default=list, blank=True, help_text="The rubric: a list of {check: …} mappings.")
    tags = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["agent", "name"]
        constraints = [models.UniqueConstraint(fields=["agent", "name"], name="one_case_name_per_agent")]

    def __str__(self):
        return f"{self.agent.slug}/{self.name}"


class EvalResult(models.Model):
    case = models.ForeignKey(EvalCase, on_delete=models.CASCADE, related_name="results")
    revision = models.ForeignKey(
        "wagtailcore.Revision", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    run = models.ForeignKey(AgentRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    score = models.FloatField(default=0.0)
    passed = models.BooleanField(default=False)
    details = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class AgentToken(models.Model):
    """`Authorization: Bearer zer0_<…>` → one agent user. The raw token is
    shown once, at issue time."""

    name = models.CharField(max_length=120)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_tokens")
    prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    tools = models.JSONField(
        default=list, blank=True, help_text="If set, the only tools this token may call (narrows the agent's own list)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def digest(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, user, name: str, tools=None) -> tuple["AgentToken", str]:
        if not user.username.startswith("agent:") or user.is_superuser:
            raise ValueError("tokens are issued to agent users only")
        raw = "zer0_" + secrets.token_urlsafe(32)
        token = cls.objects.create(name=name, user=user, prefix=raw[:12], key_hash=cls.digest(raw), tools=tools or [])
        return token, raw

    @classmethod
    def authenticate(cls, raw: str):
        token = cls.objects.select_related("user").filter(key_hash=cls.digest(raw), revoked_at__isnull=True).first()
        if token is None or not token.user.is_active:
            return None
        cls.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token
