"""`manage.py doctor PATH [--format text|findings]` — zer0 doctor over a site's
checkout (sites/doctor.py), the same as `python -m sites.doctor PATH` — or
`manage.py doctor --site KEY`, which runs it as that managed site's doctor job,
so its findings are recorded on the site. Exit status 1 when the doctor reports
an error."""

from django.core.management.base import BaseCommand, CommandError

from sites import doctor


class Command(BaseCommand):
    help = "Check a site's repository against the platform's contract (zer0 doctor)."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="The site's root, the directory holding _config.yml.")
        parser.add_argument("--site", help="A managed site's key: run its doctor job and record the findings.")
        parser.add_argument("--format", choices=["text", "findings"], default="text")

    def handle(self, *args, path=None, site=None, format="text", **options):
        if bool(path) == bool(site):
            raise CommandError("name a PATH or a --site, not both")
        if site:
            from jobs.services import execute
            from sites.models import ManagedSite
            from sites.services import start

            managed = ManagedSite.objects.filter(key=site).first()
            if managed is None:
                raise CommandError(f"no managed site {site}")
            job = execute(start("doctor", managed, enqueue=False).pk)
            if job.status != job.Status.SUCCEEDED:
                raise CommandError(job.error or f"the doctor job {job.status}")
            path = str(managed.root)
        status = doctor.main([path, "--format", format], stdout=self.stdout)
        if status:
            raise SystemExit(status)
