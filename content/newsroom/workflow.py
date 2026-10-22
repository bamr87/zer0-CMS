"""Where Wagtail's workflow and publishing meet the newsroom's stories.

`finish_workflow` is `WAGTAIL_FINISH_WORKFLOW_ACTION`, Wagtail's hook for what
approving a workflow's last task does. Every other workflow publishes, as
Wagtail does by default; the newsroom's does not, because a story that has
cleared copy goes live only through the newsroom (`services.release`), which
publishes or schedules it with `cms.services` — the person's publish
permission, the page's locks and the story's embargo all checked there.
Wagtail reads this setting when its models load, so nothing here imports a
model at module level.

`on_page_published` is where every way a page goes live converges — Write's
Publish and Schedule, the Wagtail admin, an agent's `content.publish`, an
importer, the scheduled publish on Celery beat: Wagtail sends `page_published`
from inside each, and for a page's first schedule too. A story still being
made, or one whose embargo has not passed, is refused there
(`services.publish_refusal`), and the refusal rolls the publish back with the
transaction every one of those paths runs in — except that an importer's
publish (a revision by the legacy-import principal) replays a source still
canonical for the site, and moves a story still being made on. A scheduled
story that goes live is published, and so is one an importer published.

The other receivers keep a story's status honest when its page moves in
Wagtail: a stage sent back ("request changes") returns the story to drafting
with the comment, and so does a newsroom workflow cancelled (the Wagtail admin
offers that to the requester and the page's owner), from where it is submitted
again. `not_for_the_newsroom` keeps Wagtail's workflow email away from the
newsroom's stages, which people follow in the studio's Newsroom: Wagtail mails
from inside the request — every superuser on each submission, and an approval
even when the publish it led to is refused and rolled back.
"""


def newsroom_workflow(workflow_id) -> bool:
    from .models import StageTask

    return StageTask.objects.filter(workflow_tasks__workflow_id=workflow_id).exists()


def finish_workflow(workflow_state, user=None):
    from wagtail.workflows import publish_workflow_state

    if newsroom_workflow(workflow_state.workflow_id):
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


def on_workflow_cancelled(sender, instance, user=None, **kwargs):
    from .models import Story
    from .services import record

    if not newsroom_workflow(instance.workflow_id):
        return
    at = (Story.Status.EDITING, Story.Status.COPY)
    story = Story.objects.filter(page_id=instance.object_id, status__in=at).first()
    if story is not None:
        record(story, Story.Status.DRAFTING, user, "workflow cancelled")


def on_page_published(sender, instance, revision=None, **kwargs):
    from django.contrib.auth import get_user_model

    from agents.principals import LEGACY_IMPORT_USER

    from .models import Story
    from .services import IN_THE_MAKING, publish_refusal, record

    story = Story.objects.filter(page_id=instance.pk).first()
    if story is None:
        return
    by = getattr(revision, "user_id", None)
    replayed = by is not None and get_user_model().objects.filter(pk=by, username=LEGACY_IMPORT_USER).exists()
    # Wagtail sends this for a page scheduled to go live for the first time too: then it is not live yet.
    refusal = publish_refusal(story, None if instance.live else instance.go_live_at, replayed=replayed)
    if refusal is not None:
        raise refusal
    if instance.live and story.status in (Story.Status.SCHEDULED, *IN_THE_MAKING):
        record(story, Story.Status.PUBLISHED, None, "went live", note="published by an import" if replayed else "")


def not_for_the_newsroom(notifier):
    """Wagtail's workflow email `notifier`, for every workflow but the newsroom's."""

    def notify(sender, instance=None, **kwargs):
        if not newsroom_workflow(instance.workflow_id):
            return notifier(sender=sender, instance=instance, **kwargs)
        return None

    return notify
