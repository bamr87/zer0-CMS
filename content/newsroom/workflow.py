"""Where Wagtail's workflow and publishing meet the newsroom's stories.

`finish_workflow` is `WAGTAIL_FINISH_WORKFLOW_ACTION`, Wagtail's hook for what
approving a workflow's last task does. Every other workflow publishes, as
Wagtail does by default; the newsroom's does not, because a story that has
cleared copy goes live only through the newsroom (`services.release`), which
publishes or schedules it with `cms.services` — the person's publish
permission, the page's locks and the story's embargo all checked there.
Wagtail reads this setting when its models load, so nothing here imports a
model at module level.

The receivers keep a story's status honest when its page moves outside the
newsroom's own calls: a stage sent back (Wagtail's "request changes") returns
the story to drafting with the comment, and a page that goes live — the
scheduled publish on Celery beat, or a publish from the Wagtail admin —
publishes a story that had not got there yet.
"""


def finish_workflow(workflow_state, user=None):
    from wagtail.workflows import publish_workflow_state

    from .models import StageTask

    if StageTask.objects.filter(workflow_tasks__workflow_id=workflow_state.workflow_id).exists():
        return  # cleared copy: the newsroom publishes or schedules it (services.release)
    publish_workflow_state(workflow_state, user=user)


def on_workflow_rejected(sender, instance, user=None, **kwargs):
    from .models import StageTask, Story
    from .services import record

    task_state = instance.current_task_state
    if task_state is None or not isinstance(task_state.task.specific, StageTask):
        return
    story = Story.objects.filter(page_id=instance.object_id).first()
    if story is not None and story.status != Story.Status.DRAFTING:
        record(story, Story.Status.DRAFTING, user, "sent back", note=task_state.comment)


def on_page_published(sender, instance, **kwargs):
    from .models import Story
    from .services import PRE_PUBLISH, record

    story = Story.objects.filter(page_id=instance.pk, status__in=PRE_PUBLISH).first()
    if story is not None and instance.live:
        record(story, Story.Status.PUBLISHED, None, "went live")
