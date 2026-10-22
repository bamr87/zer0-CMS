"""App config for `newsroom`: after every migrate, its bundled assistants,
schemas and pipeline in the AI content layer (skipped while the AI tables are
unapplied); the receivers that keep a story's status in step with Wagtail — a
stage sent back, a workflow cancelled, a page gone live — and that refuse a
publish the story holds back; Wagtail's workflow email for every workflow but
the newsroom's; and a story's headline run turned into suggestions
(newsroom/workflow.py, newsroom/services.py)."""

from django.apps import AppConfig
from django.apps import apps as installed
from django.db.models.signals import post_migrate


class NewsroomConfig(AppConfig):
    name = "newsroom"
    verbose_name = "Newsroom"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from wagtail.admin import signal_handlers as wagtail_email
        from wagtail.models import WorkflowState
        from wagtail.signals import (
            page_published,
            workflow_approved,
            workflow_cancelled,
            workflow_rejected,
            workflow_submitted,
        )

        from agents.runner import run_finished

        from . import services, workflow

        post_migrate.connect(_seed, sender=self)
        workflow_rejected.connect(workflow.on_workflow_rejected, dispatch_uid="newsroom.rejected")
        workflow_cancelled.connect(workflow.on_workflow_cancelled, dispatch_uid="newsroom.cancelled")
        page_published.connect(workflow.on_page_published, dispatch_uid="newsroom.published")
        run_finished.connect(services.propose_headlines, dispatch_uid="newsroom.headlines")
        # Wagtail's own receivers, by their dispatch_uid: replaced whichever app is ready first, since a
        # receiver connected under a dispatch_uid already taken is not connected again.
        for signal, notifier, uid in (
            (workflow_submitted, wagtail_email.workflow_submission_email_notifier, "submitted"),
            (workflow_rejected, wagtail_email.workflow_rejection_email_notifier, "rejected"),
            (workflow_approved, wagtail_email.workflow_approval_email_notifier, "approved"),
        ):
            dispatch_uid = f"workflow_state_{uid}_email_notification"
            signal.disconnect(sender=WorkflowState, dispatch_uid=dispatch_uid)
            signal.connect(
                workflow.not_for_the_newsroom(notifier), sender=WorkflowState, dispatch_uid=dispatch_uid, weak=False
            )


def _seed(sender, apps=installed, **kwargs):
    from .services import seed_bundled

    try:
        for name in ("OutputSchema", "Assistant", "Pipeline", "PipelineStep"):
            apps.get_model("ai", name)
    except LookupError:
        return  # the migrate left the AI tables unapplied
    seed_bundled(apps)
