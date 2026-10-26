"""`/api/v2/ideas/`: ideas and their boards over REST (ideas/README.md).

    /                    ideas (filters board — an id, or `none` for the inbox — status, origin, tag, q; by cursor,
                         ordered by created_at, updated_at, vote_count or title); POST one
    <id>/                one idea; PATCH (title, notes, tags, status, board, source_ids …); DELETE
    <id>/vote/           POST a vote, DELETE it — anyone who sees the idea
    <id>/merge/          fold another idea into this one
    <id>/promote/        to a brief (201, or 202 when written now), an article draft or a book draft (201)
    capture/             an idea from a line or a few, from anywhere — the studio, the editor, the extension
    brainstorm/          ask an assistant for ideas: a conversation message whose reply is a run (202)
    keep/                the ideas a person keeps from a brainstorm's reply (201)
    clusters/            groups of ideas alike in meaning and likely duplicates, from the stored vectors
    boards/              CRUD

Thin views over ideas/services.py; people only (`IsPerson`); rows from
`visible_to` alone (an idea the person cannot see is a 404, changing one they
may not change a 403); what reaches a model answers 202 and honours an
`Idempotency-Key`; every failure is the error envelope.
"""

import uuid

from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from ai.models import Brief
from ai.serializers import BriefSerializer, MessageSerializer, RunRefSerializer
from ai.views import IDEMPOTENCY, idempotent, page_or_404
from cms.services import visible_pages
from graph.embeddings import get_embedder
from ops.openapi import ERROR_RESPONSES
from research.models import Source
from research.views import PeopleViewSet, valid

from . import serializers as s
from . import services
from .models import Board, Idea, Vote


class BoardViewSet(PeopleViewSet):
    queryset = Board.objects.select_related("owner")
    serializer_class = s.BoardSerializer
    filterset_fields = ["visibility"]
    ordering_fields = ["name", "created_at", "updated_at"]


class IdeaFilter(filters.FilterSet):
    board = filters.CharFilter(method="on_board", help_text="A board's id, or `none` for the inbox.")
    tag = filters.CharFilter(field_name="tags__name", distinct=True)
    q = filters.CharFilter(method="words", help_text="Words in the title or the notes.")

    class Meta:
        model = Idea
        fields = ["status", "origin", "board", "tag"]

    def on_board(self, rows, name, value):
        if value == "none":
            return rows.filter(board__isnull=True)
        try:
            return rows.filter(board__public_id=uuid.UUID(value))
        except ValueError:
            return rows.none()  # not an id: no board has it

    def words(self, rows, name, value):
        return rows.filter(Q(title__icontains=value) | Q(notes__icontains=value))


@extend_schema_view(
    list=extend_schema(summary="Ideas you can see, newest first"),
    partial_update=extend_schema(summary="Change an idea: move it, retitle it, tag it, link sources"),
)
class IdeaViewSet(PeopleViewSet):
    queryset = Idea.objects.select_related("owner", "board", "brief", "page", "source_message").prefetch_related("tags")
    serializer_class = s.IdeaSerializer
    filterset_class = IdeaFilter
    ordering_fields = ["created_at", "updated_at", "vote_count", "title"]
    open_actions = ("vote",)
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        """Ideas the person sees, each with the sources, brief and page it links to as far as they see those too."""
        user = self.request.user
        mine = Vote.objects.filter(idea=OuterRef("pk"), user=user)
        seen = Prefetch("sources", queryset=Source.objects.visible_to(user), to_attr="seen_sources")
        return (
            super()
            .get_queryset()
            .prefetch_related(seen)
            .annotate(
                vote_count=Count("votes", distinct=True),
                my_vote=Exists(mine),
                brief_seen=Exists(Brief.objects.visible_to(user).filter(pk=OuterRef("brief_id"))),
                page_seen=Exists(visible_pages(user).filter(pk=OuterRef("page_id"))),
            )
        )

    def _out(self, idea, code=status.HTTP_200_OK):
        fresh = self.get_queryset().get(pk=idea.pk)
        return Response(s.IdeaSerializer(fresh, context=self.get_serializer_context()).data, status=code)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return self._out(serializer.instance, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        super().partial_update(request, *args, **kwargs)
        return self._out(self.get_object())

    @extend_schema(
        summary="Capture an idea: the first line is its title, the rest its notes (or a template's)",
        request=s.CaptureSerializer,
        responses={201: s.IdeaSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"])
    def capture(self, request):
        body = valid(s.CaptureSerializer, request)
        idea = services.capture(
            request.user,
            body["text"],
            board=body.get("board"),
            url=body.get("url", ""),
            tags=body.get("tags", []),
            template=body.get("template", ""),
        )
        return self._out(idea, status.HTTP_201_CREATED)

    @extend_schema(
        summary="Brainstorm with an assistant: a message whose reply, a run, lists ideas to keep",
        request=s.BrainstormSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.BrainstormedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"])
    @idempotent
    def brainstorm(self, request):
        body = valid(s.BrainstormSerializer, request)
        conversation, message, reply, run = services.brainstorm(
            request.user,
            body["prompt"],
            kind=body.get("kind", "angles"),
            count=body.get("count", 8),
            board=body.get("board"),
            conversation=body.get("conversation"),
            sources=body.get("sources") or (),
            assistant=body.get("assistant"),
        )
        context = self.get_serializer_context()
        return Response(
            {
                "conversation": conversation.public_id,
                "message": MessageSerializer(message, context=context).data,
                "reply": MessageSerializer(reply, context=context).data,
                "run": RunRefSerializer(run).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        summary="Keep ideas from a brainstorm's reply",
        request=s.KeepSerializer,
        responses={201: s.KeptSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"])
    def keep(self, request):
        body = valid(s.KeepSerializer, request)
        kept = services.keep(body["message"], user=request.user, picks=body.get("picks"), board=body.get("board"))
        rows = self.get_queryset().filter(pk__in=[i.pk for i in kept])
        data = s.IdeaSerializer(rows, many=True, context=self.get_serializer_context()).data
        return Response({"ideas": data}, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Ideas alike in meaning, and likely duplicates, from the stored vectors",
        parameters=[
            OpenApiParameter("board", OpenApiTypes.STR, description="A board's id, or `none` for the inbox."),
            OpenApiParameter("status", OpenApiTypes.STR),
            OpenApiParameter("threshold", OpenApiTypes.FLOAT, description="How alike a cluster's ideas are (0–1)."),
        ],
        responses={200: s.ClustersSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["get"], filter_backends=[filters.DjangoFilterBackend])
    def clusters(self, request):
        try:
            threshold = float(request.query_params["threshold"]) if "threshold" in request.query_params else None
        except ValueError:
            threshold = None
        rows = self.filter_queryset(self.get_queryset()).exclude(status=Idea.ARCHIVED).order_by("-created_at")
        found = services.clusters(rows, threshold=threshold)
        ref = s.IdeaRefSerializer
        return Response(
            {
                "model": get_embedder().model,
                "clusters": [{"ideas": ref(group, many=True).data} for group in found["clusters"]],
                "duplicates": [
                    {"a": ref(a).data, "b": ref(b).data, "similarity": similarity}
                    for a, b, similarity in found["duplicates"]
                ],
                "pending": ref(found["pending"], many=True).data,
            }
        )

    @extend_schema(methods=["POST"], summary="Vote for the idea", request=None, responses={200: s.IdeaSerializer})
    @extend_schema(methods=["DELETE"], summary="Take your vote back", request=None, responses={200: s.IdeaSerializer})
    @action(detail=True, methods=["post", "delete"])
    def vote(self, request, public_id=None):
        idea = self.get_object()
        services.vote(idea, request.user, up=request.method == "POST")
        return self._out(idea)

    @extend_schema(
        summary="Fold another idea into this one: notes, tags, sources and votes come along",
        request=s.MergeSerializer,
        responses={200: s.IdeaSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    def merge(self, request, public_id=None):
        body = valid(s.MergeSerializer, request)
        return self._out(services.merge(self.get_object(), body["other"], user=request.user))

    @extend_schema(
        summary="Promote: to a brief (written now with `generate`, 202), an article draft or a book draft",
        request=s.PromoteIdeaSerializer,
        parameters=[IDEMPOTENCY],
        responses={201: s.PromotedIdeaSerializer, 202: s.PromotedIdeaSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def promote(self, request, public_id=None):
        body = valid(s.PromoteIdeaSerializer, request)
        idea, brief, page, run = services.promote(
            self.get_object(),
            user=request.user,
            to=body["into"],
            parent=page_or_404(body.get("parent")),
            assistant=body.get("assistant"),
            generate=body.get("generate", False),
        )
        context = self.get_serializer_context()
        data = {
            "idea": s.IdeaSerializer(self.get_queryset().get(pk=idea.pk), context=context).data,
            "brief": BriefSerializer(brief, context=context).data if brief else None,
            "page_id": page.pk if page else None,
            "run": RunRefSerializer(run).data if run else None,
        }
        return Response(data, status=status.HTTP_202_ACCEPTED if run else status.HTTP_201_CREATED)
