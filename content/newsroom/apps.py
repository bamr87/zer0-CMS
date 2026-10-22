"""App config for `newsroom`: after every migrate, its bundled assistants,
schemas and pipeline in the AI content layer (skipped while the AI tables are
unapplied); and the receivers that keep a story's status in step with Wagtail
— a stage sent back, a page gone live — and turn a story's headline run into
suggestions (newsroom/workflow.py, newsroom/services.py)."""

from django.apps import AppConfig
from django.apps import apps as installed
from django.db.models.signals import post_migrate


class NewsroomConfig(AppConfig):
    name = "newsroom"
    verbose_name = "Newsroom"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from wagtail.signals import page_published, workflow_rejected

        from agents.runner import run_finished

        from . import services, workflow

        post_migrate.connect(_seed, sender=self)
        workflow_rejected.connect(workflow.on_workflow_rejected, dispatch_uid="newsroom.rejected")
        page_published.connect(workflow.on_page_published, dispatch_uid="newsroom.published")
        run_finished.connect(services.propose_headlines, dispatch_uid="newsroom.headlines")


def _seed(sender, apps=installed, **kwargs):
    from .services import seed_bundled

    try:
        for name in ("OutputSchema", "Assistant", "Pipeline", "PipelineStep"):
            apps.get_model("ai", name)
    except LookupError:
        return  # the migrate left the AI tables unapplied
    seed_bundled(apps)
