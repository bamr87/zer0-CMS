"""The outbox desk API's shapes (`/api/v2/outbox/`), so the OpenAPI document and the studio's generated client
follow them.

A belt message is shown as the library writes it — `from`, `to`, `kind`, `subject`, `trace`, `parent_id`,
`created_at`, `payload`, `ref`, and on the ledger the relay's `seq` — so what the studio shows is what
`ledger.jsonl` says. `from` and `pass` are Python keywords, which a class body cannot declare (`Keywords`). A task
card and a claim set are validated here, field by field, before the worker gives them to the harness; a claim's id
names a directory, so it is held to a safe name. Trials and claim checks are addressed by their UUID (`id`).
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.serializers import PageRefSerializer
from cms.services import visible_pages

from .models import ClaimCheck, Trial
from .services import SENDABLE, trial_ledger

# The belt's kinds (outbox_harness.belt.KINDS; tests/outboxdesk hold the two equal) and the claim desk's verdicts.
KINDS = ("idea", "assignment", "draft", "verdict", "approval", "published", "signal")
VERDICTS = ("pass", "block")
TICKS = {"min_value": 0, "max_value": 1000}


class Keywords(serializers.Serializer):
    """Fields named by Python keywords (`from`, `pass`), added where a class body cannot declare them."""

    keywords: dict = {}

    def get_fields(self):
        fields = super().get_fields()
        for name, make in self.keywords.items():
            fields[name] = make()
        return fields


# ── the belt ───────────────────────────────────────────────────────────────


class KindCountSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=KINDS)
    count = serializers.IntegerField()


class BeltSummarySerializer(serializers.Serializer):
    delivered = serializers.IntegerField(help_text="Messages on the ledger.")
    dead_letters = serializers.IntegerField()
    traces = serializers.IntegerField(help_text="Pieces of work the ledger has seen.")
    kinds = KindCountSerializer(many=True)
    seq_gapless = serializers.BooleanField(help_text="The relay's sequence runs 1, 2, 3 … with no gap.")
    ids_unique = serializers.BooleanField()
    pending = serializers.IntegerField(help_text="Outbox records the relay has not delivered or dead-lettered yet.")
    stations = serializers.ListField(child=serializers.CharField())
    editor = serializers.CharField(help_text="The station a person sends as.")
    harness = serializers.CharField(help_text="The installed outbox harness's version.")


class HandoffSerializer(Keywords):
    keywords = {"from": lambda: serializers.CharField(help_text="The station that sent it.")}

    seq = serializers.IntegerField(
        allow_null=True, required=False, help_text="The relay's number; none until delivered."
    )
    id = serializers.CharField()
    kind = serializers.ChoiceField(choices=KINDS)
    to = serializers.ListField(child=serializers.CharField())
    subject = serializers.CharField(help_text="The stable key of the piece of work.")
    trace = serializers.CharField(help_text="Shared by every message about one piece of work (32 hex digits).")
    parent_id = serializers.CharField(allow_null=True)
    created_at = serializers.CharField()
    payload = serializers.DictField()
    ref = serializers.DictField(allow_null=True, help_text="What the message is about: a page, a file, a URL.")


class CloudEventSerializer(serializers.Serializer):
    specversion = serializers.CharField()
    id = serializers.CharField()
    source = serializers.CharField()
    type = serializers.CharField()
    subject = serializers.CharField()
    time = serializers.CharField()
    datacontenttype = serializers.CharField()
    traceparent = serializers.CharField()
    data = serializers.DictField()


class BeltMessageSerializer(HandoffSerializer):
    cloudevent = CloudEventSerializer(help_text="The message as a CloudEvents 1.0 envelope (the library's binding).")


class JourneySerializer(serializers.Serializer):
    trace = serializers.CharField()
    messages = HandoffSerializer(many=True)


class DeadLetterSerializer(serializers.Serializer):
    id = serializers.CharField()
    station = serializers.CharField()
    path = serializers.CharField(help_text="The outbox file's name.")
    errors = serializers.ListField(child=serializers.CharField())


class SendSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SENDABLE)
    to = serializers.ListField(child=serializers.CharField(max_length=64), min_length=1, max_length=20)
    subject = serializers.CharField(max_length=255, required=False, allow_blank=True)
    payload = serializers.DictField(required=False)
    parent_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="A delivered message this answers (an approval must).",
    )
    trace = serializers.RegexField(r"\A[0-9a-f]{32}\Z", required=False, allow_blank=True)
    ref = serializers.DictField(required=False)
    page = serializers.IntegerField(required=False, allow_null=True, help_text="A page the message is about.")

    def validate_page(self, value):
        if value is None:
            return None
        page = visible_pages(self.context["request"].user).filter(pk=value).first()
        if page is None:
            raise serializers.ValidationError(f"no page {value} you can find")
        return page.specific


class QueuedDeliverySerializer(serializers.Serializer):
    pending = serializers.IntegerField(help_text="Records waiting for the relay pass just queued.")


# ── trials ─────────────────────────────────────────────────────────────────


class EnvEventSerializer(serializers.Serializer):
    tick = serializers.IntegerField(**TICKS)
    env_seq = serializers.IntegerField(min_value=1)
    fact = serializers.CharField(max_length=2000)
    answer_hint = serializers.JSONField(required=False, allow_null=True)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    source = serializers.CharField(max_length=255, required=False, allow_blank=True)


class TaskCardSerializer(serializers.Serializer):
    """A task card, as the harness's tasks/*.json and protocol/schema.json describe one."""

    id = serializers.CharField(max_length=120)
    family = serializers.CharField(max_length=120, required=False, allow_blank=True)
    question = serializers.CharField(max_length=2000)
    expected_answer = serializers.JSONField(
        required=False, allow_null=True, help_text="The judge; none leaves it open."
    )
    closes_at_tick = serializers.IntegerField(min_value=1, max_value=1000)
    deadline_ping_tick = serializers.IntegerField(min_value=-1, max_value=1000, required=False)
    lag_b = serializers.IntegerField(min_value=0, max_value=100, required=False)
    max_env_lag = serializers.IntegerField(min_value=0, max_value=1000, required=False)
    inversion_confidence = serializers.FloatField(min_value=0, max_value=1, required=False)
    a_sticky = serializers.BooleanField(required=False)
    env_schedule = EnvEventSerializer(many=True, max_length=1000)


class StartTrialSerializer(serializers.Serializer):
    task = TaskCardSerializer()
    lag_b = serializers.IntegerField(
        min_value=0, max_value=100, required=False, allow_null=True, help_text="Widen or close the race."
    )


class WinnerSerializer(Keywords):
    keywords = {"from": lambda: serializers.CharField(allow_null=True)}

    id = serializers.CharField(allow_null=True)
    confidence = serializers.FloatField(allow_null=True)
    env_seq = serializers.IntegerField(allow_null=True)
    answer = serializers.JSONField(allow_null=True)
    tick = serializers.IntegerField(allow_null=True)


class TrialResultSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    family = serializers.CharField(allow_null=True)
    latest_env_seq = serializers.IntegerField()
    n_active_claims = serializers.IntegerField()
    winner = WinnerSerializer(allow_null=True)
    first_claim_from = serializers.CharField(allow_null=True)
    resolved = serializers.BooleanField()
    correct = serializers.BooleanField(allow_null=True)
    confidence_inversion = serializers.BooleanField(allow_null=True)
    retracts = serializers.IntegerField()
    claims_per_agent = serializers.DictField(child=serializers.IntegerField())
    expected_answer = serializers.JSONField(allow_null=True)


class TrialSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    requested_by = serializers.CharField(source="requested_by.username", allow_null=True, default=None)
    task = TaskCardSerializer()
    result = TrialResultSerializer(allow_null=True)

    class Meta:
        model = Trial
        fields = ["id", "task", "lag_b", "status", "error", "result", "run_dir", "requested_by", "created_at"]
        fields += ["started_at", "finished_at"]
        read_only_fields = fields


class ArenaRowSerializer(Keywords):
    """A line of the arena's ledger: a tick, or a delivered message (`outbox watch` reads the same)."""

    keywords = {"from": lambda: serializers.CharField(required=False)}

    event = serializers.CharField(required=False)
    tick = serializers.IntegerField(required=False)
    type = serializers.CharField(required=False)
    id = serializers.CharField(required=False)
    task_id = serializers.CharField(required=False)
    to = serializers.ListField(child=serializers.CharField(), required=False)
    env_seq = serializers.IntegerField(required=False)
    created_at_tick = serializers.IntegerField(required=False)
    closes_at_tick = serializers.IntegerField(required=False, allow_null=True)
    confidence = serializers.FloatField(required=False, allow_null=True)
    parent_id = serializers.CharField(required=False, allow_null=True)
    payload = serializers.DictField(required=False)
    note = serializers.CharField(required=False, allow_blank=True)


class TrialDetailSerializer(TrialSerializer):
    ledger = serializers.SerializerMethodField(help_text="The arena's ledger, in the order it was written.")

    class Meta(TrialSerializer.Meta):
        fields = [*TrialSerializer.Meta.fields, "ledger"]
        read_only_fields = fields

    @extend_schema_field(ArenaRowSerializer(many=True))
    def get_ledger(self, trial):
        return ArenaRowSerializer(trial_ledger(trial), many=True).data


# ── the claim desk ─────────────────────────────────────────────────────────


class ClaimSerializer(serializers.Serializer):
    id = serializers.RegexField(
        r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z", help_text="Letters, digits, `_`, `.` and `-`: it names a directory."
    )
    question = serializers.CharField(max_length=2000)
    answer = serializers.JSONField(help_text="What the draft says.")
    confidence = serializers.FloatField(min_value=0, max_value=1, required=False, allow_null=True)
    sources = serializers.ListField(
        child=serializers.CharField(max_length=255), required=False, help_text="Only these sources' rows; none for all."
    )


class TimelineRowSerializer(serializers.Serializer):
    tick = serializers.IntegerField(**TICKS)
    source = serializers.CharField(max_length=255)
    says = serializers.JSONField(help_text="What the source said then.")
    fact = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class StartClaimCheckSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    author = serializers.CharField(max_length=120, required=False, allow_blank=True, help_text="Whose draft it is.")
    page = serializers.IntegerField(required=False, allow_null=True, help_text="The draft the claims are from.")
    claims = ClaimSerializer(many=True, max_length=100)
    timeline = TimelineRowSerializer(many=True, max_length=1000)
    closes_at_tick = serializers.IntegerField(min_value=1, max_value=1000, default=8)
    lag_b = serializers.IntegerField(min_value=0, max_value=100, default=2)

    validate_page = SendSerializer.validate_page

    def validate_claims(self, claims):
        ids = [claim["id"] for claim in claims]
        if not ids:
            raise serializers.ValidationError("a check needs a claim")
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("every claim has an id of its own")
        return claims


class VerdictSerializer(serializers.Serializer):
    claim_id = serializers.CharField()
    question = serializers.CharField()
    draft_answer = serializers.JSONField()
    verdict = serializers.ChoiceField(choices=VERDICTS)
    reason = serializers.CharField(help_text="sources_agree, sources_disagree, winner_is_stale, low_confidence, …")
    supported_answer = serializers.JSONField(allow_null=True)
    winner_from = serializers.CharField(required=False, allow_null=True)
    winner_confidence = serializers.FloatField(required=False, allow_null=True)
    winner_env_seq = serializers.IntegerField(required=False, allow_null=True)
    latest_env_seq = serializers.IntegerField(required=False, allow_null=True)


class DeskReportSerializer(Keywords):
    keywords = {"pass": lambda: serializers.BooleanField(help_text="Every claim passed.")}

    claims = VerdictSerializer(many=True)


class ResolutionSerializer(serializers.Serializer):
    claim_id = serializers.CharField()
    task_id = serializers.CharField(help_text="The arena task the claim was raced in.")
    truth = serializers.JSONField(allow_null=True)
    winner_correct = serializers.BooleanField(allow_null=True)
    confidence_inversion = serializers.BooleanField(allow_null=True)
    draft_correct = serializers.BooleanField()
    brier = serializers.DictField(child=serializers.FloatField(), help_text="Per verifier; lower is better.")
    draft_brier = serializers.FloatField(allow_null=True, help_text="The draft's own confidence, scored.")


class ClaimCheckSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    requested_by = serializers.CharField(source="requested_by.username", allow_null=True, default=None)
    page = PageRefSerializer(allow_null=True)
    claim_count = serializers.SerializerMethodField()

    class Meta:
        model = ClaimCheck
        fields = ["id", "title", "author", "page", "claim_count", "status", "passed", "resolution_status"]
        fields += ["requested_by", "created_at", "finished_at", "resolved_at"]
        read_only_fields = fields

    def get_claim_count(self, check) -> int:
        return len(check.claims or [])


class ClaimCheckDetailSerializer(ClaimCheckSerializer):
    claims = ClaimSerializer(many=True)
    timeline = TimelineRowSerializer(many=True)
    report = DeskReportSerializer(allow_null=True)
    truth = serializers.DictField(allow_null=True)
    resolutions = ResolutionSerializer(many=True, allow_null=True)

    class Meta(ClaimCheckSerializer.Meta):
        fields = [*ClaimCheckSerializer.Meta.fields, "claims", "timeline", "closes_at_tick", "lag_b", "error", "report"]
        fields += ["truth", "resolutions", "resolution_error", "run_dir"]
        read_only_fields = fields


class ResolveSerializer(serializers.Serializer):
    truth = serializers.DictField(child=serializers.JSONField(), help_text="Claim id → what turned out to be true.")


class CalibrationRowSerializer(serializers.Serializer):
    name = serializers.CharField()
    n = serializers.IntegerField(help_text="Resolved claims scored.")
    brier = serializers.FloatField(help_text="Mean Brier score: 0 is perfect, 0.25 a coin flip at 0.5.")


class CalibrationSerializer(serializers.Serializer):
    resolved = serializers.IntegerField()
    winner_accuracy = serializers.FloatField()
    verifiers = CalibrationRowSerializer(many=True)
    authors = CalibrationRowSerializer(many=True)
