"""`/api/v2/sites/<id>/voice/`: a site's voice as the platform holds it today (voice/README.md, ADR 0010 V0).

    GET   /api/v2/sites/<id>/voice/resolved/   every layer that holds (?page=<id>, ?channel=<public id>), who reads it
    POST  /api/v2/sites/<id>/voice/test/       the brand guard's findings on a text under that resolution

Read-only, for people only, and nothing here reaches a model. A site the
caller does not see is a 404, as everywhere in /api/v2/sites/; a page is one
the caller may open (api/pages.py: edit or publish it) on that site, and a
channel one of the site's channels they see, else a 404. AIEO's brand context
is shown only to the site's editors (aieo/services.py `editor_of`): to anyone
else its layer is there, `hidden`, with nothing in it.
"""

import uuid

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.models import Assistant
from aieo.services import editor_of
from api.pages import IsPerson
from api.pages import _page as page_for
from distribution.models import Channel
from ops.errors import Invalid, NotFound
from ops.openapi import ERROR_RESPONSES
from sites.access import visible_sites
from suggestions.guard import builtin_bans, page_findings

from . import serializers as s
from . import services


def _site(request, pk):
    site = visible_sites(request.user).filter(pk=pk).first()
    if site is None:
        raise NotFound("no such site")
    return site


def _page(request, site, pk):
    if pk in (None, ""):
        return None
    try:
        page = page_for(request, int(pk))
    except (TypeError, ValueError):
        raise Invalid("page is a page id") from None
    if page.get_site() != site:
        raise NotFound(f"no page {pk}")
    return page


def _channel(request, site, public_id):
    if public_id in (None, ""):
        return None
    try:
        public_id = uuid.UUID(str(public_id))
    except ValueError:
        raise NotFound(f"no channel {public_id}") from None
    channel = Channel.objects.visible_to(request.user, site).filter(public_id=public_id).first()
    if channel is None:
        raise NotFound(f"no channel {public_id}")
    return channel


def _resolved(request, site, page, channel) -> dict:
    resolved = services.resolve(site, page=page, channel=channel)
    try:
        editor_of(request.user, site)
    except NotFound:
        for layer in resolved["layers"]:
            if layer["key"] == "aieo":
                layer.update(guidance=[], hidden=True)
    return resolved


class Resolved(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="sites_voice_resolved",
        summary="A site's voice for a page or a channel: every layer that holds, in order, and who reads each",
        parameters=[
            OpenApiParameter("page", int, description="A page of the site the caller may open."),
            OpenApiParameter("channel", str, description="The public id of one of the site's channels."),
        ],
        responses={200: s.ResolvedVoiceSerializer, **ERROR_RESPONSES},
    )
    def get(self, request, pk):
        site = _site(request, pk)
        page = _page(request, site, request.query_params.get("page"))
        channel = _channel(request, site, request.query_params.get("channel"))
        resolved = _resolved(request, site, page, channel)
        assistants = Assistant.objects.visible_to(request.user, site).order_by("name")
        body = {
            "page": {"id": page.pk, "title": page.title, "type": type(page).__name__} if page else None,
            "channel": {"id": channel.public_id, "name": channel.name, "kind": channel.kind} if channel else None,
            "layers": resolved["layers"],
            "digest": resolved["digest"],
            "told": services.told(resolved),
            "assistants": [
                {"id": a.public_id, "name": a.name, "reads_voice": "brand.rules" in (a.tools or [])} for a in assistants
            ],
            "readers": [{"key": key, "label": label} for key, label in services.READERS.items()],
        }
        return Response(s.ResolvedVoiceSerializer(body).data)


class Test(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="sites_voice_test",
        summary="The brand guard's findings on a text under the site's voice for a page or a channel (no model)",
        request=s.VoiceTestRequestSerializer,
        responses={200: s.VoiceTestSerializer, **ERROR_RESPONSES},
    )
    def post(self, request, pk):
        from distribution.services import guard as post_guard

        site = _site(request, pk)
        body = s.VoiceTestRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        page = _page(request, site, data.get("page"))
        channel = _channel(request, site, data.get("channel"))
        if channel is not None:
            findings = post_guard(data["text"], channel)
        else:
            findings = page_findings(data["text"], site=site, builtin=builtin_bans(page))
        resolved = services.resolve(site, page=page, channel=channel)
        return Response(s.VoiceTestSerializer({"findings": findings, "digest": resolved["digest"]}).data)
