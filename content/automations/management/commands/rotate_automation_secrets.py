"""`manage.py rotate_automation_secrets`: re-encrypt every automation's secret with the first key. Automations keep
their secrets under the keys provider credentials use (ai/crypto.py), so this runs beside `rotate_ai_credentials`:
put the new key first, run both, then drop the old key. A secret no current key can read stops it, named."""

from django.core.management.base import BaseCommand, CommandError

from automations.services import reencrypt_secrets


class Command(BaseCommand):
    help = "Re-encrypt every automation's secret with the newest key."

    def handle(self, *args, **options):
        try:
            self.stdout.write(f"{reencrypt_secrets()} secret(s) re-encrypted")
        except ValueError as e:
            raise CommandError(str(e)) from e
