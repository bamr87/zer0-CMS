"""`manage.py mcp_stdio --agent SLUG`: the MCP server over stdio, for an IDE or
a CLI on the same machine. One JSON-RPC message per line in, one per line
out. Whoever can run this command can already reach the database, so the
agent is named rather than token-authenticated; it still acts only as
`agent:<slug>`, through the same registry checks as HTTP."""

import json
import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from mcp_server.protocol import PARSE_ERROR, Principal, error, handle


class Command(BaseCommand):
    help = "Serve the content plane's tools over MCP stdio."

    def add_arguments(self, parser):
        parser.add_argument("--agent", required=True)

    def handle(self, *args, agent, **options):
        user = get_user_model().objects.filter(username=f"agent:{agent}", is_active=True).first()
        if user is None:
            raise CommandError(f"no active agent user agent:{agent}")
        principal = Principal.for_user(user)
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                reply = error(None, PARSE_ERROR, "not JSON")
            else:
                with transaction.atomic():
                    reply = handle(message, principal)
            if reply is not None:
                sys.stdout.write(json.dumps(reply, default=str) + "\n")
                sys.stdout.flush()
