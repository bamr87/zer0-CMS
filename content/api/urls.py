"""`/api/v2/`: Wagtail's page, image and document endpoints (public, live
content only) plus the content plane's own endpoints (api/views.py)."""

from django.urls import path
from rest_framework.permissions import AllowAny
from wagtail.api.v2.router import WagtailAPIRouter
from wagtail.api.v2.views import PagesAPIViewSet
from wagtail.documents.api.v2.views import DocumentsAPIViewSet
from wagtail.images.api.v2.views import ImagesAPIViewSet

from . import views


class PublicPages(PagesAPIViewSet):
    permission_classes = [AllowAny]


class PublicImages(ImagesAPIViewSet):
    permission_classes = [AllowAny]


class PublicDocuments(DocumentsAPIViewSet):
    permission_classes = [AllowAny]


router = WagtailAPIRouter("wagtailapi")
router.register_endpoint("pages", PublicPages)
router.register_endpoint("images", PublicImages)
router.register_endpoint("documents", PublicDocuments)

urlpatterns = [
    path("agent-runs/", views.agent_runs, name="agent-runs"),
    path("agent-runs/<int:pk>/", views.agent_run, name="agent-run"),
    path("agent-runs/<int:pk>/stream/", views.agent_run_stream, name="agent-run-stream"),
    path("agents/<slug:slug>/runs", views.agent_runs_for, name="agent-runs-for"),
    path("graph/neighbors/", views.graph_neighbors, name="graph-neighbors"),
    path("graph/path/", views.graph_path, name="graph-path"),
    path("graph/related/<int:page_id>/", views.graph_related, name="graph-related"),
    path("graph/search/", views.graph_search, name="graph-search"),
    path("suggestions/", views.suggestions, name="suggestions"),
    path("suggestions/<int:pk>/<str:decision>/", views.suggestion_decide, name="suggestion-decide"),
    path("tools/", views.tools, name="tools"),
]
