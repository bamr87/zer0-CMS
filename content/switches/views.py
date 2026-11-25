"""`/api/v2/switches/`: the content outlets' switches for the studio's Content switches section (switches/README.md).

    GET   /api/v2/switches/           the hub's map, the credential's state, and every outlet's switches as set now
    GET   /api/v2/switches/config/    the outlets and whether a credential is set
    PATCH /api/v2/switches/config/    change the outlets, set or remove the credential (write-only)
    POST  /api/v2/switches/preview/   what a flip would write — one switch, or every switch of an outlet; writes nothing
    POST  /api/v2/switches/apply/     the flip a person previewed and confirmed, with a reason (202: the job)

All of it is for people who manage sites (`sites.manage_site`; a superuser holds it): the variables are read with the
platform's credential, which GitHub gives only to a repository's collaborators, so nobody else is shown them. Thin
views over switches/services.py. Apply needs `confirm: true`, a reason and the preview's digest, and is refused
(409) when what a flip would write changed since.
"""

from contextlib import contextmanager

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.views import IDEMPOTENCY, idempotent
from api.pages import IsPerson
from ops.errors import Conflict, Forbidden, Invalid
from ops.openapi import ERROR_RESPONSES
from sites.access import MANAGE

from . import serializers as s
from . import services
from .models import SwitchConfig


def _manager(request) -> None:
    if not request.user.has_perm(MANAGE):
        raise Forbidden("the content switches are for people who manage sites (sites.manage_site)")


def _valid(serializer_class, request) -> dict:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


@contextmanager
def refusals():
    try:
        yield
    except services.Changed as e:
        raise Conflict(str(e), code="switches.changed") from e
    except services.SwitchError as e:
        raise Invalid(str(e)) from e


def _config_json(config: SwitchConfig) -> dict:
    return {"outlets": config.outlets, "has_credential": config.has_credential, "updated_at": config.updated_at}


class Board(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="switches_board",
        summary="Every outlet's switches as set now, against the hub's switch map",
        responses={200: s.SwitchBoardSerializer, **ERROR_RESPONSES},
    )
    def get(self, request):
        _manager(request)
        return Response(s.SwitchBoardSerializer(services.board()).data)


class Config(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="switches_config",
        responses={200: s.SwitchConfigSerializer, **ERROR_RESPONSES},
    )
    def get(self, request):
        _manager(request)
        return Response(s.SwitchConfigSerializer(_config_json(SwitchConfig.load())).data)

    @extend_schema(
        operation_id="switches_config_update",
        summary="Change the outlets; set or remove the credential (never returned)",
        request=s.SwitchConfigSerializer,
        responses={200: s.SwitchConfigSerializer, **ERROR_RESPONSES},
    )
    def patch(self, request):
        _manager(request)
        data = _valid(s.SwitchConfigSerializer, request)
        config = SwitchConfig.load()
        if "outlets" in data:
            config.outlets = data["outlets"]
        if "credential" in data:
            config.set_credential(data["credential"])
        config.updated_by = request.user
        config.save()
        return Response(s.SwitchConfigSerializer(_config_json(config)).data)


class Preview(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="switches_preview",
        summary="What a flip would write, read from GitHub now; writes nothing",
        request=s.SwitchFlipSerializer,
        responses={200: s.SwitchPreviewSerializer, **ERROR_RESPONSES},
    )
    def post(self, request):
        _manager(request)
        data = _valid(s.SwitchFlipSerializer, request)
        with refusals():
            body = services.preview(data["repo"], target=data["target"], switch=data["switch"], reason=data["reason"])
        return Response(s.SwitchPreviewSerializer(body).data)


class Apply(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="switches_apply",
        summary="Apply a previewed, confirmed flip with its reason (a job: set, read back, recorded as an event)",
        request=s.SwitchApplySerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.SwitchFlipAcceptedSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def post(self, request):
        _manager(request)
        data = _valid(s.SwitchApplySerializer, request)
        with refusals():
            job = services.apply(
                data["repo"],
                target=data["target"],
                switch=data["switch"],
                reason=data["reason"],
                digest=data["digest"],
                user=request.user,
            )
        return Response(s.SwitchFlipAcceptedSerializer({"job": job}).data, status=status.HTTP_202_ACCEPTED)
