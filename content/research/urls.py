"""`/api/v2/research/`: the research library's router (research/views.py); included from config/urls.py and, for
the OpenAPI document, from ops/openapi.py."""

from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("collections", views.CollectionViewSet, basename="research-collection")
router.register("sources", views.SourceViewSet, basename="research-source")
router.register("quotes", views.QuoteViewSet, basename="research-quote")
router.register("citations", views.CitationViewSet, basename="research-citation")
router.register("feeds", views.FeedViewSet, basename="research-feed")
router.register("questions", views.QuestionViewSet, basename="research-question")
router.register("fact-checks", views.FactCheckViewSet, basename="research-fact-check")

urlpatterns = router.urls
