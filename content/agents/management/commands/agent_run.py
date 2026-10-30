"""`manage.py agent_run SLUG [--page ID] [--input JSON]`: run an agent now, in
this process, and print the outcome. For people at a terminal; the APIs and
the workflow queue runs through Celery instead."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from wagtail.models import Page

from agents.models import AgentDefinition
from agents.runner import RunRefused, execute, start_run


class Command(BaseCommand):
    help = "Run one agent synchronously."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--page", type=int)
        parser.add_argument("--input", default="{}")

    def handle(self, *args, slug, page=None, input="{}", **options):
        definition = AgentDefinition.objects.filter(slug=slug).first()
        if definition is None:
            raise CommandError(f"no agent {slug}")
        target = Page.objects.get(pk=page).specific if page else None
        try:
            with transaction.atomic():
                run = start_run(definition, trigger="manual", target=target, input=json.loads(input), enqueue=False)
        except RunRefused as e:
            raise CommandError(str(e)) from e
        run = execute(run)
        self.stdout.write(
            json.dumps(
                {
                    "run_id": str(run.public_id),
                    "status": run.status,
                    "error": run.error,
                    "output": run.output,
                    "cost_usd": str(run.cost_usd),
                    "trace_id": run.trace_id,
                },
                indent=2,
                default=str,
            )
        )
