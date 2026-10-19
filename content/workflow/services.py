"""Finishing an agent review: comments on blocks, then approve or reject.

The verdict comes from the run's output (`review.submit_verdict` stores it).
Comments are Wagtail `Comment` rows authored by the agent user and anchored
to `body.<block id>`, so they appear beside the block in the editor.
"""

from django.db import transaction
from wagtail.models import Comment, TaskState


@transaction.atomic
def finish_review(run):
    state_id = (run.input or {}).get("task_state_id")
    if not state_id:
        return None
    state = TaskState.objects.filter(pk=state_id).first()
    if state is None or state.status != TaskState.STATUS_IN_PROGRESS:
        return None
    state = state.specific
    agent_user = run.config().user
    verdict = (run.output or {}).get("verdict") or {}
    page = run.target
    revision = page.get_latest_revision() if page is not None else None
    for note in verdict.get("comments", []):
        block = note.get("block_id")
        Comment.objects.create(
            page=page,
            user=agent_user,
            text=note.get("text", "")[:2000],
            contentpath=f"body.{block}" if block else "title",
            revision_created=revision,
        )
    summary = verdict.get("summary") or run.error or ""
    if run.status == run.SUCCEEDED and verdict.get("passed") is True:
        state.approve(user=agent_user, comment=summary[:2000])
        return "approved"
    state.reject(user=agent_user, comment=(summary or "the review agent did not pass the page")[:2000])
    return "rejected"
