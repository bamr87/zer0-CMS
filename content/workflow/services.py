"""The editorial workflow, and finishing an agent review in one.

`editorial` is the seeded "Editorial" workflow (`manage.py seed_editorial`):
the brand agent's review, then a moderator's approval — Wagtail's own
"Moderators approval" task, for the Moderators group — so an agent is never
the last task and a person publishes. `assign` makes a workflow the one a
page's subtree is reviewed by (Wagtail's `WorkflowPage`).

`finish_review` ends an agent review: the verdict comes from the run's
output (`review.submit_verdict` stores it); comments are Wagtail `Comment` rows
authored by the agent user and anchored to `body.<block id>`, so they appear
beside the block in the editor; then the task state is approved or rejected.
"""

from django.contrib.auth.models import Group
from django.db import transaction
from wagtail.models import Comment, GroupApprovalTask, TaskState, Workflow, WorkflowPage, WorkflowTask

from .models import AgentReviewTask

EDITORIAL = "Editorial"


def editorial() -> Workflow:
    """The "Editorial" workflow — brand review, then a moderator — made the first time it is asked for."""
    flow = Workflow.objects.filter(name=EDITORIAL).first()
    if flow is not None:
        return flow
    review = AgentReviewTask.objects.filter(agent="brand").first() or AgentReviewTask.objects.create(
        name="Brand review", agent="brand"
    )
    approval = GroupApprovalTask.objects.filter(name="Moderators approval").first()
    if approval is None:
        approval = GroupApprovalTask.objects.create(name="Moderators approval")
        approval.groups.set(Group.objects.filter(name="Moderators"))
    flow = Workflow.objects.create(name=EDITORIAL)
    WorkflowTask.objects.bulk_create(
        [
            WorkflowTask(workflow=flow, task=review, sort_order=0),
            WorkflowTask(workflow=flow, task=approval, sort_order=1),
        ]
    )
    return flow


def assign(flow: Workflow, page) -> None:
    """Review `page` and every page under it with `flow` (until a page below names another)."""
    WorkflowPage.objects.update_or_create(page=page, defaults={"workflow": flow})


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
