"""The review inbox: every pending suggestion a person may decide, with its diff.

    GET  /api/v2/review/suggestions/             pending suggestions across sites, newest first, each
                                                 with its change as before/after text (filters: site,
                                                 target, run, agent)
    POST /api/v2/review/runs/<run_id>/accept/    accept everything a run proposed — one revision per page

A single suggestion is accepted or rejected (with a reason) through the
existing `/api/v2/suggestions/<id>/accept|reject/`. Everything here goes
through `suggestions.services`, which re-checks the person's rights and the
page's current state at decision time; the diff is measured against the
page's latest revision, so a suggestion whose block has gone says so
(`change.stale`) before anyone tries to accept it.
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
from ops.errors import Conflict, NotFound
from ops.openapi import ERROR_RESPONSES
from suggestions.models import Suggestion
from suggestions.services import SuggestionError, accept_run, decidable, describe

from .pages import IsPerson, StudioPagination
from .serializers import AcceptedRunSerializer, SuggestionSerializer


class InboxFilter(django_filters.FilterSet):
    site = django_filters.NumberFilter(method="by_site", help_text="A site id: suggestions on its pages.")
    target = django_filters.NumberFilter(field_name="target_id", help_text="A page (or image) id.")
    run = django_filters.NumberFilter(field_name="run_id")
    agent = django_filters.CharFilter(field_name="agent__slug")

    def by_site(self, qs, name, value: int):
        site = Site.objects.filter(pk=value).select_related("root_page").first()
        if site is None:
            return qs.none()
        pages = Page.objects.descendant_of(site.root_page, inclusive=True).values("pk")
        return qs.filter(target_id__in=pages).exclude(target_ct__model="contentimage")


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
        return decidable(self.request.user).order_by("-created_at", "-id")

    @extend_schema(operation_id="review_suggestions", summary="Pending suggestions the caller may decide, with diffs")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        rows = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        targets: dict = {}
        return self.get_paginated_response(SuggestionSerializer([_row(s, targets) for s in rows], many=True).data)


@extend_schema(
    operation_id="review_runs_accept",
    summary="Accept every pending suggestion of a run, one revision per page",
    request=None,
    responses={200: AcceptedRunSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([IsPerson])
def accept_all(request, run_id):
    run = AgentRun.objects.filter(pk=run_id).first()
    if run is None:
        raise NotFound(f"no run {run_id}")
    ids = list(run.suggestions.filter(status=Suggestion.PENDING).values_list("pk", flat=True))
    try:
        results = accept_run(run, request.user)
    except SuggestionError as e:
        raise Conflict(str(e)) from e
    revisions = [r.pk for r in results if isinstance(r, Revision)]
    return Response(AcceptedRunSerializer({"accepted": ids, "revision_ids": revisions}).data)
