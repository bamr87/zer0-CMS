"""`manage.py rotate_ai_credentials`: re-encrypt every secret kept under the AI
layer's keys (ai/crypto.py) with the first key — the first of
`AI_CREDENTIAL_KEYS`, else the one derived from `SECRET_KEY`: the providers'
credentials and every other secret an app keeps under them (distribution's
channels, the automations' webhook secrets: `crypto.credentials_rotated`), in
one transaction. Put the new key first, run this, then drop the old key. A secret no current key can read is
named, not lost, and then nothing is changed."""

from django.core.management.base import BaseCommand, CommandError

from ai.providers import NotConfigured
from ai.services import rotate_credentials


class Command(BaseCommand):
    help = "Re-encrypt stored provider credentials and other secrets with the newest key."

    def handle(self, *args, **options):
        try:
            self.stdout.write(f"{rotate_credentials()} credential(s) re-encrypted")
        except (NotConfigured, ValueError) as e:
            raise CommandError(str(e)) from e
