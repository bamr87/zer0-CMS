"""`manage.py user_token USERNAME --name NAME [--days N]`: issue a person's
API token — for the VS Code extension ("zer0-CMS: Set platform token") or a
script. The token is printed once; only its hash is stored. `--list` shows a
person's tokens, `--revoke PREFIX` revokes one."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import UserToken


class Command(BaseCommand):
    help = "Issue, list or revoke a person's API token."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--name", help="Where the token is used; required to issue one.")
        parser.add_argument("--days", type=int, help="Expire after this many days (default: never).")
        parser.add_argument("--list", action="store_true", dest="show", help="List the person's tokens.")
        parser.add_argument("--revoke", metavar="PREFIX", help="Revoke the token that starts with PREFIX.")

    def handle(self, *args, username, name, days, show, revoke, **options):
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"no user {username}")
        if show:
            for token in user.user_tokens.order_by("-created_at"):
                state = "revoked" if token.revoked_at else f"expires {token.expires_at:%Y-%m-%d}" if token.expires_at else "active"
                self.stdout.write(f"{token.prefix}…  {token.name}  {state}  last used {token.last_used_at or 'never'}")
            return
        if revoke:
            found = user.user_tokens.filter(prefix__startswith=revoke[:14], revoked_at__isnull=True)
            if found.count() != 1:
                raise CommandError(f"{found.count()} active tokens of {username} start with {revoke}; name exactly one")
            found.update(revoked_at=timezone.now())
            self.stderr.write(f"revoked {revoke}…")
            return
        if not name:
            raise CommandError("--name is required to issue a token")
        try:
            token, raw = UserToken.issue(user, name=name, expires_at=timezone.now() + timedelta(days=days) if days else None)
        except ValueError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(raw)
        self.stderr.write(f"issued {token} for {username}; store it now, it is not shown again")
