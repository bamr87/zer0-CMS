"""`manage.py seed_editorial [--site KEY …]`: the "Editorial" workflow.

Makes, once, Wagtail's workflow for a page's editorial review — the brand
agent's review first (`workflow.AgentReviewTask`, rules only, no model), then a
moderator's approval (Wagtail's own "Moderators approval" task, the Moderators
group), so an agent is never the last task and only a person publishes — and,
with `--site`, makes it the workflow of each named site's pages (Wagtail's
`WorkflowPage` on the site's root). A second run changes nothing.
`manage.py seed_demo` runs it for the demo site.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cms.models import SiteRootPage
from workflow.services import assign, editorial


class Command(BaseCommand):
    help = "The Editorial workflow (brand review, then a moderator), optionally for some sites (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--site", action="append", default=[], help="A site key whose pages it reviews.")

    @transaction.atomic
    def handle(self, *args, site, **options):
        roots = list(SiteRootPage.objects.filter(site_key__in=site))
        if missing := sorted(set(site) - {root.site_key for root in roots}):
            raise CommandError(f"no such site: {', '.join(missing)}")
        flow = editorial()
        for root in roots:
            assign(flow, root)
        tasks = " → ".join(str(task.specific) for task in flow.tasks)
        on = f" for {', '.join(r.site_key for r in roots)}" if roots else ""
        self.stdout.write(f"{flow.name}: {tasks}{on}")
