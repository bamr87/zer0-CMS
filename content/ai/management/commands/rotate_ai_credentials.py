"""`manage.py rotate_ai_credentials`: re-encrypt every stored provider
credential with the first key (ai/crypto.py): the first of `AI_CREDENTIAL_KEYS`,
else the one derived from `SECRET_KEY`. Put the new key first, run this, then
drop the old key. A credential no current key can read is named, not lost."""

from django.core.management.base import BaseCommand, CommandError

from ai.providers import NotConfigured
from ai.services import rotate_credentials


class Command(BaseCommand):
    help = "Re-encrypt stored provider credentials with the newest key."

    def handle(self, *args, **options):
        try:
            self.stdout.write(f"{rotate_credentials()} credential(s) re-encrypted")
        except NotConfigured as e:
            raise CommandError(str(e)) from e
