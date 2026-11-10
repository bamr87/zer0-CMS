"""`manage.py site_job sync|export|doctor|directives --site KEY [--include-drafts] [--force] [--generate]
[--user NAME] [--assistant ID]`: run one of a managed site's jobs here and now (sites/services.py) and print its
log — the same job the studio starts, for an operator or a CI step. `directives` pulls the site's open
`editorial:directive` issues into briefs (as `--user`, who owns them and, with `--generate`, starts writing them).
Exit status 1 when the job does not succeed or reports a conflict or an error."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from jobs.services import execute
from sites.models import ManagedSite
from sites.services import KINDS, start


class Command(BaseCommand):
    help = "Run a managed site's sync, write-back (export), doctor or directives job now and print its log."

    def add_arguments(self, parser):
        parser.add_argument("kind", choices=KINDS)
        parser.add_argument("--site", required=True, help="The managed site's key.")
        parser.add_argument(
            "--include-drafts", action="store_true", help="export: the latest revisions, not live pages."
        )
        parser.add_argument("--force", action="store_true", help="sync: take a file over a page changed here since.")
        parser.add_argument("--generate", action="store_true", help="directives: start writing each new brief.")
        parser.add_argument("--user", default="", help="directives: the person who owns the briefs (by username).")
        parser.add_argument("--assistant", default="", help="directives: the assistant (its id) that writes them.")

    def handle(self, *args, kind, site, include_drafts=False, force=False, **options):
        managed = ManagedSite.objects.filter(key=site).first()
        if managed is None:
            raise CommandError(f"no managed site {site}")
        user = None
        if options.get("user"):
            user = get_user_model().objects.filter(username=options["user"], is_active=True).first()
            if user is None:
                raise CommandError(f"no active person {options['user']}")
        params = {"include_drafts": include_drafts} if kind == "export" else {"force": force} if kind == "sync" else {}
        if kind == "directives":
            params = {"generate": bool(options.get("generate")), "assistant": options.get("assistant") or ""}
        job = execute(start(kind, managed, user=user, params=params, enqueue=False).pk)
        for line in job.lines.all():
            self.stdout.write(f"{line.level:7} {line.text}")
        flagged = job.result.get("conflict") or job.result.get("conflicts") or job.result.get("errors")
        if job.status != job.Status.SUCCEEDED or flagged:
            raise SystemExit(1)
