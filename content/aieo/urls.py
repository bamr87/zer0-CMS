"""`/api/v2/aieo/`: AIEO's router (aieo/views.py); included from config/urls.py and, for the OpenAPI document, from
ops/openapi.py."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("audits", views.AuditViewSet, basename="aieo-audit")
router.register("patterns", views.PatternViewSet, basename="aieo-pattern")
router.register("agents", views.AgentViewSet, basename="aieo-agent")
router.register("citations/queries", views.CitationQueryViewSet, basename="aieo-citation-query")
router.register("citations/checks", views.CitationCheckViewSet, basename="aieo-citation-check")
router.register("connectors", views.ConnectorViewSet, basename="aieo-connector")

urlpatterns = [
    path("score/", views.ScoreView.as_view(), name="aieo-score"),
    path("rewrites/", views.RewriteView.as_view(), name="aieo-rewrite"),
    path("citations/share/", views.ShareView.as_view(), name="aieo-share"),
    path("priorities/", views.PrioritiesView.as_view(), name="aieo-priorities"),
    path("context/<int:site_id>/", views.ContextView.as_view(), name="aieo-context"),
    path("lifecycle/", views.LifecycleView.as_view(), name="aieo-lifecycle"),
    *router.urls,
]
