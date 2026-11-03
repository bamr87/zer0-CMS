"""`manage.py agent_token SLUG --name NAME [--tool T ...]`: issue a bearer token
for an agent's user, for an MCP client or the Rails plane. The token is
printed once; only its hash is stored. `--list` shows the agent's tokens by
their prefix, `--revoke PREFIX` revokes the one active token that starts with
it — `HashedToken.revoke`, so Wagtail's log records it (`zer0.token.revoke`),
as issuing one is."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from agents.models import AgentToken


class Command(BaseCommand):
    help = "Issue, list or revoke an agent token."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--name", help="Where the token is used; required to issue one.")
        parser.add_argument("--tool", action="append", default=[], help="Narrow the token to this tool (repeat).")
        parser.add_argument("--list", action="store_true", dest="show", help="List the agent's tokens.")
        parser.add_argument("--revoke", metavar="PREFIX", help="Revoke the active token that starts with PREFIX.")

    def handle(self, *args, slug, name, tool, show, revoke, **options):
        user = get_user_model().objects.filter(username=f"agent:{slug}").first()
        if user is None:
            raise CommandError(f"no agent user agent:{slug} — run sync_agents first")
        tokens = AgentToken.objects.filter(user=user).order_by("-created_at")
        if show:
            for token in tokens:
                state = f"revoked {token.revoked_at:%Y-%m-%d}" if token.revoked_at else "active"
                self.stdout.write(
                    f"{token.prefix}…  {token.name}  {'+'.join(token.tools) or 'all its tools'}  {state}  "
                    f"last used {token.last_used_at or 'never'}"
                )
            return
        if revoke:
            shown = AgentToken._meta.get_field("prefix").max_length
            found = tokens.filter(prefix__startswith=revoke[:shown], revoked_at__isnull=True)
            if found.count() != 1:
                raise CommandError(
                    f"{found.count()} active tokens of {user.username} start with {revoke[:shown]}; name exactly one"
                )
            found.get().revoke()
            self.stderr.write(f"revoked {revoke[:shown]}…")
            return
        if not name:
            raise CommandError("--name is required to issue a token")
        token, raw = AgentToken.issue(user, name=name, tools=tool)
        self.stdout.write(raw)
        self.stderr.write(f"issued {token} for {user.username}; store it now, it is not shown again")
