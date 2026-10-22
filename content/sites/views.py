"""`/api/v2/sites/`: the site registry for the studio's Sites area and its site
switcher (sites/README.md).

    GET   /api/v2/sites/                   the sites the caller sees, with what the platform manages of each
    POST  /api/v2/sites/                   register a site from its checkout; its first sync starts (201)
    GET   /api/v2/sites/discover/          checkouts that could be registered
    GET   /api/v2/sites/<id>/              a site: its registry entry, pages, files and latest jobs
    PATCH /api/v2/sites/<id>/              change its content source, renderer, domains, deploy target
    GET   /api/v2/sites/<id>/settings/     its settings: SEO defaults, analytics, navigation, brand voice, design, budget
    PATCH /api/v2/sites/<id>/settings/
    GET   /api/v2/sites/<id>/findings/     the last doctor run's findings (?severity=, ?check=)
    POST  /api/v2/sites/<id>/sync/         start a sync (202, the job)
    POST  /api/v2/sites/<id>/export/       start a write-back into its checkout (202)
    POST  /api/v2/sites/<id>/doctor/       start a doctor run (202)

Thin views over sites/services.py, for people only. A site the caller does not
see is a 404; changing one, or starting its jobs, needs `sites.manage_site`
(sites/access.py), else a 403. A job-starting request honours an
`Idempotency-Key`, and an exclusive job already queued or running for the
site is a 409 (`job.busy`). Jobs are followed on `/api/v2/jobs/<id>/`.
"""

from contextlib import contextmanager

from django.db import transaction
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.models import Page

from ai.views import IDEMPOTENCY, idempotent
from api.pages import IsPerson
from cms.models import BasePage
from jobs import services as jobs
from jobs.models import Job
from ops.errors import Conflict, Forbidden, Invalid, NotFound
from ops.openapi import ERROR_RESPONSES

from . import access, services
from . import serializers as s
from .models import ManagedSite, SiteSettings


def _valid(serializer_class, request, **kwargs) -> dict:
    serializer = serializer_class(data=request.data, **kwargs)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def managed_of(site) -> ManagedSite | None:
    return getattr(site, "managed", None)  # a reverse one-to-one with no row reads as missing


def site_json(site, user) -> dict:
    managed = managed_of(site)
    return {
        "id": site.pk,
        "name": site.site_name or site.hostname,
        "hostname": site.hostname,
        "port": site.port,
        "is_default": site.is_default_site,
        "root_page_id": site.root_page_id,
        "managed": managed,
        "can_manage": access.may_manage(user, site),
    }


def _visible(request, pk):
    site = access.visible_sites(request.user).select_related("managed").filter(pk=pk).first()
    if site is None:
        raise NotFound("no such site")
    return site


def _managed(request, pk) -> ManagedSite:
    site = _visible(request, pk)
    if not access.may_manage(request.user, site):
        raise Forbidden("managing a site needs the sites.manage_site permission")
    managed = managed_of(site)
    if managed is None:
        raise NotFound("the platform does not manage this site yet: register it first")
    return managed


@contextmanager
def service_errors():
    """Service errors as the envelope's: 422 for a refused request, 409 for a busy site."""
    try:
        yield
    except services.SiteError as e:
        raise Invalid(str(e)) from e
    except jobs.Busy as e:
        raise Conflict(str(e), code="job.busy") from e


class Sites(APIView):
    permission_classes = [IsPerson]

    @extend_schema(operation_id="sites_list", responses={200: s.SiteSerializer(many=True), **ERROR_RESPONSES})
    def get(self, request):
        rows = access.visible_sites(request.user).select_related("managed").order_by("site_name", "hostname")
        return Response(s.SiteSerializer([site_json(site, request.user) for site in rows], many=True).data)

    @extend_schema(
        operation_id="sites_register",
        summary="Register a site from its checkout; its first sync starts",
        request=s.RegisterSiteSerializer,
        responses={201: s.RegisteredSiteSerializer, **ERROR_RESPONSES},
    )
    def post(self, request):
        if not request.user.has_perm(access.MANAGE):
            raise Forbidden("registering a site needs the sites.manage_site permission")
        data = _valid(s.RegisterSiteSerializer, request)
        with service_errors():
            managed, job = services.register(data["checkout"], user=request.user, key=data.get("key") or "")
        body = {"site": site_json(managed.site, request.user), "job": job}
        return Response(s.RegisteredSiteSerializer(body).data, status=status.HTTP_201_CREATED)


class Discover(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="sites_discover",
        summary="Checkouts that could be registered: workspace.yml's sites and the Jekyll roots under SITES_DIR",
        responses={200: s.SiteCandidateSerializer(many=True), **ERROR_RESPONSES},
    )
    def get(self, request):
        if not request.user.has_perm(access.MANAGE):
            raise Forbidden("registering a site needs the sites.manage_site permission")
        return Response(s.SiteCandidateSerializer(services.discover(), many=True).data)


class SiteDetail(APIView):
    permission_classes = [IsPerson]

    def detail(self, request, site) -> Response:
        pages = Page.objects.descendant_of(site.root_page).type(BasePage)
        managed = managed_of(site)
        recent = Job.objects.visible_to(request.user).filter(site=site).prefetch_related("artifacts")[:10]
        body = {
            **site_json(site, request.user),
            "pages": {
                "total": pages.count(),
                "live": pages.live().count(),
                "drafts": pages.filter(Q(live=False) | Q(has_unpublished_changes=True)).count(),
            },
            "files": len(managed.digests) if managed is not None else 0,
            "jobs": list(recent),
        }
        return Response(s.SiteDetailSerializer(body).data)

    @extend_schema(operation_id="sites_retrieve", responses={200: s.SiteDetailSerializer, **ERROR_RESPONSES})
    def get(self, request, pk):
        return self.detail(request, _visible(request, pk))

    @extend_schema(
        operation_id="sites_update",
        summary="Change a site's content source, renderer, domains or deploy target",
        request=s.SiteUpdateSerializer,
        responses={200: s.SiteDetailSerializer, **ERROR_RESPONSES},
    )
    def patch(self, request, pk):
        managed = _managed(request, pk)
        data = _valid(s.SiteUpdateSerializer, request, partial=True)
        with service_errors(), transaction.atomic():
            services.update(managed, data)
        return self.detail(request, _visible(request, pk))


class Settings(APIView):
    permission_classes = [IsPerson]

    @extend_schema(operation_id="sites_settings", responses={200: s.SiteSettingsSerializer, **ERROR_RESPONSES})
    def get(self, request, pk):
        return Response(s.SiteSettingsSerializer(SiteSettings.for_site(_visible(request, pk))).data)

    @extend_schema(
        operation_id="sites_settings_update",
        request=s.SiteSettingsSerializer,
        responses={200: s.SiteSettingsSerializer, **ERROR_RESPONSES},
    )
    def patch(self, request, pk):
        site = _visible(request, pk)
        if not access.may_manage(request.user, site):
            raise Forbidden("changing a site's settings needs the sites.manage_site permission")
        serializer = s.SiteSettingsSerializer(SiteSettings.for_site(site), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class Findings(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="sites_findings",
        summary="The last doctor run's findings",
        parameters=[
            OpenApiParameter("severity", str, enum=["error", "warning"]),
            OpenApiParameter("check", str, description="config, image-engine, cms, fleet, distribution or content."),
        ],
        responses={200: s.DoctorFindingSerializer(many=True), **ERROR_RESPONSES},
    )
    def get(self, request, pk):
        site = _visible(request, pk)
        managed = managed_of(site)
        found = list(managed.findings) if managed is not None else []
        for name, key in (("severity", "severity"), ("check", "check_id")):
            if value := request.query_params.get(name):
                found = [f for f in found if f.get(key) == value]
        return Response(s.DoctorFindingSerializer(found, many=True).data)


class StartJob(APIView):
    """POST: start this view's kind of job for the site (202 with the job)."""

    permission_classes = [IsPerson]
    kind = ""
    request_serializer = None

    def start(self, request, pk):
        managed = _managed(request, pk)
        params = _valid(self.request_serializer, request) if self.request_serializer else {}
        with service_errors():
            job = services.start(self.kind, managed, user=request.user, params=params)
        return Response(s.JobAcceptedSerializer({"job": job}).data, status=status.HTTP_202_ACCEPTED)


class Sync(StartJob):
    kind, request_serializer = "sync", s.SyncOptionsSerializer

    @extend_schema(
        operation_id="sites_sync",
        summary="Sync the site's files into the platform (a job)",
        request=s.SyncOptionsSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.JobAcceptedSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def post(self, request, pk):
        return self.start(request, pk)


class Export(StartJob):
    kind, request_serializer = "export", s.ExportOptionsSerializer

    @extend_schema(
        operation_id="sites_export",
        summary="Write the site's pages back into its checkout, under the stale-write guard (a job)",
        request=s.ExportOptionsSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.JobAcceptedSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def post(self, request, pk):
        return self.start(request, pk)


class Doctor(StartJob):
    kind = "doctor"

    @extend_schema(
        operation_id="sites_doctor",
        summary="Check the site's checkout with zer0 doctor (a job)",
        request=None,
        parameters=[IDEMPOTENCY],
        responses={202: s.JobAcceptedSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def post(self, request, pk):
        return self.start(request, pk)
