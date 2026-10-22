"""`/api/v2/ideas/`: the ideas router (ideas/views.py) — ideas at the root, their boards under `boards/`; included
from config/urls.py and, for the OpenAPI document, from ops/openapi.py."""

from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("boards", views.BoardViewSet, basename="ideas-board")
router.register("", views.IdeaViewSet, basename="idea")

urlpatterns = router.urls
