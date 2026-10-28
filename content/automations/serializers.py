"""The automations API's shapes (`/api/v2/automations/`).

An automation is the AI layer's owned row (`ai.serializers.OwnedSerializer`: its public id as `id`, owner, site,
visibility, `can_edit`), validated by the model's own `clean()`, so the API, an import and a shell agree. Its trigger
and its actions are JSON whose OpenAPI description is `spec.py`'s schemas, so the generated client types them as
unions by `kind`. It is made paused (`enabled` is read-only: `enable/` and `disable/` change it), and its secret is in
the answer that made it — or a new one, from `rotate-secret/` — and never again; its last run is shown only to whom
its runs are (`Automation.shows_runs_to`). Every name here starts with `Automation`, since drf-spectacular names a
component after its serializer.
"""

from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ai.serializers import OWNED, OwnedSerializer

from . import spec
from .models import Automation, AutomationRun

OUTCOME = {
    "type": "object",
    "properties": {
        "index": {"type": "integer", "description": "The action's place in the list, from 0."},
        "kind": {"type": "string"},
        "status": {"enum": ["succeeded", "failed", "not_run"]},
        "input": {**spec.OBJECT, "description": "What it was asked: its templates rendered against the payload."},
        "result": {
            "type": "object",
            "description": "What it made: an agent run's id (`run`), a brief, an idea or a story by public id (and the "
            "story's new status), an email's recipients, a webhook's HTTP status.",
            "properties": {
                "run": {"type": "integer"},
                "brief": {"type": "string", "format": "uuid"},
                "idea": {"type": "string", "format": "uuid"},
                "story": {"type": "string", "format": "uuid"},
                "status": {"type": "string"},
                "http_status": {"type": "integer"},
                "to": {"type": "array", "items": {"type": "string"}},
                "sent": {"type": "integer"},
            },
        },
        "error": {"type": "string"},
        "ms": {"type": "integer"},
    },
    "required": ["index", "kind", "status"],
}


@extend_schema_field(spec.TRIGGER_SCHEMA)
class TriggerField(serializers.JSONField):
    """What fires the automation: `{kind, …}` (automations/spec.py)."""


@extend_schema_field(spec.ACTIONS_SCHEMA)
class ActionsField(serializers.JSONField):
    """What it does, in order: `[{kind, …}]` (automations/spec.py)."""


@extend_schema_field({"type": "array", "items": OUTCOME})
class OutcomesField(serializers.JSONField):
    """Each action's outcome, in order."""


class AutomationLastRunSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = AutomationRun
        fields = ["id", "trigger", "status", "error", "created_at", "finished_at"]
        read_only_fields = fields


class AutomationSerializer(OwnedSerializer):
    trigger = TriggerField()
    actions = ActionsField(required=False)
    last_run = AutomationLastRunSerializer(read_only=True, allow_null=True)
    webhook_url = serializers.SerializerMethodField()
    secret = serializers.SerializerMethodField()

    class Meta:
        model = Automation
        fields = [
            *OWNED,
            "name",
            "description",
            "enabled",
            "trigger",
            "condition",
            "actions",
            "on_error",
            "max_runs_per_hour",
            "webhook_url",
            "secret",
            "last_run",
        ]
        read_only_fields = ["enabled", "created_at", "updated_at"]

    def get_can_edit(self, automation) -> bool:
        """Whether the requester may change, enable or test it: its owner, or a superuser — it runs as its owner."""
        return automation.can_edit(getattr(self.context.get("request"), "user", None))

    def get_webhook_url(self, automation) -> str | None:
        """Where a webhook trigger's requests go, signed with the automation's secret; null for any other trigger."""
        if not isinstance(automation.trigger, dict) or automation.trigger.get("kind") != "webhook":
            return None
        path = reverse("automation-webhook", args=[automation.public_id])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request is not None else path

    def get_secret(self, automation) -> str | None:
        """The secret that signs its webhooks, in the answer that made it (or a new one) and never again."""
        return getattr(automation, "new_secret", None)

    def update(self, automation, validated_data):
        if validated_data.get("trigger", automation.trigger) != automation.trigger:
            automation.scheduled_at = timezone.now()  # a new schedule counts from when it was set, as on enabling
        return super().update(automation, validated_data)

    def to_representation(self, automation):
        """Its last run only for whoever sees its runs (its owner, staff): a run's error can quote what it heard."""
        data = super().to_representation(automation)
        if not automation.shows_runs_to(getattr(self.context.get("request"), "user", None)):
            data["last_run"] = None
        return data


class AutomationRunSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    automation = serializers.SlugRelatedField(slug_field="public_id", read_only=True)
    automation_name = serializers.CharField(source="automation.name", read_only=True)
    outcomes = OutcomesField(read_only=True)

    class Meta:
        model = AutomationRun
        fields = [
            "id",
            "automation",
            "automation_name",
            "trigger",
            "status",
            "matched",
            "payload",
            "outcomes",
            "error",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields


# ── the actions' requests and responses ────────────────────────────────────


class AutomationPayloadSerializer(serializers.Serializer):
    payload = serializers.DictField(
        default=dict, help_text="A sample of what its trigger sends (options/ has one for each kind)."
    )


class AutomationConditionSerializer(AutomationPayloadSerializer):
    condition = serializers.CharField(allow_blank=True, max_length=5000, help_text="A JMESPath expression.")


class AutomationVerdictSerializer(serializers.Serializer):
    matched = serializers.BooleanField(allow_null=True, help_text="Null when the condition could not be evaluated.")
    value = serializers.JSONField(allow_null=True, help_text="What the expression found in the payload.")
    error = serializers.CharField(allow_blank=True)


class AutomationDryRunActionSerializer(serializers.Serializer):
    index = serializers.IntegerField()
    kind = serializers.CharField()
    input = serializers.DictField(help_text="The action with its templates rendered against the payload.")


class AutomationDryRunSerializer(AutomationVerdictSerializer):
    actions = AutomationDryRunActionSerializer(many=True)


class AutomationAgentSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()


class AutomationOptionsSerializer(serializers.Serializer):
    events = serializers.ListField(child=serializers.CharField(), help_text="The events a trigger may wait for.")
    stages = serializers.ListField(child=serializers.CharField(), help_text="Where an action may move a story.")
    agents = AutomationAgentSerializer(many=True, help_text="The agents an action may start.")
    samples = serializers.DictField(help_text="A sample payload per trigger kind; an event's per event type.")


class AutomationYamlSerializer(serializers.Serializer):
    name = serializers.CharField()
    yaml = serializers.CharField(help_text="The automation as a YAML document: no owner, secret or enabled.")


class AutomationImportSerializer(serializers.Serializer):
    yaml = serializers.CharField(max_length=100_000, help_text="A document `export/` wrote.")


class AutomationSecretSerializer(serializers.Serializer):
    secret = serializers.CharField(help_text="Shown this once.")


class AutomationWebhookAcceptedSerializer(serializers.Serializer):
    run = serializers.UUIDField()
    status = serializers.CharField(help_text="queued — or limited, when the automation is over its runs per hour.")
