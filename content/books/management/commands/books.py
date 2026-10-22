"""`manage.py books <command>`: the bookshelf CLI's commands on the platform's
books (books/services.py), with its output:

    books list [--status S] [--json]          every book, with status and progress
    books show <slug> [--json]                one book, chapter by chapter
    books new [<slug>] --title … [--logline …] [--genre …]   a book from the template
    books add-chapter <slug> --title … [--number N] [--act N]
    books validate [<slug> …] [--strict] [--json]   schema and continuity checks; exit 1 on errors
    books stats [<slug> …] [--json]           narrative-only word counts and progress
    books build [<slug> …] [--out DIR] [--include-outline]   <DIR>/<slug>/manuscript.md
    books dashboard [--out DIR]               <DIR>/index.html and <DIR>/library.json
    books context <slug> [--chapter N] [--task T]   what a book task's model would be given

Books are found by their directory name in the library (`--site`, default
BOOKS_SITE_KEY); `dist/` beside the library is the default output. `new` and
`add-chapter` write draft revisions as `--user` (default `legacy:import`): an
operator at the shell is not held to page permissions. The AI tasks themselves
run from the studio, as runs a person starts.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from agents.principals import ensure_legacy_import_user
from books import context, files, library, services
from ops.errors import ApiError


def _table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    lines += ["  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip() for row in rows]
    return "\n".join(lines)


def _bar(fraction: float, width: int = 12) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return "#" * filled + "." * (width - filled)


class Command(BaseCommand):
    help = "The bookshelf's commands: list, show, new, add-chapter, validate, stats, build, dashboard, context."

    def add_arguments(self, parser):
        parser.add_argument("--site", default=None, help="The library's site key (default: BOOKS_SITE_KEY).")
        parser.add_argument("--user", default=None, help="Who writes new books and chapters (default: legacy:import).")
        sub = parser.add_subparsers(dest="command", required=True)
        listing = sub.add_parser("list")
        listing.add_argument("--status")
        listing.add_argument("--json", action="store_true")
        show = sub.add_parser("show")
        show.add_argument("slug")
        show.add_argument("--json", action="store_true")
        new = sub.add_parser("new")
        new.add_argument("slug", nargs="?")
        new.add_argument("--title", required=True)
        new.add_argument("--logline", default="")
        new.add_argument("--genre", default="")
        chapter = sub.add_parser("add-chapter")
        chapter.add_argument("slug")
        chapter.add_argument("--title", required=True)
        chapter.add_argument("--number", type=int)
        chapter.add_argument("--act", type=int)
        validate = sub.add_parser("validate")
        validate.add_argument("slugs", nargs="*")
        validate.add_argument("--strict", action="store_true")
        validate.add_argument("--json", action="store_true")
        stats = sub.add_parser("stats")
        stats.add_argument("slugs", nargs="*")
        stats.add_argument("--json", action="store_true")
        build = sub.add_parser("build")
        build.add_argument("slugs", nargs="*")
        build.add_argument("--out")
        build.add_argument("--include-outline", action="store_true")
        dashboard = sub.add_parser("dashboard")
        dashboard.add_argument("--out")
        ask = sub.add_parser("context")
        ask.add_argument("slug")
        ask.add_argument("--chapter", type=int)
        ask.add_argument("--task", default="draft", choices=sorted(context.TASKS))

    def handle(self, *args, command, site=None, user=None, **options):
        self.site = site or settings.BOOKS_SITE_KEY
        self.user = user
        try:
            return getattr(self, f"do_{command.replace('-', '_')}")(**options)
        except (ApiError, ValidationError) as e:
            raise CommandError(getattr(e, "message", None) or "; ".join(e.messages)) from e

    # ── helpers ───────────────────────────────────────────────────────────
    def books(self, slugs=None):
        if slugs:
            return [services.by_slug(slug, self.site) for slug in slugs]
        return [b.specific for b in files.library_books(self.site) if not services.is_template(b)]

    def author(self):
        if self.user is None:
            return ensure_legacy_import_user()
        found = get_user_model().objects.filter(username=self.user).first()
        if found is None:
            raise CommandError(f"no user {self.user!r}")
        return found

    def json(self, payload) -> None:
        self.stdout.write(json.dumps(payload, indent=2))

    def out_dir(self, out) -> Path:
        return Path(out) if out else Path(settings.BOOKS_LIBRARY_DIR).parent / "dist"

    def prefix(self) -> str:
        return Path(settings.BOOKS_LIBRARY_DIR).name

    # ── commands ──────────────────────────────────────────────────────────
    def do_list(self, status=None, json=False, **options):
        books = [(b, services.read(b)) for b in self.books()]
        books = [(b, rm) for b, rm in books if not status or rm.status == status]
        if json:
            return self.json([library.book_to_dict(rm, self.prefix()) for _b, rm in books])
        if not books:
            self.stdout.write('No books found. Run `manage.py books new <slug> --title "..."` to start one.')
            return
        rows = [
            [
                rm.slug,
                rm.title,
                rm.status,
                f"{len(rm.chapters)}/{rm.planned_chapters}",
                f"{rm.word_count:,}",
                f"{_bar(rm.progress)} {round(rm.progress * 100):>3}%",
            ]
            for _b, rm in books
        ]
        self.stdout.write(_table(rows, ["SLUG", "TITLE", "STATUS", "CH", "WORDS", "PROGRESS"]))
        self.stdout.write(f"\n{len(books)} book(s), {sum(rm.word_count for _b, rm in books):,} words of prose.")

    def do_show(self, slug, json=False, **options):
        rm = services.read(services.by_slug(slug, self.site))
        if json:
            return self.json(library.book_to_dict(rm, self.prefix()))
        self.stdout.write(f"{rm.title}  ({rm.slug})")
        if rm.meta.get("subtitle"):
            self.stdout.write(f"  {rm.meta['subtitle']}")
        if rm.logline:
            self.stdout.write(f"\n{rm.logline}")
        self.stdout.write("")
        target = f" of {rm.target_word_count:,}" if rm.target_word_count else ""
        facts = [
            ("status", rm.status),
            ("genre", rm.genre),
            ("pov", rm.pov),
            ("acts", str(rm.acts)),
            ("chapters", f"{len(rm.chapters)} of {rm.planned_chapters} planned"),
            ("words", f"{rm.word_count:,}{target}"),
            ("tags", ", ".join(sorted(set(library.as_list(rm.meta.get("tags")))))),
            ("cast", ", ".join(sorted(set(rm.cast)))),
        ]
        for label, value in facts:
            if value:
                self.stdout.write(f"  {label:<10} {value}")
        if rm.chapters:
            rows = [
                [str(c.number or "?"), c.title, str(c.act or "-"), c.status, c.pov or "-", f"{c.word_count:,}"]
                for c in rm.chapters
            ]
            self.stdout.write("\n" + _table(rows, ["#", "TITLE", "ACT", "STATUS", "POV", "WORDS"]))

    def do_new(self, slug=None, title="", logline="", genre="", **options):
        parent = services.library_root()
        book = services.new_book(
            parent, self.author(), title=title, slug=slug or "", logline=logline, genre=genre, check=False
        )
        self.stdout.write(f"Created {self.prefix()}/{book.slug} (a draft; export_books writes its files)")
        self.stdout.write(f'Next: write its outline, then `manage.py books add-chapter {book.slug} --title "..."`')

    def do_add_chapter(self, slug, title="", number=None, act=None, **options):
        book = services.by_slug(slug, self.site)
        chapter = services.add_chapter(book, self.author(), title=title, number=number, act=act, check=False)
        self.stdout.write(f"Created chapter {chapter.number}: {chapter.title} ({self.prefix()}/{slug}/chapters)")

    def do_validate(self, slugs=None, strict=False, json=False, **options):
        books = self.books(slugs)
        issues = [issue for book in books for issue in services.validate(book)]
        errors = sum(1 for i in issues if i.level == library.ERROR)
        warnings = len(issues) - errors
        failed = bool(errors or (strict and warnings))
        if json:
            self.json([issue.as_dict() for issue in issues])
        elif not issues:
            self.stdout.write(f"No problems found in {len(books)} book(s).")
        else:
            for issue in issues:
                self.stdout.write(issue.format())
            tally: dict[str, int] = {}
            for issue in issues:
                tally[issue.code] = tally.get(issue.code, 0) + 1
            self.stdout.write("\nBy check:")
            for code, count in sorted(tally.items(), key=lambda item: (-item[1], item[0])):
                self.stdout.write(f"  {count:>4}  {code}")
            self.stdout.write(f"\n{errors} error(s), {warnings} warning(s) across {len(books)} book(s).")
        if failed:
            raise SystemExit(1)

    def do_stats(self, slugs=None, json=False, **options):
        books = [services.read(b) for b in self.books(slugs)]
        if json:
            data = [library.book_to_dict(rm, self.prefix()) for rm in books]
            return self.json({"books": data, "word_count": sum(rm.word_count for rm in books)})
        for rm in books:
            s = services.stats(rm)
            breakdown = ", ".join(f"{n} {status}" for status, n in sorted(s["status_counts"].items())) or "no chapters"
            target = f" of {rm.target_word_count:,}" if rm.target_word_count else ""
            self.stdout.write(f"{rm.title} ({rm.slug})")
            self.stdout.write(f"  chapters   {s['chapters']} ({breakdown})")
            self.stdout.write(f"  words      {rm.word_count:,}{target}")
            if rm.chapters:
                self.stdout.write(f"  average    {s['average']:,} words per chapter")
                for label in ("longest", "shortest"):
                    c = s[label]
                    self.stdout.write(f"  {label:<10} ch{c['number']} {c['title']} ({c['word_count']:,})")
            self.stdout.write(f"  progress   {_bar(rm.progress)} {round(rm.progress * 100)}%\n")

    def do_build(self, slugs=None, out=None, include_outline=False, **options):
        out = self.out_dir(out)
        for book in self.books(slugs):
            rm = services.read(book)
            path = out / rm.slug / "manuscript.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(library.manuscript(rm, include_outline=include_outline), encoding="utf-8")
            self.stdout.write(f"Wrote {path} ({rm.word_count:,} words)")

    def do_dashboard(self, out=None, **options):
        out = self.out_dir(out)
        out.mkdir(parents=True, exist_ok=True)
        books = self.books()
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        (out / "index.html").write_text(services.dashboard(books, generated=stamp), encoding="utf-8")
        (out / "library.json").write_text(json.dumps(services.library_data(books), indent=2) + "\n", encoding="utf-8")
        self.stdout.write(f"Wrote {out / 'index.html'} and {out / 'library.json'}")

    def do_context(self, slug, chapter=None, task="draft", **options):
        rm = services.read(services.by_slug(slug, self.site))
        found = rm.chapter(chapter) if chapter is not None else None
        if chapter is not None and found is None:
            raise CommandError(f"{slug} has no chapter {chapter}")
        self.stdout.write(context.request(rm, found, context.TASKS[task]))
