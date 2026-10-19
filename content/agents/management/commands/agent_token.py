"""`manage.py agent_token SLUG --name NAME [--tool T ...]`: issue a bearer token
for an agent's user, for an MCP client or the Rails plane. The token is
printed once; only its hash is stored."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from agents.models import AgentToken


class Command(BaseCommand):
    help = "Issue an agent token."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--name", required=True)
        parser.add_argument("--tool", action="append", default=[])

    def handle(self, *args, slug, name, tool, **options):
        user = get_user_model().objects.filter(username=f"agent:{slug}").first()
        if user is None:
            raise CommandError(f"no agent user agent:{slug} — run sync_agents first")
        token, raw = AgentToken.issue(user, name=name, tools=tool)
        self.stdout.write(raw)
        self.stderr.write(f"issued {token} for {user.username}; store it now, it is not shown again")
