"""The OpenAPI document's scope and the envelope's schema (UPS-BE-12, BE-31).

drf-spectacular walks a URLconf; this one holds the platform's own REST
endpoints (`api/urls.py` `urlpatterns`, the AI content layer's router,
`ai/urls.py`, and the ideas and research routers, `ideas/urls.py` and
`research/urls.py`) and nothing else. Wagtail's
`pages`/`images`/`documents` viewsets build their serializer per request
(`get_serializer_class` reads `self.request`), which no static generator can
introspect, so they are documented by Wagtail itself and left out here. The
probes are root-level, not `/api/v2`, so they stay out too.

`urlpatterns` is built when first read (a module `__getattr__`), not at
import: the API's views import `ERROR_RESPONSES` from here, so an eager
`include("api.urls")` made importing a view before the URLconf an import cycle.
"""

from django.urls import include, path
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import serializers


def __getattr__(name):
    if name == "urlpatterns":
        return [
            path("api/v2/ai/", include("ai.urls")),
            path("api/v2/ideas/", include("ideas.urls")),
            path("api/v2/research/", include("research.urls")),
            path("api/v2/", include("api.urls")),
        ]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class AgentTokenScheme(OpenApiAuthenticationExtension):
    """How `agents.auth.AgentTokenAuthentication` appears in the document."""

    target_class = "agents.auth.AgentTokenAuthentication"
    name = "agentToken"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "zer0_…",
            "description": "An agent token (`manage.py agent_token <slug> --name …`); the caller acts as that agent user.",
        }


class ErrorDetailSerializer(serializers.Serializer):
    field = serializers.CharField(allow_null=True, help_text="The field at fault, or null for the whole request.")
    code = serializers.CharField()
    message = serializers.CharField()


class ErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="`<domain>.<reason>`, stable across releases (ops/README.md).")
    message = serializers.CharField()
    status = serializers.IntegerField()
    details = ErrorDetailSerializer(many=True)
    request_id = serializers.CharField(allow_null=True)
    retry_after = serializers.IntegerField(allow_null=True)


class ErrorEnvelopeSerializer(serializers.Serializer):
    error = ErrorSerializer()


ERROR_RESPONSES = {status: ErrorEnvelopeSerializer for status in (401, 403, 404, 405, 409, 422, 429, 500)}
