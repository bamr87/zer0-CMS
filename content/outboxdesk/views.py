"""`/api/v2/outbox/`: the outbox desk over REST (outboxdesk/README.md).

    belt/                         the belt's summary: delivered, dead letters, traces, kinds, pending, stations
    belt/messages/                delivered messages, newest first (filters kind, station, trace; `ordering=seq`)
    belt/messages/<id>/           one message, with its CloudEvents form
    belt/traces/<trace>/          a piece of work's journey, in relay order
    belt/dead-letters/            what the relay refused, and why
    belt/send/                    a handoff from the editor station: idea, approval or signal (201)
    belt/deliver/                 run the relay now, in the worker (202; the summary's `pending` follows it)
    trials/                       arena trials, newest first; POST a task card to run one in the worker (202)
    trials/<id>/                  one trial: where it stands, its result, the arena's ledger
    claim-checks/                 claim desk checks, newest first; POST claims and a timeline to check (202)
    claim-checks/<id>/            one check: its verdicts, and its resolutions once resolved
    claim-checks/<id>/resolve/    give the truth; the worker re-scores each claim (202)
    claim-checks/calibration/     mean Brier per verifier and per author, over every resolved check

Thin views over outboxdesk/services.py, for people only (`IsPerson`), each behind the Django permission its
action names (`Allowed`, `perms`): the belt's `outboxdesk.view_belt`, `send_handoff` and `deliver_belt`, and the
model permissions of trials and claim checks. What runs the harness answers 202 and runs in the worker, followed by
reading the row (or the summary) again; a request that starts one honours an `Idempotency-Key`. Every failure is
the error envelope; a harness that cannot load is a 503 (`outbox.unavailable`).
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.views import IDEMPOTENCY, Paged, idempotent
from api.pages import IsPerson
from ops.openapi import ERROR_RESPONSES
from research.views import valid

from . import serializers as s
from . import services
from .models import ClaimCheck, Trial


class Allowed(BasePermission):
    """The Django permission a view names for what is asked of it (`perms`: by action, else by method)."""

    message = "this needs a permission of the outbox desk you do not hold"

    def has_permission(self, request, view):
        perms = view.perms
        perm = perms.get(getattr(view, "action", None) or "", perms.get(request.method))
        return perm is not None and request.user.has_perm(perm)


# What every desk view shares: people only, each behind the permission it names (reading the belt by default). A
# comment, not a docstring: drf-spectacular would give every view's operation that text as its description.
class Desk:
    permission_classes = [IsPerson, Allowed]
    perms: dict[str, str] = {"GET": "outboxdesk.view_belt"}


# ── the belt ───────────────────────────────────────────────────────────────


class Summary(Desk, APIView):
    @extend_schema(
        summary="The belt: what it delivered, refused and still holds",
        responses={200: s.BeltSummarySerializer, **ERROR_RESPONSES},
    )
    def get(self, request):
        return Response(s.BeltSummarySerializer(services.summary()).data)


@extend_schema_view(
    get=extend_schema(
        summary="Delivered messages, newest first",
        parameters=[
            OpenApiParameter("kind", OpenApiTypes.STR, enum=s.KINDS),
            OpenApiParameter("station", OpenApiTypes.STR, description="Sent by or to this station."),
            OpenApiParameter("trace", OpenApiTypes.STR, description="One piece of work's messages."),
            OpenApiParameter("ordering", OpenApiTypes.STR, enum=["seq", "-seq"], description="`seq`: oldest first."),
        ],
    )
)
class Messages(Desk, generics.ListAPIView):
    serializer_class = s.HandoffSerializer
    pagination_class = Paged

    def get_queryset(self):
        query = self.request.query_params
        return services.messages(
            kind=query.get("kind", ""),
            station=query.get("station", ""),
            trace=query.get("trace", ""),
            oldest_first=query.get("ordering") == "seq",
        )


class OneMessage(Desk, APIView):
    @extend_schema(
        summary="A delivered message, and its CloudEvents form",
        responses={200: s.BeltMessageSerializer, **ERROR_RESPONSES},
    )
    def get(self, request, message_id):
        return Response(s.BeltMessageSerializer(services.message(message_id)).data)


class Journey(Desk, APIView):
    @extend_schema(
        summary="A piece of work's journey: its messages in relay order",
        responses={200: s.JourneySerializer, **ERROR_RESPONSES},
    )
    def get(self, request, trace):
        return Response(s.JourneySerializer({"trace": trace, "messages": services.journey(trace)}).data)


class DeadLetters(Desk, APIView):
    @extend_schema(
        summary="What the relay refused, newest first",
        responses={200: s.DeadLetterSerializer(many=True), **ERROR_RESPONSES},
    )
    def get(self, request):
        return Response(s.DeadLetterSerializer(services.dead_letters(), many=True).data)


class Send(Desk, APIView):
    perms = {"POST": "outboxdesk.send_handoff"}

    @extend_schema(
        summary="Send a handoff as the editor station: an idea, an approval of a delivered message, or a signal",
        request=s.SendSerializer,
        responses={201: s.HandoffSerializer, **ERROR_RESPONSES},
    )
    def post(self, request):
        body = valid(s.SendSerializer, request)
        sent = services.send(
            request.user,
            kind=body["kind"],
            to=body["to"],
            subject=body.get("subject", ""),
            payload=body.get("payload"),
            parent_id=body.get("parent_id", ""),
            trace=body.get("trace", ""),
            ref=body.get("ref"),
            page=body.get("page"),
        )
        return Response(s.HandoffSerializer(sent).data, status=status.HTTP_201_CREATED)


class Deliver(Desk, APIView):
    perms = {"POST": "outboxdesk.deliver_belt"}

    @extend_schema(
        summary="Run the relay now, in the worker; the summary's `pending` follows it",
        request=None,
        responses={202: s.QueuedDeliverySerializer, **ERROR_RESPONSES},
    )
    def post(self, request):
        return Response({"pending": services.ask_delivery()}, status=status.HTTP_202_ACCEPTED)


# ── trials and claim checks ────────────────────────────────────────────────


class Runs(Desk, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_field = "public_id"
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    pagination_class = Paged

    def get_queryset(self):
        return self.queryset.select_related("requested_by")


@extend_schema_view(
    list=extend_schema(summary="Arena trials, newest first"),
    retrieve=extend_schema(
        summary="A trial: where it stands, its result and the arena's ledger",
        responses={200: s.TrialDetailSerializer, **ERROR_RESPONSES},
    ),
)
class TrialViewSet(Runs):
    queryset = Trial.objects.all()
    perms = {"list": "outboxdesk.view_trial", "retrieve": "outboxdesk.view_trial", "create": "outboxdesk.add_trial"}

    def get_serializer_class(self):
        return s.TrialDetailSerializer if self.action == "retrieve" else s.TrialSerializer

    @extend_schema(
        summary="Run an arena trial from a task card, in the worker",
        request=s.StartTrialSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.TrialSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def create(self, request):
        body = valid(s.StartTrialSerializer, request)
        trial = services.start_trial(request.user, body["task"], body.get("lag_b"))
        return Response(s.TrialSerializer(trial).data, status=status.HTTP_202_ACCEPTED)


@extend_schema_view(
    list=extend_schema(summary="Claim checks, newest first"),
    retrieve=extend_schema(
        summary="A claim check: its verdicts, and its resolutions once resolved",
        responses={200: s.ClaimCheckDetailSerializer, **ERROR_RESPONSES},
    ),
)
class ClaimCheckViewSet(Runs):
    queryset = ClaimCheck.objects.select_related("page")
    perms = {
        "list": "outboxdesk.view_claimcheck",
        "retrieve": "outboxdesk.view_claimcheck",
        "calibration": "outboxdesk.view_claimcheck",
        "create": "outboxdesk.add_claimcheck",
        "resolve": "outboxdesk.change_claimcheck",
    }

    def get_serializer_class(self):
        return s.ClaimCheckDetailSerializer if self.action == "retrieve" else s.ClaimCheckSerializer

    @extend_schema(
        summary="Check a draft's claims against their sources' timeline, in the worker (the desk never edits a page)",
        request=s.StartClaimCheckSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.ClaimCheckSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def create(self, request):
        body = valid(s.StartClaimCheckSerializer, request)
        check = services.start_claim_check(request.user, **body)
        return Response(s.ClaimCheckSerializer(check).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="Resolve a check against the truth, in the worker: who was right, and Brier scores",
        request=s.ResolveSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.ClaimCheckDetailSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def resolve(self, request, public_id=None):
        body = valid(s.ResolveSerializer, request)
        check = services.ask_resolution(self.get_object(), body["truth"])
        return Response(s.ClaimCheckDetailSerializer(check).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="Calibration: mean Brier per verifier and per draft author, over every resolved check",
        responses={200: s.CalibrationSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def calibration(self, request):
        return Response(s.CalibrationSerializer(services.calibration()).data)
