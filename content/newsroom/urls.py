"""`/api/v2/newsroom/`: the newsroom's router (newsroom/views.py) and its three
public subscription endpoints; included from config/urls.py and, for the
OpenAPI document, from ops/openapi.py."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("desks", views.DeskViewSet, basename="newsroom-desk")
router.register("stories", views.StoryViewSet, basename="newsroom-story")
router.register("authors", views.AuthorViewSet, basename="newsroom-author")
router.register("fronts", views.FrontViewSet, basename="newsroom-front")
router.register("newsletters", views.NewsletterViewSet, basename="newsroom-newsletter")
router.register("issues", views.IssueViewSet, basename="newsroom-issue")

urlpatterns = [
    path("newsletters/<uuid:public_id>/subscribe/", views.subscribe, name="newsroom-subscribe"),
    path("subscriptions/confirm/", views.confirm, name="newsroom-confirm"),
    path("subscriptions/unsubscribe/", views.unsubscribe, name="newsroom-unsubscribe"),
    *router.urls,
]
