"""`manage.py substack {feed,copy,sync} --book PATH …` — a book's chapters to
Substack (distribution/substack/). It touches no database: the book is its
`library/<slug>/` files and the ledger is a file (`--ledger`).

  feed  write the RSS feed Substack's importer reads (sanctioned; published chapters only)
  copy  write a paste-ready HTML + Markdown copy of every chapter (sanctioned)
  sync  push through the unofficial adapter — refused unless ZER0_SUBSTACK_UNOFFICIAL is on

Configuration is settings (from the environment, docs/SUBSTACK.md): SUBSTACK_PUBLICATION_URL,
SUBSTACK_CANONICAL_BASE, SUBSTACK_SESSION_COOKIE, ZER0_SUBSTACK_UNOFFICIAL, ZER0_SUBSTACK_PUBLISH.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from distribution.ledger import Ledger
from distribution.substack.adapters import CopyAdapter, FeedAdapter, SubstackError, UnofficialApiAdapter
from distribution.substack.chapters import load_book
from distribution.substack.sync import sync


class Command(BaseCommand):
    help = "A book's chapters to Substack: feed (RSS for its importer), copy (paste-ready), sync (unofficial, off)"
    requires_system_checks: list = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=["feed", "copy", "sync"])
        parser.add_argument("--book", required=True, help="the book's directory, e.g. packages/books/library/cost-line")
        parser.add_argument("--out", help="feed: the .xml file; copy: the directory (required for both)")
        parser.add_argument(
            "--ledger",
            required=True,
            help="the ledger file — outside the book: library/<slug>/ is a generated tree",
        )
        parser.add_argument("--canonical-base", default=None, help="overrides SUBSTACK_CANONICAL_BASE")
        parser.add_argument("--force", action="store_true", help="send past an unconfirmed attempt you checked")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, mode, book, out, ledger, canonical_base, force, dry_run, **options):
        root = Path(book)
        if mode != "sync" and not out:
            raise CommandError(f"{mode} needs --out, outside the book: library/<slug>/ is a generated tree")
        base = canonical_base if canonical_base is not None else getattr(settings, "SUBSTACK_CANONICAL_BASE", "")
        try:
            chapters = load_book(root, canonical_base=base)
        except (OSError, ValueError) as e:
            raise CommandError(str(e)) from e
        publication = getattr(settings, "SUBSTACK_PUBLICATION_URL", "")
        try:
            if mode == "feed":
                title = chapters[0].series_title if chapters else root.name
                adapter = FeedAdapter(out, title=title, link=base or publication)
            elif mode == "copy":
                adapter = CopyAdapter(out)
            else:
                adapter = UnofficialApiAdapter(
                    publication_url=publication,
                    session_cookie=getattr(settings, "SUBSTACK_SESSION_COOKIE", ""),
                    enabled=getattr(settings, "ZER0_SUBSTACK_UNOFFICIAL", False),
                    publish=getattr(settings, "ZER0_SUBSTACK_PUBLISH", False),
                )
        except SubstackError as e:
            raise CommandError(e.message) from e
        report = sync(chapters, adapter, Ledger(ledger), force=force, dry_run=dry_run)
        for o in report.outcomes:
            self.stdout.write(f"ch{o.chapter:02d} {o.status:<11} {o.key} {o.detail}".rstrip())
        self.stdout.write(json.dumps({"adapter": report.adapter, **report.counts()}, sort_keys=True))
        if not report.ok:
            raise CommandError("some chapters did not sync — see above")
