"""Admin views: a page's pending suggestions, accept (one or all of a run's)
and reject. POST-only, CSRF-protected Wagtail admin views; every decision goes
through `services.accept` / `services.reject`, which re-check the editor's
permission, the page's lock and its current state; a refusal is a message. A
suggestion and a run are named by their public ids here too (P-D6)."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST
from wagtail.models import Page

from .models import Suggestion
from .services import SuggestionError, accept, can_decide, pending_for, reject


def page_suggestions(request, page_id):
    page = get_object_or_404(Page, pk=page_id).specific
    if not can_decide(request.user, page):
        raise Http404
    pending = list(pending_for(page))
    runs = {}
    for s in pending:
        runs.setdefault(s.run.public_id if s.run else None, []).append(s)
    return TemplateResponse(
        request, "suggestions/page_suggestions.html", {"page": page, "pending": pending, "runs": runs}
    )


@require_POST
def decide(request, suggestion_id, decision):
    suggestion = get_object_or_404(Suggestion, public_id=suggestion_id)
    try:
        if decision == "accept":
            batch = [suggestion]
            if request.POST.get("whole_run") and suggestion.run_id:
                batch = list(
                    Suggestion.objects.filter(
                        run_id=suggestion.run_id,
                        status=Suggestion.PENDING,
                        target_ct=suggestion.target_ct,
                        target_id=suggestion.target_id,
                    )
                )
            accept(batch, request.user)
            messages.success(request, f"Accepted {len(batch)} suggestion(s) as one draft revision.")
        elif decision == "reject":
            reject(suggestion, request.user, reason=request.POST.get("reason", ""))
            messages.success(request, "Rejected.")
        else:
            raise Http404
    except (SuggestionError, PermissionDenied) as e:
        messages.error(request, str(e) or "You may not decide this suggestion.")
    return redirect("suggestions_page", page_id=suggestion.target_id)
