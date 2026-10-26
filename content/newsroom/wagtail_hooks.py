"""The Wagtail admin's side of the newsroom's publishing rule. A page whose story
holds it back (`services.publish_refusal`: a story still being made, or one
under embargo) is refused on every path by `workflow.on_page_published`; in the
admin's editor this says why, instead of a server error, and the page stays a
draft with what was just saved."""

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from wagtail import hooks

from .models import Story
from .services import publish_refusal


@hooks.register("before_publish_page")
def held_back_by_its_story(request, page):
    story = Story.objects.filter(page_id=page.pk).first()
    if story is None:
        return None
    go_live_at = page.go_live_at if page.go_live_at and page.go_live_at > timezone.now() else None
    refusal = publish_refusal(story, go_live_at)
    if refusal is None:
        return None
    messages.error(request, f"Not published: {refusal.message}")
    return redirect("wagtailadmin_pages:edit", page.pk)
