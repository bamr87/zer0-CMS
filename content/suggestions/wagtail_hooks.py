"""Admin wiring for suggestions: the review URLs, a "Suggestions" button on
every page's header, and the log actions a suggestion's life writes to
Wagtail's log (proposed by an agent, accepted or rejected by a person)."""

from django.urls import path, reverse
from wagtail import hooks
from wagtail.admin.widgets.button import ListingButton
from wagtail.models import ModelLogEntry

from . import views
from .models import Suggestion


@hooks.register("register_log_actions")
def suggestion_log_actions(actions):
    actions.register_model(Suggestion, ModelLogEntry)
    actions.register_action("zer0.suggestion.propose", "Propose a suggestion", "Suggestion proposed")
    actions.register_action("zer0.suggestion.accept", "Accept a suggestion", "Suggestion accepted")
    actions.register_action("zer0.suggestion.reject", "Reject a suggestion", "Suggestion rejected")


@hooks.register("register_admin_urls")
def urls():
    return [
        path("suggestions/page/<int:page_id>/", views.page_suggestions, name="suggestions_page"),
        path("suggestions/<int:suggestion_id>/<str:decision>/", views.decide, name="suggestions_decide"),
    ]


@hooks.register("register_page_header_buttons")
def suggestions_button(page, user, next_url=None, view_name=None):
    yield ListingButton("Suggestions", reverse("suggestions_page", args=[page.pk]), priority=60)
