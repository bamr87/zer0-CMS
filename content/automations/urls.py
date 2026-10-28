"""`/api/v2/automations/`: the automations router (automations/views.py) — automations at the root, their runs under
`runs/`, and each webhook trigger's endpoint; included from config/urls.py and, for the OpenAPI document, from
ops/openapi.py."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("runs", views.AutomationRunViewSet, basename="automation-run")
router.register("", views.AutomationViewSet, basename="automation")

urlpatterns = [path("<uuid:public_id>/webhook/", views.webhook, name="automation-webhook"), *router.urls]
