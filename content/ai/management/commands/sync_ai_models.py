"""`manage.py sync_ai_models [SLUG ...]`: ask each provider (every enabled one
but the test adapters, by default) for the models it runs and upsert the
catalog — barodybroject's `sync_models`, and the CLI of the providers'
`sync-models` action. A provider that cannot be asked is reported and skipped."""

from django.core.management.base import BaseCommand, CommandError

from ai import providers
from ai.models import ProviderConfig
from ai.services import record_models


class Command(BaseCommand):
    help = "Sync the model catalog from the providers."

    def add_arguments(self, parser):
        parser.add_argument("slugs", nargs="*", help="Providers to sync; every enabled one by default.")

    def handle(self, *args, slugs, **options):
        rows = ProviderConfig.objects.filter(slug__in=slugs) if slugs else ProviderConfig.objects.filter(enabled=True)
        if slugs and rows.count() != len(set(slugs)):
            raise CommandError(f"unknown provider(s): {', '.join(sorted(set(slugs) - {r.slug for r in rows}))}")
        if not slugs:
            rows = rows.exclude(slug__in=["fake", "recorded"])
        for row in rows:
            try:
                found = record_models(row, providers.get(row.slug).list_models())
            except providers.ProviderError as e:
                self.stderr.write(f"{row.slug}: {e}")
                continue
            self.stdout.write(f"{row.slug}: {len(found['models'])} model(s), {len(found['created'])} new")
