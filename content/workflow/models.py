"""`AgentReviewTask`: a Wagtail workflow task a review agent decides.

Put it in a workflow (Settings → Workflows) like any other task, before the
human approval: approving a workflow's last task publishes the page, and an
agent never publishes, so an agent review that is last rejects with that
reason instead of running. When a page reaches it, `start()` queues a run of the named review agent against the
page; the run ends by calling `review.submit_verdict`, and
`workflow.services.finish_review` writes the agent's comments onto the page's
blocks through Wagtail's comments and approves or rejects the task state as
the agent's user. A failed run rejects: a review that did not happen is not a
pass. Editors see all of it in the normal moderation UI.
"""

from django.db import models, transaction
from wagtail.models import Task, TaskState


class AgentReviewTask(Task):
    agent = models.SlugField(max_length=64, help_text="The review agent's slug, e.g. brand, a11y, factcheck.")

    admin_form_fields = Task.admin_form_fields + ["agent"]

    class Meta:
        verbose_name = "Agent review task"
        verbose_name_plural = "Agent review tasks"

    @classmethod
    def get_description(cls):
        return "A review agent passes or fails the page; its comments land on the blocks."

    def start(self, workflow_state, user=None):
        task_state = super().start(workflow_state, user=user)
        from agents.models import AgentDefinition
        from agents.runner import start_run

        definition = AgentDefinition.objects.filter(slug=self.agent).first()
        page = workflow_state.content_object
        if definition is None or not definition.live or definition.role != "review":
            reason = f"review agent {self.agent!r} is missing, not live, or not a review agent"
            transaction.on_commit(lambda: _reject(task_state.pk, reason))
            return task_state
        if self.is_last_in(workflow_state.workflow):
            # Approving the last task publishes the page, as whoever approved
            # it. An agent never publishes, so a workflow must end with a person.
            reason = "an agent review cannot be a workflow's last task: add a human approval task after it"
            transaction.on_commit(lambda: _reject(task_state.pk, reason))
            return task_state
        start_run(
            definition,
            trigger="workflow",
            target=page.specific if hasattr(page, "specific") else page,
            input={"task_state_id": task_state.pk, "scenario": "workflow"},
            user=user,
        )
        return task_state

    def is_last_in(self, workflow) -> bool:
        from wagtail.models import WorkflowTask

        mine = WorkflowTask.objects.filter(workflow=workflow, task=self).first()
        later = WorkflowTask.objects.filter(workflow=workflow, task__active=True)
        return mine is None or not later.filter(sort_order__gt=mine.sort_order).exists()

    def get_actions(self, obj, user):
        # People do not approve an agent's task — but a superuser may override
        # a stuck one, which Wagtail records as theirs.
        if user.is_superuser:
            return [("approve", "Approve (override)", False), ("reject", "Reject (override)", False)]
        return []

    def user_can_access_editor(self, obj, user):
        return True

    def locked_for_user(self, obj, user):
        return False


def _reject(task_state_id, reason):
    state = TaskState.objects.filter(pk=task_state_id, status=TaskState.STATUS_IN_PROGRESS).first()
    if state is not None:
        state.specific.reject(comment=reason)
