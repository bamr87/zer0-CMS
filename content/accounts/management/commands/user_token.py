"""`manage.py user_token USERNAME --name NAME [--days N] [--superuser]`: issue a
person's API token — for the VS Code extension ("zer0-CMS: Set platform
token") or a script. It expires after 90 days unless `--days` says otherwise
(`--days 0`: never), and a superuser's needs `--superuser`. The token is
printed once; only its hash is stored. `--list` shows a person's tokens,
`--revoke PREFIX` revokes one. The rules are `accounts.services`."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts import services


class Command(BaseCommand):
    help = "Issue, list or revoke a person's API token."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--name", help="Where the token is used; required to issue one.")
        parser.add_argument(
            "--days", type=int, default=services.DEFAULT_DAYS, help="Expire after this many days (0: never)."
        )
        parser.add_argument("--superuser", action="store_true", help="Issue one to a superuser anyway.")
        parser.add_argument("--list", action="store_true", dest="show", help="List the person's tokens.")
        parser.add_argument("--revoke", metavar="PREFIX", help="Revoke the token that starts with PREFIX.")

    def handle(self, *args, username, name, days, superuser, show, revoke, **options):
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"no user {username}")
        try:
            if show:
                for token in services.tokens_of(user):
                    state = (
                        "revoked"
                        if token.revoked_at
                        else f"expires {token.expires_at:%Y-%m-%d}"
                        if token.expires_at
                        else "never expires"
                    )
                    self.stdout.write(
                        f"{token.prefix}…  {token.name}  {state}  last used {token.last_used_at or 'never'}"
                    )
                return
            if revoke:
                services.revoke(user, revoke)
                self.stderr.write(f"revoked {revoke}…")
                return
            if not name:
                raise CommandError("--name is required to issue a token")
            token, raw = services.issue(user, name=name, days=days, superuser=superuser)
        except services.TokenError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(raw)
        self.stderr.write(f"issued {token} for {username}; store it now, it is not shown again")
