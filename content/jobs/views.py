"""`/api/v2/jobs/`: the jobs a person may see, one job with its log, its log as
server-sent events while it runs, its artifacts, and cancel.

    GET  /api/v2/jobs/                          newest first, by cursor; ?site=, ?kind=, ?status=
    GET  /api/v2/jobs/<id>/                     the job, its artifacts and its whole log
    GET  /api/v2/jobs/<id>/stream/              the log as it is written (`line` events), then `status` and `end`
    POST /api/v2/jobs/<id>/cancel/              cancel a queued job, or ask a running one to stop
    GET  /api/v2/jobs/<id>/artifacts/<name>/    one artifact, as its media type

Jobs are started where their subject lives (a site's `sync/`, `export/` and
`doctor/`, sites/views.py), never here. A job a person may not see is a 404.
The stream follows an agent run's (api/views.py): it opens with a comment
frame, sends a comment when quiet, and ends when the job does or after
`timeout` seconds, when the client opens it again after the last line it has.
"""

import json
import time

import django_filters
from django.http import HttpResponse, StreamingHttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.decorators import api_view, permission_classes, renderer_classes
from rest_framework.pagination import CursorPagination
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from api.pages import IsPerson
from api.views import KEEPALIVE_SECONDS, EventStreamRenderer
from ops.errors import Conflict, NotFound
from ops.openapi import ERROR_RESPONSES

from . import services
from .models import Job, JobLine
from .serializers import JobDetailSerializer, JobLineSerializer, JobSerializer


def visible_job(request, public_id) -> Job:
    job = Job.objects.visible_to(request.user).filter(public_id=public_id).first()
    if job is None:
        raise NotFound("no such job")
    return job


class Newest(CursorPagination):
    ordering = "-created_at"
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class JobFilter(django_filters.FilterSet):
    site = django_filters.NumberFilter(field_name="site_id", help_text="A Wagtail site id: that site's jobs.")
    kind = django_filters.CharFilter(help_text="sync, export, doctor, …")
    status = django_filters.ChoiceFilter(choices=Job.Status.choices)

    class Meta:
        model = Job
        fields = ["site", "kind", "status"]


class JobList(generics.ListAPIView):
    permission_classes = [IsPerson]
    serializer_class = JobSerializer
    pagination_class = Newest
    filter_backends = [DjangoFilterBackend]
    filterset_class = JobFilter

    def get_queryset(self):
        return Job.objects.visible_to(self.request.user).prefetch_related("artifacts").select_related("created_by")

    @extend_schema(operation_id="jobs_list", summary="The jobs the caller may see, newest first")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


@extend_schema(operation_id="jobs_retrieve", responses={200: JobDetailSerializer, **ERROR_RESPONSES})
@api_view(["GET"])
@permission_classes([IsPerson])
def job_detail(request, public_id):
    return Response(JobDetailSerializer(visible_job(request, public_id)).data)


@extend_schema(
    operation_id="jobs_cancel",
    summary="Cancel a queued job, or ask a running one to stop",
    request=None,
    responses={200: JobSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([IsPerson])
def job_cancel(request, public_id):
    try:
        job = services.cancel(visible_job(request, public_id))
    except services.NotCancellable as e:
        raise Conflict(str(e), code="job.final") from e
    return Response(JobSerializer(job).data)


@extend_schema(
    operation_id="jobs_artifact",
    summary="One artifact of a job, as its media type",
    responses={(200, "text/plain"): OpenApiTypes.STR, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsPerson])
def job_artifact(request, public_id, name):
    artifact = visible_job(request, public_id).artifacts.filter(name=name).first()
    if artifact is None:
        raise NotFound("no such artifact")
    response = HttpResponse(artifact.content, content_type=f"{artifact.media_type}; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{artifact.name}"'
    return response


@extend_schema(
    operation_id="jobs_stream",
    summary="A job's log as server-sent events",
    description="`line` events (a JobLine) as the job writes them, then one `status` event and `end`.",
    parameters=[
        OpenApiParameter("after", OpenApiTypes.INT, description="Send only lines after this index."),
        OpenApiParameter("timeout", OpenApiTypes.NUMBER, description="Seconds to hold the stream (at most 300)."),
    ],
    responses={(200, "text/event-stream"): OpenApiTypes.STR, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsPerson])
@renderer_classes([JSONRenderer, EventStreamRenderer])
def job_stream(request, public_id):
    job = visible_job(request, public_id)
    timeout = min(float(request.query_params.get("timeout", 60)), 300)
    try:
        sent = int(request.query_params.get("after", -1))
    except ValueError:
        sent = -1

    def events():
        nonlocal sent
        yield ": open\n\n"
        quiet = time.monotonic()
        deadline = quiet + timeout
        while True:
            current = Job.objects.get(pk=job.pk)
            for line in JobLine.objects.filter(job=job, idx__gt=sent).order_by("idx"):
                sent, quiet = line.idx, time.monotonic()
                yield f"event: line\ndata: {json.dumps(JobLineSerializer(line).data, default=str)}\n\n"
            if current.is_final or time.monotonic() > deadline:
                status = {"id": str(current.public_id), "status": current.status, "is_final": current.is_final}
                yield f"event: status\ndata: {json.dumps({**status, 'error': current.error})}\n\n"
                yield "event: end\ndata: {}\n\n"
                return
            if time.monotonic() - quiet > KEEPALIVE_SECONDS:
                quiet = time.monotonic()
                yield ": keep-alive\n\n"
            time.sleep(0.5)

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
