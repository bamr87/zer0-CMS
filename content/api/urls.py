"""`/api/v2/`: Wagtail's page, image and document endpoints (public, live
content only) plus the content plane's own endpoints: agent runs, the graph,
suggestions and the tool registry (api/views.py), and what the studio and the
extension work with — who is signed in (api/session.py; signing in is
allauth's headless API, accounts/README.md), pages, revisions and
publishing (api/pages.py), and the review inbox (api/review.py)."""

from django.urls import path
from rest_framework.permissions import AllowAny
from wagtail.api.v2.router import WagtailAPIRouter
from wagtail.api.v2.views import PagesAPIViewSet
from wagtail.documents.api.v2.views import DocumentsAPIViewSet
from wagtail.images.api.v2.views import ImagesAPIViewSet

from . import pages, review, session, views


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
    # The studio and the extension (people only; agents use the tool registry).
    path("me", session.me, name="me"),
    path("content/types/", pages.all_types, name="content-types"),
    path("content/pages/", pages.PageList.as_view(), name="content-pages"),
    path("content/pages/<int:pk>/", pages.page_detail, name="content-page"),
    path("content/pages/<int:pk>/types/", pages.page_types, name="content-page-types"),
    path("content/pages/<int:pk>/publish/", pages.publish, name="content-page-publish"),
    path("content/pages/<int:pk>/unpublish/", pages.unpublish, name="content-page-unpublish"),
    path("content/pages/<int:pk>/schedule/", pages.schedule, name="content-page-schedule"),
    path("content/pages/<int:pk>/unschedule/", pages.unschedule, name="content-page-unschedule"),
    path("content/pages/<int:pk>/revisions/", pages.RevisionList.as_view(), name="content-page-revisions"),
    path("content/pages/<int:pk>/revisions/compare/", pages.compare, name="content-page-revisions-compare"),
    path(
        "content/pages/<int:pk>/revisions/<int:revision_id>/revert/",
        pages.revert,
        name="content-page-revisions-revert",
    ),
    path("review/suggestions/", review.Inbox.as_view(), name="review-suggestions"),
    path("review/runs/<int:run_id>/accept/", review.accept_all, name="review-run-accept"),
]
