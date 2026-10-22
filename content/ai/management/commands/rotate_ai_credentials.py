"""`manage.py rotate_ai_credentials`: re-encrypt every stored provider
credential with the first key of `AI_CREDENTIAL_KEYS` (ai/crypto.py). Put the
new key first, run this, then drop the old key."""

from django.core.management.base import BaseCommand

from ai.services import rotate_credentials


class Command(BaseCommand):
    help = "Re-encrypt stored provider credentials with the newest key."

    def handle(self, *args, **options):
        self.stdout.write(f"{rotate_credentials()} credential(s) re-encrypted")
