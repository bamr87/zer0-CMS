"""The AIEO API's shapes (`/api/v2/aieo/`).

Rows are addressed by their UUID public id (`id`); a pattern by its name; a page and a site by Wagtail's ids.
Every serializer's name starts with `Aieo`, so the OpenAPI document's components stay unique across the platform.
An audit's `result` is the scorer's whole answer (aieo/scoring.py) — patterns with evidence, gaps, penalties, the
dimensions and the analyses behind them, and for a model's evaluation its assessment, priority actions and sample
improvements — kept as it came. A connector's credential is write-only: it goes in, is encrypted, and only
`has_credential` comes back.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from wagtail.models import Site

from ai.models import Visibility
from ai.serializers import OWNED, OwnedSerializer, RunRefSerializer

from .models import Audit, BrandContext, CitationCheck, CitationQuery, Connector, Pattern
from .services import benchmark_for

# Choice sets the OpenAPI document names (SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]).
MODES = ["optimize", "expand", "scrub", "rewrite", "pattern"]
STYLES = ["preserve", "aggressive"]
GROUPS = ["agent", "evaluator", "rewriter", "writer", "probe"]


class AieoScoreInputSerializer(serializers.Serializer):
    content = serializers.CharField(trim_whitespace=False)
    format = serializers.ChoiceField(choices=["markdown", "html"], default="markdown")
    site = serializers.PrimaryKeyRelatedField(
        queryset=Site.objects.all(), required=False, allow_null=True, help_text="Read this site's target keywords."
    )


class AieoScoreSerializer(serializers.Serializer):
    """A score at once: the heuristics' whole answer (nothing recorded)."""

    score = serializers.FloatField()
    grade = serializers.CharField()
    scoring_method = serializers.CharField()
    word_count = serializers.IntegerField()
    dimensions = serializers.DictField(child=serializers.FloatField(allow_null=True))
    pattern_scores = serializers.DictField(child=serializers.DictField())
    gaps = serializers.ListField(child=serializers.DictField())
    anti_pattern_penalties = serializers.FloatField()
    result = serializers.SerializerMethodField(help_text="The whole answer: the analyses behind each dimension too.")

    def get_result(self, data) -> dict:
        return data


# ── audits ─────────────────────────────────────────────────────────────────


class AieoAuditSerializer(OwnedSerializer):
    page = serializers.IntegerField(source="page_id", read_only=True, allow_null=True)
    target = serializers.CharField(read_only=True)
    run = RunRefSerializer(read_only=True, allow_null=True)
    screenshot = serializers.SerializerMethodField()
    benchmark = serializers.SerializerMethodField(
        help_text="Its percentile among the audits of its kind and how many; on one finished audit, also per engine "
        "how often its domain was cited and the audits nearest it in meaning, of those the reader sees."
    )

    class Meta:
        model = Audit
        fields = [
            *OWNED,
            "kind",
            "method",
            "provider",
            "title",
            "url",
            "page",
            "target",
            "format",
            "max_pages",
            "visual",
            "status",
            "score",
            "grade",
            "scoring_method",
            "content_hash",
            "result",
            "pages",
            "benchmark",
            "screenshot",
            "batch",
            "origin",
            "run",
            "error",
            "audited_at",
        ]
        read_only_fields = [f for f in fields if f not in ("site", "visibility")]

    def get_screenshot(self, row) -> str | None:
        return f"/api/v2/aieo/audits/{row.public_id}/screenshot/" if row.screenshot else None

    @extend_schema_field(serializers.JSONField())
    def get_benchmark(self, row):
        user = getattr(self.context.get("request"), "user", None)
        stored = dict(row.benchmark or {})
        return {**stored, **benchmark_for(row, user)} if row.status == Audit.READY and user is not None else stored


class AieoAuditListSerializer(AieoAuditSerializer):
    """An audit in a list: everything but the whole result and the pages, and of its benchmark the counts."""

    class Meta(AieoAuditSerializer.Meta):
        fields = [f for f in AieoAuditSerializer.Meta.fields if f not in ("result", "pages")]
        read_only_fields = fields

    @extend_schema_field(serializers.JSONField())
    def get_benchmark(self, row):
        return dict(row.benchmark or {})


class AieoAuditCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Audit.KINDS)
    method = serializers.ChoiceField(choices=Audit.METHODS, default=Audit.AI)
    content = serializers.CharField(required=False, default="", allow_blank=True, trim_whitespace=False)
    format = serializers.ChoiceField(choices=[Audit.MARKDOWN, Audit.HTML], default=Audit.MARKDOWN)
    page_id = serializers.IntegerField(required=False, allow_null=True)
    url = serializers.CharField(required=False, default="", allow_blank=True, max_length=2000)
    max_pages = serializers.IntegerField(required=False, default=25, min_value=1, max_value=200)
    visual = serializers.BooleanField(required=False, default=False)
    provider = serializers.CharField(required=False, default="", allow_blank=True, max_length=40)
    title = serializers.CharField(required=False, default="", allow_blank=True, max_length=500)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all(), required=False, allow_null=True)
    visibility = serializers.ChoiceField(choices=Visibility.choices, required=False)


class AieoAuditAcceptedSerializer(serializers.Serializer):
    audit = AieoAuditSerializer()
    run = RunRefSerializer()


class AieoBatchInputSerializer(serializers.Serializer):
    urls = serializers.ListField(child=serializers.CharField(max_length=2000), min_length=1, max_length=100)
    method = serializers.ChoiceField(choices=Audit.METHODS, default=Audit.AI)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all(), required=False, allow_null=True)
    visibility = serializers.ChoiceField(choices=Visibility.choices, required=False)


class AieoBatchSerializer(serializers.Serializer):
    batch = serializers.CharField()
    audits = AieoAuditListSerializer(many=True)


class AieoReportSerializer(serializers.Serializer):
    filename = serializers.CharField()
    markdown = serializers.CharField()
    html = serializers.CharField()


# ── patterns ───────────────────────────────────────────────────────────────


class AieoPatternSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Pattern
        fields = [
            "id",
            "name",
            "display_name",
            "category",
            "description",
            "weight",
            "max_score",
            "boost_min",
            "boost_max",
            "body",
            "enabled",
            "bundled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["bundled", "created_at", "updated_at"]


class AieoApplyPatternSerializer(serializers.Serializer):
    page_id = serializers.IntegerField(required=False, allow_null=True)
    content = serializers.CharField(required=False, default="", allow_blank=True, trim_whitespace=False)
    style = serializers.ChoiceField(choices=STYLES, default="preserve")


# ── rewrites and agents ────────────────────────────────────────────────────


class AieoRewriteInputSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=MODES)
    page_id = serializers.IntegerField(required=False, allow_null=True, help_text="Suggestions on this page.")
    content = serializers.CharField(
        required=False, default="", allow_blank=True, trim_whitespace=False, help_text="Or a text: a draft to read."
    )
    pattern = serializers.SlugRelatedField(
        slug_field="name", queryset=Pattern.objects.all(), required=False, allow_null=True
    )
    style = serializers.ChoiceField(choices=STYLES, default="preserve")


class AieoRunAcceptedSerializer(serializers.Serializer):
    run = RunRefSerializer()


class AieoAgentSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="aieo-<name>; the ten agents are in group `agent`.")
    id = serializers.UUIDField(help_text="The bundled assistant's id (AI → Assistants).")
    name = serializers.CharField()
    description = serializers.CharField()
    group = serializers.ChoiceField(choices=GROUPS)
    structured = serializers.BooleanField(help_text="Whether it answers as JSON (an output schema).")


class AieoAgentRunInputSerializer(serializers.Serializer):
    agent = serializers.CharField(help_text="An agent's key: aieo-seo-optimizer, aieo-meta-creator, …")
    content = serializers.CharField(required=False, default="", allow_blank=True, trim_whitespace=False)
    page_id = serializers.IntegerField(required=False, allow_null=True)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all(), required=False, allow_null=True)
    inputs = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False, default=dict)


# ── citations ──────────────────────────────────────────────────────────────


class AieoCitationQuerySerializer(OwnedSerializer):
    latest = serializers.SerializerMethodField()

    class Meta:
        model = CitationQuery
        fields = [
            *OWNED,
            "prompt",
            "domain",
            "engines",
            "interval_days",
            "active",
            "next_check_at",
            "last_checked_at",
            "latest",
        ]
        read_only_fields = ["next_check_at", "last_checked_at", "created_at", "updated_at"]

    def validate_engines(self, value):
        from ai import providers

        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise serializers.ValidationError("a list of provider slugs")
        unknown = sorted(set(value) - set(providers.available()))
        if unknown:
            raise serializers.ValidationError(f"no provider {', '.join(unknown)}")
        return list(dict.fromkeys(value))

    def validate_domain(self, value):
        from .services import _bare

        bare = _bare(value.strip())
        if "." not in bare:
            raise serializers.ValidationError("a domain, like example.com")
        return bare

    @extend_schema_field(serializers.DictField(child=serializers.DictField()))
    def get_latest(self, query) -> dict:
        """Each engine's last answer: {engine: {cited, position, checked_at, status}}."""
        found = {}
        for check in query.checks.order_by("-checked_at")[:50]:
            found.setdefault(
                check.engine,
                {
                    "cited": check.cited,
                    "position": check.position,
                    "checked_at": check.checked_at,
                    "status": check.status,
                },
            )
        return found


class AieoCitationCheckSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    query = serializers.UUIDField(source="query.public_id", read_only=True)
    run = RunRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = CitationCheck
        fields = [
            "id",
            "query",
            "engine",
            "model",
            "status",
            "cited",
            "position",
            "cited_urls",
            "sources",
            "answer",
            "error",
            "run",
            "checked_at",
        ]
        read_only_fields = fields


class AieoCitationChecksSerializer(serializers.Serializer):
    checks = AieoCitationCheckSerializer(many=True)


class AieoEngineShareSerializer(serializers.Serializer):
    engine = serializers.CharField()
    checks = serializers.IntegerField()
    cited = serializers.IntegerField()
    rate = serializers.FloatField()


class AieoWeekShareSerializer(AieoEngineShareSerializer):
    week = serializers.CharField(help_text="The Monday the week starts on.")


class AieoShareOfVoiceSerializer(serializers.Serializer):
    days = serializers.IntegerField()
    engines = AieoEngineShareSerializer(many=True)
    weeks = AieoWeekShareSerializer(many=True)


# ── connectors, priorities, context, lifecycle ─────────────────────────────


class AieoConnectorSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all())
    credential = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={"input_type": "password"},
        help_text="Write-only; encrypted at rest. GA4 and GSC: a service account's JSON key; DataForSEO: login:password.",
    )
    has_credential = serializers.BooleanField(read_only=True)
    can_edit = serializers.SerializerMethodField()
    rows = serializers.SerializerMethodField()

    class Meta:
        model = Connector
        fields = [
            "id",
            "site",
            "kind",
            "enabled",
            "options",
            "credential",
            "has_credential",
            "status",
            "error",
            "last_synced_at",
            "can_edit",
            "rows",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "error", "last_synced_at", "created_at", "updated_at"]

    def get_can_edit(self, row) -> bool:
        return row.can_edit(getattr(self.context.get("request"), "user", None))

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_rows(self, row) -> int | None:
        """How many rows the last sync fetched."""
        last = row.snapshots.first()
        return len(last.rows) if last else None

    def validate_options(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("an object")
        return value


class AieoConnectorDataSerializer(serializers.Serializer):
    report = serializers.CharField()
    fetched_at = serializers.DateTimeField()
    rows = serializers.ListField(child=serializers.DictField())


class AieoPriorityRowSerializer(serializers.Serializer):
    query = serializers.CharField()
    page = serializers.CharField()
    clicks = serializers.IntegerField()
    impressions = serializers.IntegerField()
    ctr = serializers.FloatField()
    position = serializers.FloatField()
    opportunity_score = serializers.FloatField()
    components = serializers.DictField(child=serializers.FloatField())


class AieoPrioritiesSerializer(serializers.Serializer):
    site = serializers.IntegerField()
    fetched_at = serializers.DateTimeField(allow_null=True)
    queue = AieoPriorityRowSerializer(many=True)
    quick_wins = AieoPriorityRowSerializer(many=True)


class AieoBrandContextSerializer(serializers.ModelSerializer):
    site = serializers.IntegerField(source="site_id", read_only=True)
    keywords = serializers.SerializerMethodField()

    class Meta:
        model = BrandContext
        fields = ["site", *BrandContext.FIELDS, "competitors", "keywords", "updated_at"]
        read_only_fields = ["updated_at"]

    def get_keywords(self, row) -> list[str]:
        """The target keywords the analyzers and priorities read."""
        return row.keywords()

    def validate_competitors(self, value):
        if not isinstance(value, dict) or not all(
            isinstance(value.get(k, []), list) for k in ("competitors", "keywords", "topics")
        ):
            raise serializers.ValidationError("{competitors: [...], keywords: [...], topics: [...]}")
        return value


class AieoLifecycleSerializer(serializers.Serializer):
    topics = serializers.IntegerField()
    research = serializers.IntegerField()
    drafts = serializers.IntegerField()
    rewrites = serializers.IntegerField()
    review_required = serializers.IntegerField()
    published = serializers.IntegerField()
    landing_pages = serializers.IntegerField()
    audits = serializers.IntegerField()
    average_score = serializers.FloatField(allow_null=True)
