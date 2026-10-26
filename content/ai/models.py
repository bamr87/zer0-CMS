"""The AI content layer's tables, rebuilt from barodybroject's model to the
platform's rules (TARGET.md § The AI content layer, § Rules that keep models
and views manageable).

| barodybroject                     | here                                        |
|-----------------------------------|---------------------------------------------|
| `AIProviderConfig`                | `ProviderConfig` (credential encrypted, write-only, one default by constraint) |
| `AIModel`                         | `ModelEntry` (synced from the provider)     |
| `JSONSchema`, the bundled schemas | `OutputSchema` (validated as a schema, versioned, with a render template) |
| `Assistant`                       | `Assistant` (persona; propose-only)         |
| `AssistantGroup` + memberships    | `Pipeline` + `PipelineStep`                 |
| `ContentDetail` + `ContentItem`   | `Brief` (prompt → structured result → draft) |
| `Thread` + `Message`              | `Conversation` + `Message`                  |

Every row has a UUID `public_id` (the integer key stays internal) and every
owned row carries `owner`, `site` and `visibility`; `visible_to(user, site)` is
the one place rows are scoped, and every view, tool and service uses it —
`usable(row, user)` asks it again when a run executes, since what a person
could see when they asked may have changed by then. A row belongs only to a
site its owner edits.
Generation itself is an `agents.AgentRun` (ai/handlers.py), so its cost,
tokens, steps and trace live where every other run's do.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from jsonschema import Draft202012Validator, SchemaError, validators

from . import crypto, rendering
from .providers.base import EFFORT, NotConfigured

USER = settings.AUTH_USER_MODEL
PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "temperature": {"type": "number", "minimum": 0, "maximum": 2},
        "top_p": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "max_tokens": {"type": "integer", "minimum": 1, "maximum": 128000},
        "effort": EFFORT,
    },
    "additionalProperties": False,
}
REFS = ("$ref", "$dynamicRef", "$recursiveRef")


def first_error(schema: dict, data) -> str:
    """The first way `data` fails `schema` (a fixed schema of ours), or ''."""
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    return f"{'/'.join(map(str, errors[0].path)) or '(root)'}: {errors[0].message}" if errors else ""


class Visibility(models.TextChoices):
    PRIVATE = "private", "Private — its owner"
    SITE = "site", "Site — everyone who edits its site"
    SHARED = "shared", "Shared — everyone signed in"


def is_staff(user) -> bool:
    return bool(user is not None and user.is_authenticated and (user.is_staff or user.is_superuser))


def sites_for(user) -> list[int]:
    """The sites `user` edits: a page permission on the site's root, an
    ancestor of it, or a page inside it."""
    from wagtail.models import GroupPagePermission, Site

    paths = set(GroupPagePermission.objects.filter(group__user=user).values_list("page__path", flat=True))
    return [
        site.pk
        for site in Site.objects.select_related("root_page")
        if any(site.root_page.path.startswith(p) or p.startswith(site.root_page.path) for p in paths)
    ]


class OwnedQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        """What `user` may see: their own rows, shared ones, and site rows of the
        sites they edit; staff see everything. With `site`, that site's rows and
        rows that belong to no site."""
        if user is None or not user.is_authenticated:
            return self.none()
        rows = self if site is None else self.filter(Q(site=site) | Q(site__isnull=True))
        if is_staff(user):
            return rows
        return rows.filter(
            Q(owner=user) | Q(visibility=Visibility.SHARED) | Q(visibility=Visibility.SITE, site__in=sites_for(user))
        )


def usable(row, user) -> bool:
    """Whether `user` may use `row` (an assistant, a pipeline, a schema …) now: `visible_to` asked again."""
    return row is None or type(row).objects.visible_to(user).filter(pk=row.pk).exists()


class Owned(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    site = models.ForeignKey("wagtailcore.Site", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    visibility = models.CharField(max_length=8, choices=Visibility.choices, default=Visibility.PRIVATE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        abstract = True

    def clean(self):
        if self.visibility == Visibility.SITE and self.site_id is None:
            raise ValidationError({"visibility": "site visibility needs a site"})
        owner = self.owner if self.owner_id else None
        if (
            self.site_id is not None
            and owner is not None
            and not is_staff(owner)
            and self.site_id not in sites_for(owner)
        ):
            raise ValidationError({"site": "a row belongs only to a site its owner edits"})

    def can_edit(self, user) -> bool:
        return is_staff(user) or (self.owner_id is not None and self.owner_id == getattr(user, "pk", None))


# ── providers and models ───────────────────────────────────────────────────


class ProviderQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        """Every signed-in person sees the providers (never a credential)."""
        return self if user is not None and user.is_authenticated else self.none()


class ProviderConfig(models.Model):
    """One row per registered adapter (ai/providers/). The credential is
    encrypted at rest and never leaves through the API; without one the
    adapter falls back to its environment variables."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    slug = models.SlugField(max_length=40, unique=True, help_text="The adapter's key in the provider registry.")
    display_name = models.CharField(max_length=120, blank=True)
    enabled = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    base_url = models.CharField(max_length=255, blank=True)
    organization = models.CharField(max_length=255, blank=True)
    project = models.CharField(max_length=255, blank=True)
    default_model = models.CharField(max_length=255, blank=True)
    extra = models.JSONField(default=dict, blank=True, help_text="Adapter options (effort, max_turns, timeout, …).")
    monthly_budget_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Refuse new runs once spent this month."
    )
    credential_encrypted = models.TextField(blank=True, editable=False)
    last_health = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProviderQuerySet.as_manager()

    class Meta:
        ordering = ["-is_default", "slug"]
        constraints = [
            models.UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="ai_one_default_provider")
        ]

    def __str__(self):
        return self.display_name or self.slug

    def clean(self):
        from . import providers

        if self.slug not in providers.available():
            raise ValidationError({"slug": f"no adapter {self.slug!r} in the provider registry"})
        if self.is_default and not self.enabled:
            raise ValidationError({"is_default": "the default provider must be enabled"})
        problem = first_error(providers.provider_class(self.slug).options_schema(), self.extra or {})
        if problem:
            raise ValidationError({"extra": problem})

    @property
    def has_credential(self) -> bool:
        return bool(self.credential_encrypted)

    def set_credential(self, raw: str) -> None:
        self.credential_encrypted = crypto.encrypt(raw or "")

    def get_credential(self) -> str:
        try:
            return crypto.decrypt(self.credential_encrypted)
        except crypto.InvalidToken as e:
            raise NotConfigured(
                f"the {self.slug} credential was encrypted with a key that is gone: add that key to AI_CREDENTIAL_KEYS "
                "(or its SECRET_KEY to SECRET_KEY_FALLBACKS) and run manage.py rotate_ai_credentials, or set it again",
                provider=self.slug,
            ) from e

    def settings(self):
        """The adapter's configuration: this row, its credential and the catalog's prices."""
        from .providers import Settings

        prices = {
            m.model_id: (m.input_usd_per_mtok, m.output_usd_per_mtok)
            for m in self.models.filter(active=True)
            if m.input_usd_per_mtok is not None or m.output_usd_per_mtok is not None
        }
        return Settings(
            slug=self.slug,
            credential=self.get_credential(),
            base_url=self.base_url,
            organization=self.organization,
            project=self.project,
            default_model=self.default_model,
            extra=dict(self.extra or {}),
            prices=prices,
        )


class ModelQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        return self.filter(provider__in=ProviderConfig.objects.visible_to(user, site))


class ModelEntry(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    provider = models.ForeignKey(ProviderConfig, on_delete=models.CASCADE, related_name="models")
    model_id = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    capabilities = models.JSONField(
        default=dict, blank=True, help_text="structured_output, tools, vision, web_search, context."
    )
    input_usd_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    output_usd_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    active = models.BooleanField(default=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ModelQuerySet.as_manager()

    class Meta:
        ordering = ["provider__slug", "model_id"]
        constraints = [models.UniqueConstraint(fields=["provider", "model_id"], name="ai_one_model_per_provider")]
        indexes = [models.Index(fields=["provider", "active"])]

    def __str__(self):
        return f"{self.provider.slug}:{self.model_id}"


# ── what assistants produce ────────────────────────────────────────────────


def _refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from [value] if key in REFS and isinstance(value, str) else _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def check_json_schema(schema) -> None:
    """A valid JSON Schema that refers only to itself: a `$ref` elsewhere would
    have the worker fetch it (a URL inside the network, say) while validating."""
    if not isinstance(schema, dict):
        raise ValidationError({"schema": "a JSON Schema is an object"})
    try:
        validators.validator_for(schema, default=Draft202012Validator).check_schema(schema)
    except SchemaError as e:
        raise ValidationError({"schema": f"not a valid JSON Schema: {e.message}"}) from e
    elsewhere = next((ref for ref in _refs(schema) if not ref.startswith("#")), None)
    if elsewhere is not None:
        raise ValidationError({"schema": f"a schema refers only to itself ('#/…'), not to {elsewhere!r}"})


class OutputSchema(Owned):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    schema = models.JSONField(help_text="The JSON Schema a result must match.")
    version = models.PositiveIntegerField(default=1, editable=False)
    render_template = models.TextField(
        blank=True, help_text="A Django template that turns a result into Markdown; empty renders generically."
    )
    bundled = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        check_json_schema(self.schema)
        rendering.check(self.render_template)

    def save(self, *args, **kwargs):
        """Validate the schema and the template; a changed schema is a new version."""
        check_json_schema(self.schema)
        rendering.check(self.render_template)
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values_list("schema", flat=True).first()
            if old is not None and old != self.schema:
                self.version += 1
        super().save(*args, **kwargs)

    def to_markdown(self, data) -> str:
        return rendering.to_markdown(data, self.render_template)


class Assistant(Owned):
    """A persona a person manages. Its effect is `propose`: what it produces is
    a result someone reviews — a brief, a message — never a write."""

    EFFECT = "propose"

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    instructions = models.TextField(blank=True, help_text="The system prompt.")
    prompt_template = models.TextField(blank=True, help_text="A Django template around the request: {{ prompt }}.")
    provider = models.ForeignKey(ProviderConfig, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    model = models.ForeignKey(ModelEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    params = models.JSONField(default=dict, blank=True, help_text="temperature, top_p, max_tokens, effort.")
    output_schema = models.ForeignKey(
        OutputSchema, null=True, blank=True, on_delete=models.SET_NULL, related_name="assistants"
    )
    tools = models.JSONField(default=list, blank=True, help_text="Read-only registry tools it may use.")

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        from agents.registry import registry

        problem = first_error(PARAMS_SCHEMA, self.params or {})
        if problem:
            raise ValidationError({"params": problem})
        readable = {t.name for t in registry.all() if t.effect == "read"}
        if not isinstance(self.tools, list) or not set(self.tools) <= readable:
            raise ValidationError(
                {"tools": f"an assistant may only use read-only tools: {', '.join(sorted(readable))}"}
            )
        if self.model_id and self.provider_id and self.model.provider_id != self.provider_id:
            raise ValidationError({"model": "the model belongs to another provider"})
        rendering.check(self.prompt_template)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Pipeline(Owned):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class PipelineStep(models.Model):
    PREVIOUS, CONVERSATION, BRIEF, PAGE = "previous", "conversation", "brief", "page"
    SOURCES = [
        (PREVIOUS, "The previous step's output (the request, for the first)"),
        (CONVERSATION, "The whole conversation, or the run so far"),
        (BRIEF, "The brief's prompt"),
        (PAGE, "A field of the page the run is about"),
    ]

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE, related_name="steps")
    position = models.PositiveSmallIntegerField()
    assistant = models.ForeignKey(Assistant, on_delete=models.PROTECT, related_name="pipeline_steps")
    source = models.CharField(max_length=16, choices=SOURCES, default=PREVIOUS)
    source_field = models.CharField(max_length=64, blank=True, help_text="For source=page: the field to read.")

    class Meta:
        ordering = ["pipeline", "position"]
        constraints = [models.UniqueConstraint(fields=["pipeline", "position"], name="ai_one_step_per_position")]

    def __str__(self):
        return f"{self.pipeline} #{self.position}: {self.assistant}"


# ── briefs and conversations ───────────────────────────────────────────────


class Brief(Owned):
    """A request to create: a prompt (or a text) → a structured result rendered
    to Markdown, with extracted metadata → a draft page, through suggestions."""

    DRAFT, GENERATING, READY, APPLIED, FAILED = "draft", "generating", "ready", "applied", "failed"
    STATUSES = [(s, s) for s in (DRAFT, GENERATING, READY, APPLIED, FAILED)]

    title = models.CharField(max_length=255, blank=True)
    prompt = models.TextField(blank=True)
    source_text = models.TextField(blank=True, help_text="A text to turn into content as it is (metadata only).")
    assistant = models.ForeignKey(Assistant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    pipeline = models.ForeignKey(Pipeline, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    output_schema = models.ForeignKey(OutputSchema, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    page_type = models.CharField(max_length=80, default="cms.ArticlePage")
    parent = models.ForeignKey("wagtailcore.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=12, choices=STATUSES, default=DRAFT, db_index=True)
    result = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    markdown = models.TextField(blank=True)
    metadata = models.JSONField(
        default=dict, blank=True, help_text="title, slug, description, keywords, tags (and what else it found)."
    )
    page = models.ForeignKey("wagtailcore.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    run = models.ForeignKey("agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    error = models.TextField(blank=True)
    conversation = models.ForeignKey(
        "Conversation", null=True, blank=True, on_delete=models.SET_NULL, related_name="briefs"
    )
    source_message = models.ForeignKey("Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title or self.prompt[:60] or str(self.public_id)


class Conversation(Owned):
    title = models.CharField(max_length=200, default="New conversation")
    assistant = models.ForeignKey(
        Assistant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", help_text="Who replies."
    )
    pipeline = models.ForeignKey(Pipeline, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    page = models.ForeignKey(
        "wagtailcore.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", help_text="About."
    )

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return self.title


class MessageQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        return self.filter(conversation__in=Conversation.objects.visible_to(user, site))


class Message(models.Model):
    USER, ASSISTANT, SYSTEM = "user", "assistant", "system"
    ROLES = [(r, r) for r in (USER, ASSISTANT, SYSTEM)]
    QUEUED, RUNNING, COMPLETED, FAILED = "queued", "running", "completed", "failed"
    STATUSES = [(s, s) for s in (QUEUED, RUNNING, COMPLETED, FAILED)]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    seq = models.PositiveIntegerField()
    role = models.CharField(max_length=12, choices=ROLES, default=USER)
    text = models.TextField(blank=True)
    result = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    assistant = models.ForeignKey(Assistant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    run = models.ForeignKey("agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=12, choices=STATUSES, default=COMPLETED, db_index=True)
    provider = models.CharField(max_length=40, blank=True)
    model = models.CharField(max_length=255, blank=True)
    usage = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MessageQuerySet.as_manager()

    class Meta:
        ordering = ["conversation", "seq"]
        constraints = [models.UniqueConstraint(fields=["conversation", "seq"], name="ai_one_message_per_seq")]

    def __str__(self):
        return f"{self.conversation_id}#{self.seq} {self.role}"

    def can_edit(self, user) -> bool:
        return self.conversation.can_edit(user)


# ── idempotent run creation ────────────────────────────────────────────────


class IdempotencyKey(models.Model):
    """The response a run-creating request got, replayed when the same person
    sends the same `Idempotency-Key` to the same endpoint within a day."""

    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=255)
    scope = models.CharField(max_length=255, help_text="METHOD path")
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    response = models.JSONField(encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key", "scope"], name="ai_one_response_per_key")]
