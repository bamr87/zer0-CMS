"""The review inbox: every pending suggestion a person may decide, with its diff.

    GET  /api/v2/review/suggestions/             pending suggestions across sites, newest first, each
                                                 with its change as before/after text (filters: site,
                                                 page_id, run, agent)
    POST /api/v2/review/runs/<run_id>/accept/    accept the suggestions of a run the person saw
                                                 (`ids`) — one revision per page

A single suggestion is accepted or rejected (with a reason) through the
existing `/api/v2/suggestions/<id>/accept|reject/`. Everything here reads
through the one scope (`Suggestion.objects.visible_to`, `AgentRun.objects.
visible_to`) and decides through `suggestions.services`, which re-checks the
person's rights, the page's lock and its current state at decision time; the
diff is measured against the page's latest revision, so a suggestion whose
block has gone says so (`change.stale`) before anyone tries to accept it. A
run the person may not see is a 404, and a refusal never names a page they
cannot open.
"""

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from wagtail.models import Page, Revision, Site

from agents.models import AgentRun
from cms.models import BasePage
from ops.errors import NotFound
from ops.openapi import ERROR_RESPONSES
from suggestions.models import Suggestion
from suggestions.services import accept_run, describe

from .pages import IsPerson, StudioPagination, _valid, service_errors
from .serializers import AcceptedRunSerializer, AcceptRunSerializer, SuggestionSerializer


class InboxFilter(django_filters.FilterSet):
    site = django_filters.NumberFilter(method="by_site", help_text="A site id: suggestions on its pages.")
    page_id = django_filters.NumberFilter(method="by_page", help_text="A page id: the suggestions on that page.")
    run = django_filters.NumberFilter(field_name="run_id")
    agent = django_filters.CharFilter(field_name="agent__slug")

    def by_site(self, qs, name, value: int):
        site = Site.objects.filter(pk=value).select_related("root_page").first()
        return qs.visible_to(self.request.user, site) if site else qs.none()

    def by_page(self, qs, name, value: int):
        return qs.on_pages(Page.objects.filter(pk=value))


def _row(suggestion: Suggestion, targets: dict) -> dict:
    key = (suggestion.target_ct_id, suggestion.target_id)
    if key not in targets:
        target = suggestion.target
        latest = target.get_latest_revision_as_object() if isinstance(target, BasePage) else target
        targets[key] = (target, latest)
    target, latest = targets[key]
    is_page = isinstance(target, BasePage)
    if target is None:
        change = {"kind": "block", "label": "the target is gone", "before": "", "after": "", "stale": True}
    else:
        change = describe(suggestion, latest)
    return {
        "id": suggestion.pk,
        "op": suggestion.op,
        "block_id": suggestion.block_id,
        "field": suggestion.field,
        "payload": suggestion.payload,
        "rationale": suggestion.rationale,
        "status": suggestion.status,
        "agent": suggestion.agent.slug if suggestion.agent else None,
        "run_id": suggestion.run_id,
        "created_at": suggestion.created_at,
        "target": {
            "type": "page" if is_page or target is None else "image",
            "id": suggestion.target_id,
            "title": (latest.title if is_page else getattr(target, "title", "")) or f"#{suggestion.target_id}",
        },
        "change": change,
    }


class Inbox(generics.ListAPIView):
    permission_classes = [IsPerson]
    serializer_class = SuggestionSerializer
    pagination_class = StudioPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = InboxFilter

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Suggestion.objects.none()
        return (
            Suggestion.objects.visible_to(self.request.user)
            .filter(status=Suggestion.PENDING)
            .select_related("agent", "run", "target_ct")
            .order_by("-created_at", "-id")
        )

    @extend_schema(operation_id="review_suggestions", summary="Pending suggestions the caller may decide, with diffs")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        rows = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        targets: dict = {}
        return self.get_paginated_response(SuggestionSerializer([_row(s, targets) for s in rows], many=True).data)


@extend_schema(
    operation_id="review_runs_accept",
    summary="Accept the suggestions of a run the caller saw, one revision per page",
    request=AcceptRunSerializer,
    responses={200: AcceptedRunSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([IsPerson])
def accept_all(request, run_id):
    run = AgentRun.objects.visible_to(request.user).filter(pk=run_id).first()
    if run is None:
        raise NotFound(f"no run {run_id}")
    data = _valid(AcceptRunSerializer, request)
    with service_errors():
        accepted, results = accept_run(run, request.user, data["ids"])
    revisions = [r.pk for r in results if isinstance(r, Revision)]
    return Response(AcceptedRunSerializer({"accepted": [s.pk for s in accepted], "revision_ids": revisions}).data)
