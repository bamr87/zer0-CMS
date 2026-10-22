"""The research API's shapes (`/api/v2/research/`).

Rows are addressed by their UUID public id (`id`); a related row is named by
its public id too, out of the rows the requester may see (`Visible`), a page by
Wagtail's id. Validation is the models' own (`OwnedSerializer`, from the AI
layer). A list of sources leaves out their text (`SourceListSerializer`); one
source carries all of it. A question's and a fact-check's `status` is its
run's: `pending` until the run ends, then `ready` or `failed` (with the run's
error).
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from wagtail.models import Page

from ai.models import Brief
from ai.serializers import OWNED, OwnedSerializer, RunRefSerializer, Visible

from .models import Citation, Collection, FactCheck, FeedSubscription, Question, Quote, Source

OUTCOMES = ["pending", "ready", "failed"]
CAPTURED = [Source.URL, Source.NOTE]  # what POST sources/ makes; uploads and feed items have their own way in
VERDICTS = ["supported", "contradicted", "unsupported"]


def outcome(run) -> tuple[str, str]:
    """(status, error) of a row a run fills."""
    if run is None or not run.is_final:
        return "pending", ""
    return ("ready", "") if run.status == run.SUCCEEDED else ("failed", run.error or run.status)


class CollectionSerializer(OwnedSerializer):
    class Meta:
        model = Collection
        fields = [*OWNED, "name", "description"]
        read_only_fields = ["created_at", "updated_at"]


SOURCE_LIST = [
    *OWNED,
    "kind",
    "collection",
    "url",
    "title",
    "author",
    "site_name",
    "published",
    "status",
    "error",
    "robots",
    "fetched_at",
]


class SourceListSerializer(OwnedSerializer):
    collection = Visible(Collection, allow_null=True, required=False)

    class Meta:
        model = Source
        fields = SOURCE_LIST
        read_only_fields = fields


class SourceSerializer(OwnedSerializer):
    collection = Visible(Collection, allow_null=True, required=False)
    feed = serializers.SlugRelatedField(slug_field="public_id", read_only=True)
    summary_run = RunRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Source
        fields = [
            *SOURCE_LIST,
            "language",
            "text",
            "metadata",
            "summary",
            "entities",
            "highlights",
            "summary_run",
            "feed",
        ]
        read_only_fields = [
            "kind",
            "url",
            "status",
            "error",
            "robots",
            "fetched_at",
            "metadata",
            "entities",
            "highlights",
            "feed",
            "created_at",
            "updated_at",
        ]


class SourceCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=CAPTURED, help_text="A web page to capture, or a note.")
    url = serializers.URLField(max_length=2000, required=False, help_text="For a web page.")
    text = serializers.CharField(required=False, allow_blank=True, help_text="For a note.")
    title = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    collection = Visible(Collection, allow_null=True, required=False)


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="A PDF, plain text or Markdown.")
    title = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    collection = Visible(Collection, allow_null=True, required=False)


class SearchSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=500)
    collection = Visible(Collection, allow_null=True, required=False)
    max_results = serializers.IntegerField(min_value=1, max_value=10, default=5)
    provider = serializers.CharField(required=False, allow_blank=True, default="", help_text="A provider's slug.")


class SourceRunSerializer(serializers.Serializer):
    source = SourceSerializer()
    run = RunRefSerializer()


class ResearchBriefSerializer(serializers.Serializer):
    topic = serializers.CharField(max_length=500)


class QuoteSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    source = Visible(Source)
    owner = serializers.CharField(source="owner.username", read_only=True, allow_null=True)

    class Meta:
        model = Quote
        fields = ["id", "source", "text", "note", "location", "owner", "created_at"]
        read_only_fields = ["created_at"]


class CitationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    source = Visible(Source)
    quote = Visible(Quote, allow_null=True, required=False)
    page = serializers.PrimaryKeyRelatedField(queryset=Page.objects.all(), allow_null=True, required=False)
    brief = Visible(Brief, allow_null=True, required=False)
    source_title = serializers.SerializerMethodField()
    source_url = serializers.URLField(source="source.url", read_only=True)
    page_title = serializers.SerializerMethodField()
    created_by = serializers.CharField(source="created_by.username", read_only=True, allow_null=True)

    class Meta:
        model = Citation
        fields = [
            "id",
            "source",
            "source_title",
            "source_url",
            "quote",
            "page",
            "page_title",
            "brief",
            "note",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def get_source_title(self, citation) -> str:
        return citation.source.title or citation.source.url

    def get_page_title(self, citation) -> str:
        return citation.page.title if citation.page_id else ""


class FeedSerializer(OwnedSerializer):
    collection = Visible(Collection, allow_null=True, required=False)
    items = serializers.SerializerMethodField(help_text="The sources it has brought.")

    class Meta:
        model = FeedSubscription
        fields = [
            *OWNED,
            "url",
            "title",
            "collection",
            "active",
            "interval_minutes",
            "last_checked_at",
            "next_check_at",
            "error",
            "items",
        ]
        read_only_fields = ["last_checked_at", "next_check_at", "error", "created_at", "updated_at"]

    def get_items(self, feed) -> int:
        return feed.items.count()


class Outcome:
    """`status` and `error`, from the run that fills the row."""

    @extend_schema_field(serializers.ChoiceField(choices=OUTCOMES))
    def get_status(self, row) -> str:
        return outcome(row.run)[0]

    def get_error(self, row) -> str:
        return outcome(row.run)[1]


class CitedSourceSerializer(serializers.Serializer):
    label = serializers.CharField()
    source = serializers.UUIDField()
    title = serializers.CharField()
    quote = serializers.CharField()
    verified = serializers.BooleanField(help_text="The quote is in the source's text, word for word.")


class QuestionSerializer(Outcome, OwnedSerializer):
    collection = Visible(Collection, allow_null=True, required=False)
    citations = CitedSourceSerializer(many=True, read_only=True)
    status = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    run = RunRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Question
        fields = [*OWNED, "collection", "text", "answer", "citations", "status", "error", "run"]
        read_only_fields = ["answer", "created_at", "updated_at"]


class QuestionRunSerializer(serializers.Serializer):
    question = QuestionSerializer()
    run = RunRefSerializer()


class FindingSourceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()


class FindingSerializer(serializers.Serializer):
    block = serializers.CharField(help_text="The id of the block the claim is in ('' when the checker named none).")
    claim = serializers.CharField()
    verdict = serializers.ChoiceField(choices=VERDICTS)
    explanation = serializers.CharField()
    correction = serializers.CharField(allow_blank=True)
    sources = FindingSourceSerializer(many=True)
    suggestion = serializers.IntegerField(allow_null=True, help_text="The suggestion it became, to accept or reject.")
    error = serializers.CharField(allow_blank=True, help_text="Why a correction could not become a suggestion.")


class FactCheckSerializer(Outcome, OwnedSerializer):
    page = serializers.PrimaryKeyRelatedField(read_only=True)
    page_title = serializers.CharField(source="page.title", read_only=True)
    collection = Visible(Collection, allow_null=True, required=False)
    findings = FindingSerializer(many=True, read_only=True)
    status = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    run = RunRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = FactCheck
        fields = [*OWNED, "page", "page_title", "collection", "summary", "findings", "status", "error", "run"]
        read_only_fields = ["summary", "created_at", "updated_at"]


class FactCheckCreateSerializer(serializers.Serializer):
    page_id = serializers.IntegerField(help_text="The draft to check: a page you may edit.")
    collection = Visible(Collection, allow_null=True, required=False, help_text="Also check against this collection.")


class FactCheckRunSerializer(serializers.Serializer):
    fact_check = FactCheckSerializer()
    run = RunRefSerializer()
