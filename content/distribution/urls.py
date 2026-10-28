"""`/api/v2/distribution/`: distribution's router (distribution/views.py) and
LinkedIn's OAuth callback; included from config/urls.py and, for the OpenAPI
document, from ops/openapi.py."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("channels", views.DistributionChannelViewSet, basename="distribution-channel")
router.register("posts", views.DistributionPostViewSet, basename="distribution-post")
router.register("ledger", views.DistributionLedgerViewSet, basename="distribution-ledger")

urlpatterns = [
    path("oauth/linkedin/", views.linkedin_callback, name="distribution-linkedin-callback"),
    *router.urls,
]
