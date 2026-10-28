"""The AI API's shapes (`/api/v2/ai/`).

Rows are addressed by their UUID public id (`id`), never by their integer key —
an agent run too (`RunRefSerializer`, P-D6); a related row is named by its public id too, and only a row the requester may
see can be named (`Visible`). A provider is named by its slug, a page and a
site by Wagtail's own ids. A provider's credential is write-only: it goes in,
is encrypted, and only `has_credential` ever comes back; changing the base URL
without sending a credential drops the stored one, since it was entered for the
old host. A provider's configuration (base URL, organization, project, `extra`,
the health check's details) is shown only to people who configure providers.
Validation is the models' own (`clean()`), so the API, the importer and a shell
agree.
"""

import copy
import os

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.fields import get_error_detail
from wagtail.models import Page, Site

from api.serializers import RunLinksSerializer

from . import providers
from .models import (
    Assistant,
    Brief,
    Conversation,
    Message,
    ModelEntry,
    OutputSchema,
    Pipeline,
    PipelineStep,
    ProviderConfig,
)


class Visible(serializers.SlugRelatedField):
    """A related row by public id, out of the rows the requester may see."""

    def __init__(self, model, **kwargs):
        self.model = model
        super().__init__(slug_field="public_id", queryset=model.objects.all(), **kwargs)

    def get_queryset(self):
        request = self.context.get("request")
        return self.model.objects.visible_to(getattr(request, "user", None))


def _clean(model, instance, attrs):
    """Run the model's own validation over the instance as it would be saved."""
    candidate = copy.copy(instance) if instance is not None else model()
    for key, value in attrs.items():
        setattr(candidate, key, value)
    try:
        candidate.clean()
    except DjangoValidationError as e:
        raise serializers.ValidationError(get_error_detail(e)) from e


# ── runs ───────────────────────────────────────────────────────────────────


class RunRefSerializer(serializers.Serializer):
    """An agent run to follow on the existing runs API, by its public id."""

    id = serializers.UUIDField(source="public_id")
    status = serializers.CharField()
    links = serializers.SerializerMethodField()

    @extend_schema_field(RunLinksSerializer)
    def get_links(self, run):
        return run.links


class RunAcceptedSerializer(serializers.Serializer):
    run = RunRefSerializer()


# ── providers and models ───────────────────────────────────────────────────

CONFIGURATION = ("base_url", "organization", "project", "extra")  # and last_health's details


class ProviderSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    credential = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={"input_type": "password"},
        help_text="Write-only; encrypted at rest. An empty string removes it (the environment is used again).",
    )
    has_credential = serializers.BooleanField(read_only=True)
    credential_source = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = ProviderConfig
        fields = [
            "id",
            "slug",
            "display_name",
            "enabled",
            "is_default",
            "base_url",
            "organization",
            "project",
            "default_model",
            "extra",
            "monthly_budget_usd",
            "credential",
            "has_credential",
            "credential_source",
            "capabilities",
            "last_health",
            "checked_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["slug", "is_default", "last_health", "checked_at", "created_at", "updated_at"]
        extra_kwargs = {
            "extra": {"help_text": "The adapter's options (its declared keys only). Shown to those who configure."},
            "base_url": {"help_text": "Shown to those who configure; a row with its own needs its own credential."},
            "organization": {"help_text": "Shown to those who configure providers."},
            "project": {"help_text": "Shown to those who configure providers."},
            "last_health": {"help_text": "The last check; only `ok` for those who do not configure providers."},
        }

    def get_credential_source(self, row) -> str:
        """`database`, the environment variable the adapter would read, or ''."""
        if row.has_credential:
            return "database"
        try:
            names = providers.provider_class(row.slug).credential_env
        except (ImportError, providers.ProviderError):
            return ""
        return next((name for name in names if os.environ.get(name)), "")

    def get_capabilities(self, row) -> list[str]:
        try:
            return sorted(providers.provider_class(row.slug).capabilities)
        except (ImportError, providers.ProviderError):
            return []

    def validate(self, attrs):
        if self.instance is not None and self.instance.is_default and attrs.get("enabled") is False:
            raise serializers.ValidationError({"enabled": "the default provider stays enabled; choose another first"})
        _clean(ProviderConfig, self.instance, {k: v for k, v in attrs.items() if k != "credential"})
        return attrs

    def update(self, instance, validated_data):
        if "credential" in validated_data:
            instance.set_credential(validated_data.pop("credential"))
        elif validated_data.get("base_url", instance.base_url) != instance.base_url:
            instance.set_credential("")
        return super().update(instance, validated_data)

    def to_representation(self, row):
        data = super().to_representation(row)
        user = getattr(self.context.get("request"), "user", None)
        if user is None or not user.has_perm("ai.change_providerconfig"):
            for key in CONFIGURATION:
                data.pop(key, None)
            data["last_health"] = {"ok": row.last_health["ok"]} if "ok" in (row.last_health or {}) else {}
        return data


class ModelEntrySerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    provider = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = ModelEntry
        fields = [
            "id",
            "provider",
            "model_id",
            "display_name",
            "description",
            "capabilities",
            "input_usd_per_mtok",
            "output_usd_per_mtok",
            "active",
            "synced_at",
        ]
        read_only_fields = fields


# ── owned rows ─────────────────────────────────────────────────────────────

OWNED = ["id", "owner", "site", "visibility", "can_edit", "created_at", "updated_at"]


class OwnedSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    owner = serializers.CharField(source="owner.username", read_only=True, allow_null=True)
    site = serializers.PrimaryKeyRelatedField(
        queryset=Site.objects.all(), allow_null=True, required=False, help_text="A site its owner edits."
    )
    can_edit = serializers.SerializerMethodField()

    def get_can_edit(self, row) -> bool:
        """Whether the requester may change or delete the row (its owner, or staff)."""
        return row.can_edit(getattr(self.context.get("request"), "user", None))

    def validate(self, attrs):
        # A new row is the requester's: its owner is known before it is saved, for the rules that need it.
        owner = {"owner": getattr(self.context.get("request"), "user", None)} if self.instance is None else {}
        _clean(self.Meta.model, self.instance, {**owner, **{k: v for k, v in attrs.items() if k != "steps"}})
        return attrs


class OutputSchemaSerializer(OwnedSerializer):
    class Meta:
        model = OutputSchema
        fields = [*OWNED, "name", "description", "schema", "version", "render_template", "bundled"]
        read_only_fields = ["version", "bundled", "created_at", "updated_at"]


class OutputSchemaExportSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutputSchema
        fields = ["name", "description", "version", "schema", "render_template"]


class BundledImportSerializer(serializers.Serializer):
    schemas = serializers.ListField(child=serializers.UUIDField())
    assistants = serializers.ListField(child=serializers.UUIDField())


class AssistantSerializer(OwnedSerializer):
    provider = serializers.SlugRelatedField(
        slug_field="slug", queryset=ProviderConfig.objects.all(), allow_null=True, required=False
    )
    model = Visible(ModelEntry, allow_null=True, required=False)
    output_schema = Visible(OutputSchema, allow_null=True, required=False)
    effect = serializers.SerializerMethodField()

    class Meta:
        model = Assistant
        fields = [
            *OWNED,
            "name",
            "description",
            "instructions",
            "prompt_template",
            "provider",
            "model",
            "params",
            "output_schema",
            "tools",
            "effect",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_effect(self, assistant) -> str:
        """Always `propose`: an assistant's results are reviewed, never written."""
        return Assistant.EFFECT


class PipelineStepSerializer(serializers.ModelSerializer):
    assistant = Visible(Assistant)

    class Meta:
        model = PipelineStep
        fields = ["position", "assistant", "source", "source_field"]
        read_only_fields = ["position"]


class PipelineSerializer(OwnedSerializer):
    steps = PipelineStepSerializer(many=True, required=False, help_text="In order; replaced as a whole on update.")

    class Meta:
        model = Pipeline
        fields = [*OWNED, "name", "description", "steps"]
        read_only_fields = ["created_at", "updated_at"]

    def create(self, validated_data):
        steps = validated_data.pop("steps", [])
        pipeline = super().create(validated_data)
        self._steps(pipeline, steps)
        return pipeline

    def update(self, instance, validated_data):
        steps = validated_data.pop("steps", None)
        pipeline = super().update(instance, validated_data)
        if steps is not None:
            self._steps(pipeline, steps)
        return pipeline

    @staticmethod
    def _steps(pipeline, steps):
        pipeline.steps.all().delete()
        PipelineStep.objects.bulk_create(
            PipelineStep(pipeline=pipeline, position=i, **step) for i, step in enumerate(steps, start=1)
        )


class BriefSerializer(OwnedSerializer):
    assistant = Visible(Assistant, allow_null=True, required=False)
    pipeline = Visible(Pipeline, allow_null=True, required=False)
    output_schema = Visible(OutputSchema, allow_null=True, required=False)
    conversation = Visible(Conversation, allow_null=True, required=False)
    parent = serializers.PrimaryKeyRelatedField(queryset=Page.objects.all(), allow_null=True, required=False)
    page = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True, help_text="The draft it made.")
    source_message = serializers.SlugRelatedField(slug_field="public_id", read_only=True, allow_null=True)
    run = RunRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Brief
        fields = [
            *OWNED,
            "title",
            "prompt",
            "source_text",
            "assistant",
            "pipeline",
            "output_schema",
            "page_type",
            "parent",
            "status",
            "result",
            "markdown",
            "metadata",
            "page",
            "run",
            "error",
            "conversation",
            "source_message",
            "applied_at",
        ]
        read_only_fields = ["status", "result", "error", "applied_at", "created_at", "updated_at"]

    def validate(self, attrs):
        if self.instance is not None and self.instance.status in (Brief.GENERATING, Brief.APPLIED):
            raise serializers.ValidationError(f"the brief is {self.instance.status}; it cannot change now")
        return super().validate(attrs)


class ConversationSerializer(OwnedSerializer):
    assistant = Visible(Assistant, allow_null=True, required=False)
    pipeline = Visible(Pipeline, allow_null=True, required=False)
    page = serializers.PrimaryKeyRelatedField(queryset=Page.objects.all(), allow_null=True, required=False)
    from_brief = Visible(
        Brief, write_only=True, required=False, help_text="On create: start from this brief's text, its first turn."
    )

    class Meta:
        model = Conversation
        fields = [*OWNED, "title", "assistant", "pipeline", "page", "from_brief"]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        brief = attrs.pop("from_brief", None)
        attrs = super().validate(attrs)
        if brief is not None and self.instance is None:
            attrs["from_brief"] = brief
        return attrs


class MessageSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    conversation = serializers.SlugRelatedField(slug_field="public_id", read_only=True)
    assistant = Visible(Assistant, allow_null=True, required=False)
    run = RunRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "conversation",
            "seq",
            "role",
            "text",
            "result",
            "assistant",
            "run",
            "status",
            "provider",
            "model",
            "usage",
            "error",
            "created_at",
        ]
        read_only_fields = [f for f in fields if f != "assistant"]


# ── the actions' requests and responses ────────────────────────────────────


class SchemaDocumentSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    schema = serializers.JSONField()
    render_template = serializers.CharField(required=False, allow_blank=True, default="")


class AssistantDocumentSerializer(serializers.Serializer):
    """An assistant as a portable document (export, import)."""

    name = serializers.CharField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True)
    instructions = serializers.CharField(required=False, allow_blank=True)
    prompt_template = serializers.CharField(required=False, allow_blank=True)
    params = serializers.JSONField(required=False)
    tools = serializers.ListField(child=serializers.CharField(), required=False)
    provider = serializers.CharField(allow_null=True, required=False, help_text="A provider's slug.")
    model = serializers.CharField(allow_null=True, required=False, help_text="The provider's model id.")
    output_schema = SchemaDocumentSerializer(allow_null=True, required=False)


class OnPageSerializer(serializers.Serializer):
    """A run on a page whose answer lands there as suggestions (`suggest`)."""

    page_id = serializers.IntegerField(required=False, help_text="A page the run may read, which you can edit.")
    suggest = serializers.BooleanField(
        default=False,
        help_text="Propose the answer on the page (`page_id`) as suggestions to accept or reject: in place of "
        "`block_id`, or as new blocks at the end. The run reads that block, else the whole page.",
    )
    block_id = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="With `suggest`: the block it reads and replaces."
    )
    selection = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=50_000,
        help_text="With `block_id`: text in that block, as saved and as a person sees it (a paragraph's without its "
        "markup), that it reads and whose place its answer takes — only that text changes.",
    )
    field = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="With `selection` in a structured block: the field it is in (`text` of a heading, `code` of a code "
        "block); else any of its text fields.",
    )
    selection_start = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="With `selection`: the character it starts at in that text (code points, a paragraph's counted "
        "without its markup). Without it, the selection must appear in the block exactly once.",
    )

    def validate(self, attrs):
        if attrs["suggest"] and attrs.get("page_id") is None:
            raise serializers.ValidationError({"page_id": "suggestions land on a page: name it"})
        if (attrs["block_id"] or attrs["selection"]) and not attrs["suggest"]:
            raise serializers.ValidationError({"suggest": "a block or a selection is for a run that suggests"})
        if (attrs.get("field") or attrs.get("selection_start") is not None) and not attrs["selection"]:
            raise serializers.ValidationError({"selection": "a field or a start says where a selection is: send it"})
        return attrs


class RunAssistantSerializer(OnPageSerializer):
    prompt = serializers.CharField(max_length=50_000)


class RunPipelineSerializer(OnPageSerializer):
    prompt = serializers.CharField(max_length=50_000, required=False, allow_blank=True, default="")


class ConversationPipelineSerializer(serializers.Serializer):
    prompt = serializers.CharField(max_length=50_000, required=False, allow_blank=True, default="")


class ToolSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField()


class BriefRunSerializer(serializers.Serializer):
    brief = BriefSerializer()
    run = RunRefSerializer(allow_null=True)


class ApplyBriefSerializer(serializers.Serializer):
    parent = serializers.IntegerField(required=False, help_text="Where the draft goes; else the brief's parent.")
    page_type = serializers.CharField(required=False, help_text="e.g. cms.ArticlePage; else the brief's.")


class AppliedBriefSerializer(serializers.Serializer):
    brief = BriefSerializer()
    page_id = serializers.IntegerField(help_text="The draft page (not live).")
    suggestions = serializers.ListField(child=serializers.UUIDField(), help_text="To accept on the draft.")


class PostMessageSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=50_000)
    assistant = serializers.UUIDField(required=False, help_text="Who replies; else the conversation's assistant.")
    answer = serializers.BooleanField(default=True, help_text="Queue a reply (when there is an assistant).")


class MessagePostedSerializer(serializers.Serializer):
    message = MessageSerializer()
    reply = MessageSerializer(allow_null=True)
    run = RunRefSerializer(allow_null=True)


class MessageRunSerializer(serializers.Serializer):
    message = MessageSerializer()
    run = RunRefSerializer()


class RerunSerializer(serializers.Serializer):
    assistant = serializers.UUIDField(required=False)


class PromoteSerializer(serializers.Serializer):
    to = serializers.ChoiceField(choices=["brief", "draft"])
    parent = serializers.IntegerField(required=False)
    page_type = serializers.CharField(required=False)
