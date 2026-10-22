"""`/api/v2/research/`: the research library over REST (research/README.md).

    collections/                      CRUD; <id>/research-brief/: a research brief on a topic, as a run (202)
    sources/                          list (filters collection, kind, status, feed, q; by cursor, newest first);
                                      POST a note (201) or a web page to capture (202: a worker fetches it)
    sources/<id>/                     one source with its text; PATCH what a person corrects; DELETE
    sources/<id>/refetch/             fetch the page again (202)
    sources/<id>/summarize/           summary, entities and passages worth quoting, as a run (202)
    sources/upload/                   a PDF, plain text or Markdown file (201)
    sources/search/                   a web search through a provider's tool, as a run (202); hits become sources
    quotes/                           CRUD (filter source)
    citations/                        list (filters page_id, brief, source), cite (201), delete
    feeds/                            subscribe (201; Celery beat refreshes it), CRUD, <id>/refresh/ (202)
    questions/                        ask (202: answered by a run, with citations), list (filter collection), one, delete
    fact-checks/                      check a draft (202: findings by a run, corrections as suggestions on the draft),
                                      list (filter page_id), one

Thin views: validate, call research/services.py, serialize. People only
(`IsPerson`): an agent works through the tool registry. Rows come from
`visible_to` alone, so one the person cannot see is a 404 and changing one they
may not change a 403. What reaches the network or a model answers 202 and
honours an `Idempotency-Key`; every failure is the error envelope.
"""

from django.db.models import Q
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from ai.serializers import RunAcceptedSerializer, RunRefSerializer
from ai.views import IDEMPOTENCY, CanEdit, OwnedViewSet, accepted, idempotent, page_or_404
from api.pages import IsPerson
from ops.errors import Invalid
from ops.openapi import ERROR_RESPONSES

from . import serializers as s
from . import services
from .models import Citation, Collection, FactCheck, FeedSubscription, Question, Quote, Source


def valid(serializer_class, request) -> dict:
    body = serializer_class(data=request.data, context={"request": request})
    body.is_valid(raise_exception=True)
    return body.validated_data


class Newest(CursorPagination):
    ordering = "-created_at"
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class PeopleViewSet(OwnedViewSet):
    """An owned row's API for people: newest first, by cursor."""

    permission_classes = [IsPerson, CanEdit]
    pagination_class = Newest
    ordering = ["-created_at"]


class CollectionViewSet(PeopleViewSet):
    queryset = Collection.objects.select_related("owner")
    serializer_class = s.CollectionSerializer
    filterset_fields = ["visibility"]
    ordering_fields = ["name", "created_at", "updated_at"]
    open_actions = ("research_brief",)

    @extend_schema(
        summary="A research brief on a topic, from the collection's sources (AIEO's), as a run",
        request=s.ResearchBriefSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: RunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"], url_path="research-brief")
    @idempotent
    def research_brief(self, request, public_id=None):
        body = valid(s.ResearchBriefSerializer, request)
        run = services.research_brief(self.get_object(), user=request.user, topic=body["topic"])
        return accepted(run=RunRefSerializer(run).data)


class SourceFilter(filters.FilterSet):
    collection = filters.UUIDFilter(field_name="collection__public_id")
    feed = filters.UUIDFilter(field_name="feed__public_id")
    q = filters.CharFilter(method="words", help_text="Words in the title, the URL or the text.")

    class Meta:
        model = Source
        fields = ["kind", "status", "collection", "feed"]

    def words(self, rows, name, value):
        return rows.filter(Q(title__icontains=value) | Q(url__icontains=value) | Q(text__icontains=value))


@extend_schema_view(
    list=extend_schema(summary="Sources, newest first (without their text)"),
    retrieve=extend_schema(summary="One source, with its extracted text"),
    partial_update=extend_schema(summary="Correct a source: its title, text, summary, collection, visibility"),
)
class SourceViewSet(PeopleViewSet):
    queryset = Source.objects.select_related("owner", "collection", "feed", "summary_run")
    filterset_class = SourceFilter
    ordering_fields = ["created_at", "updated_at", "title"]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_serializer_class(self):
        return s.SourceListSerializer if self.action == "list" else s.SourceSerializer

    def _out(self, source, code):
        return Response(s.SourceSerializer(source, context=self.get_serializer_context()).data, status=code)

    @extend_schema(
        summary="Add a note (201), or capture a web page (202: a worker fetches it)",
        request=s.SourceCreateSerializer,
        parameters=[IDEMPOTENCY],
        responses={201: s.SourceSerializer, 202: s.SourceSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def create(self, request):
        body = valid(s.SourceCreateSerializer, request)
        where = {"collection": body.get("collection"), "title": body["title"]}
        if body["kind"] == Source.NOTE:
            return self._out(services.add_note(request.user, body.get("text", ""), **where), status.HTTP_201_CREATED)
        if not body.get("url"):
            raise Invalid("capturing a web page needs its URL")
        return self._out(services.capture_url(request.user, body["url"], **where), status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="Add a document: a PDF, plain text or Markdown, read now",
        request={"multipart/form-data": s.UploadSerializer},
        responses={201: s.SourceSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        body = valid(s.UploadSerializer, request)
        source = services.upload(request.user, body["file"], collection=body.get("collection"), title=body["title"])
        return self._out(source, status.HTTP_201_CREATED)

    @extend_schema(
        summary="Search the web through a provider's search tool, as a run; each hit becomes a source to fetch",
        request=s.SearchSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: RunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"])
    @idempotent
    def search(self, request):
        body = valid(s.SearchSerializer, request)
        run = services.search_web(
            request.user,
            body["query"],
            collection=body.get("collection"),
            max_results=body["max_results"],
            provider=body["provider"],
        )
        return accepted(run=RunRefSerializer(run).data)

    @extend_schema(
        summary="Fetch a web page again", request=None, responses={202: s.SourceSerializer, **ERROR_RESPONSES}
    )
    @action(detail=True, methods=["post"])
    def refetch(self, request, public_id=None):
        source = self.get_object()
        if source.kind != Source.URL:
            raise Invalid("only a web page is fetched")
        return self._out(services.capture_again(source), status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="Summarize: a summary, the entities it names and passages worth quoting, as a run",
        request=None,
        parameters=[IDEMPOTENCY],
        responses={202: s.SourceRunSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def summarize(self, request, public_id=None):
        source = self.get_object()
        run = services.summarize(source, user=request.user)
        context = self.get_serializer_context()
        return accepted(source=s.SourceSerializer(source, context=context).data, run=RunRefSerializer(run).data)


class QuoteFilter(filters.FilterSet):
    source = filters.UUIDFilter(field_name="source__public_id")

    class Meta:
        model = Quote
        fields = ["source"]


class QuoteViewSet(viewsets.ModelViewSet):
    queryset = Quote.objects.select_related("source", "owner")
    serializer_class = s.QuoteSerializer
    lookup_field = "public_id"
    permission_classes = [IsPerson, CanEdit]
    pagination_class = Newest
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = QuoteFilter
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        return self.queryset.visible_to(self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class CitationFilter(filters.FilterSet):
    page_id = filters.NumberFilter(field_name="page", help_text="Citations on this page.")
    brief = filters.UUIDFilter(field_name="brief__public_id")
    source = filters.UUIDFilter(field_name="source__public_id")

    class Meta:
        model = Citation
        fields = ["page_id", "brief", "source"]


class CitationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Citation.objects.select_related("source", "quote", "page", "brief", "created_by")
    serializer_class = s.CitationSerializer
    lookup_field = "public_id"
    permission_classes = [IsPerson, CanEdit]
    pagination_class = Newest
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = CitationFilter

    def get_queryset(self):
        return self.queryset.visible_to(self.request.user)

    @extend_schema(summary="Cite a source (or one of its quotes) on a page you may edit, or on your brief")
    def create(self, request):
        body = valid(s.CitationSerializer, request)
        citation = services.cite(
            request.user,
            body["source"],
            page=body.get("page"),
            brief=body.get("brief"),
            quote=body.get("quote"),
            note=body.get("note", ""),
        )
        return Response(s.CitationSerializer(citation, context=self.get_serializer_context()).data, status=201)


class FeedViewSet(PeopleViewSet):
    queryset = FeedSubscription.objects.select_related("owner", "collection")
    serializer_class = s.FeedSerializer
    filterset_fields = ["active", "visibility"]
    ordering_fields = ["title", "created_at", "updated_at"]

    @extend_schema(summary="Subscribe to an RSS or Atom feed: its new items become sources, on a schedule")
    def create(self, request):
        body = valid(s.FeedSerializer, request)
        feed = services.subscribe(
            request.user,
            body["url"],
            collection=body.get("collection"),
            title=body.get("title", ""),
            interval_minutes=body.get("interval_minutes", 60),
        )
        return Response(s.FeedSerializer(feed, context=self.get_serializer_context()).data, status=201)

    @extend_schema(summary="Refresh the feed now", request=None, responses={202: s.FeedSerializer, **ERROR_RESPONSES})
    @action(detail=True, methods=["post"])
    def refresh(self, request, public_id=None):
        from .tasks import refresh_feed

        feed = self.get_object()
        services.queue(refresh_feed, feed.pk)
        return Response(s.FeedSerializer(feed, context=self.get_serializer_context()).data, status=202)


class QuestionFilter(filters.FilterSet):
    collection = filters.UUIDFilter(field_name="collection__public_id")

    class Meta:
        model = Question
        fields = ["collection"]


class QuestionViewSet(PeopleViewSet):
    queryset = Question.objects.select_related("owner", "collection", "run")
    serializer_class = s.QuestionSerializer
    filterset_class = QuestionFilter
    http_method_names = ["get", "post", "delete"]

    @extend_schema(
        summary="Ask the sources a question: answered by a run, citing them",
        parameters=[IDEMPOTENCY],
        responses={202: s.QuestionRunSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def create(self, request):
        body = valid(s.QuestionSerializer, request)
        question = services.ask(request.user, body["text"], collection=body.get("collection"))
        context = self.get_serializer_context()
        return accepted(
            question=s.QuestionSerializer(question, context=context).data, run=RunRefSerializer(question.run).data
        )


class FactCheckFilter(filters.FilterSet):
    page_id = filters.NumberFilter(field_name="page", help_text="Fact-checks of this page.")

    class Meta:
        model = FactCheck
        fields = ["page_id"]


class FactCheckViewSet(PeopleViewSet):
    queryset = FactCheck.objects.select_related("owner", "collection", "page", "run")
    serializer_class = s.FactCheckSerializer
    filterset_class = FactCheckFilter
    http_method_names = ["get", "post"]

    @extend_schema(
        summary="Fact-check a draft against its sources: findings by a run, corrections as suggestions to accept",
        request=s.FactCheckCreateSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.FactCheckRunSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def create(self, request):
        body = valid(s.FactCheckCreateSerializer, request)
        check = services.fact_check(page_or_404(body["page_id"]), user=request.user, collection=body.get("collection"))
        context = self.get_serializer_context()
        return accepted(
            fact_check=s.FactCheckSerializer(check, context=context).data, run=RunRefSerializer(check.run).data
        )
