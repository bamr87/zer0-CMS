"""Admin wiring for suggestions: the review URLs and a "Suggestions" button on
every page's header."""

from django.urls import path, reverse
from wagtail import hooks
from wagtail.admin.widgets.button import ListingButton

from . import views


@hooks.register("register_admin_urls")
def urls():
    return [
        path("suggestions/page/<int:page_id>/", views.page_suggestions, name="suggestions_page"),
        path("suggestions/<int:suggestion_id>/<str:decision>/", views.decide, name="suggestions_decide"),
    ]


@hooks.register("register_page_header_buttons")
def suggestions_button(page, user, next_url=None, view_name=None):
    yield ListingButton("Suggestions", reverse("suggestions_page", args=[page.pk]), priority=60)
