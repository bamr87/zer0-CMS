"""`/api/v2/outbox/` (outboxdesk/views.py): the belt's paths, and the trials and claim checks routers; included from
config/urls.py and, for the OpenAPI document, from ops/openapi.py."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("trials", views.TrialViewSet, basename="outbox-trial")
router.register("claim-checks", views.ClaimCheckViewSet, basename="outbox-claim-check")

urlpatterns = [
    path("belt/", views.Summary.as_view(), name="outbox-belt"),
    path("belt/messages/", views.Messages.as_view(), name="outbox-belt-messages"),
    path("belt/messages/<str:message_id>/", views.OneMessage.as_view(), name="outbox-belt-message"),
    path("belt/traces/<str:trace>/", views.Journey.as_view(), name="outbox-belt-journey"),
    path("belt/dead-letters/", views.DeadLetters.as_view(), name="outbox-belt-dead-letters"),
    path("belt/send/", views.Send.as_view(), name="outbox-belt-send"),
    path("belt/deliver/", views.Deliver.as_view(), name="outbox-belt-deliver"),
    *router.urls,
]
