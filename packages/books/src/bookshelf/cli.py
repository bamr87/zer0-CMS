"""Command line interface for the bookshelf.

    books list                 every book, with status and progress
    books show <slug>          one book, chapter by chapter
    books new <slug>           start a new book from the template
    books add-chapter <slug>   add the next chapter file
    books validate [slug...]   schema and continuity checks
    books stats [slug...]      word counts and progress
    books build <slug>         compile chapters into one manuscript
    books dashboard            render the library as a static HTML page
    books serve                build the dashboard and serve it locally
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ai, scaffold
from . import build as build_mod
from . import dashboard as dashboard_mod
from .library import Library, LibraryError
from .models import Book, summarise
from .validate import ERROR, WARNING, has_errors, validate_all

PROG = "books"


# -- helpers --------------------------------------------------------------
def _library(args: argparse.Namespace) -> Library:
    return Library.load(args.root)


def _table(rows: list[list[str]], headers: list[str]) -> str:
    if not rows:
        return ""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def _bar(fraction: float, width: int = 12) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return "#" * filled + "." * (width - filled)


def _emit_json(payload: Any) -> int:
    print(json.dumps(payload, indent=2))
    return 0


# -- commands -------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> int:
    library = _library(args)
    books = [book for book in library.books if not args.status or book.status == args.status]
    if args.json:
        return _emit_json([build_mod.book_to_dict(book, library.root) for book in books])
    if not books:
        print("No books found. Run `books new <slug> --title \"...\"` to start one.")
        return 0
    rows = [
        [
            book.slug,
            book.title,
            book.status,
            f"{len(book.chapters)}/{book.planned_chapters}",
            f"{book.word_count:,}",
            f"{_bar(book.progress)} {round(book.progress * 100):>3}%",
        ]
        for book in books
    ]
    print(_table(rows, ["SLUG", "TITLE", "STATUS", "CH", "WORDS", "PROGRESS"]))
    print(f"\n{len(books)} book(s), {sum(b.word_count for b in books):,} words of prose.")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    library = _library(args)
    book = library.get(args.slug)
    if args.json:
        return _emit_json(build_mod.book_to_dict(book, library.root))

    print(f"{book.title}  ({book.slug})")
    if book.meta.get("subtitle"):
        print(f"  {book.meta['subtitle']}")
    if book.logline:
        print(f"\n{book.logline}")
    print()
    facts = [
        ("status", book.status),
        ("genre", book.genre),
        ("pov", book.pov),
        ("acts", str(book.acts)),
        ("chapters", f"{len(book.chapters)} of {book.planned_chapters} planned"),
        ("words", f"{book.word_count:,}" + (f" of {book.target_word_count:,}" if book.target_word_count else "")),
        ("tags", summarise(book.tags)),
        ("cast", summarise(book.cast)),
    ]
    for label, value in facts:
        if value:
            print(f"  {label:<10} {value}")

    if book.chapters:
        print()
        rows = [
            [
                str(chapter.number or "?"),
                chapter.title,
                str(chapter.act or "-"),
                chapter.status,
                chapter.pov or "-",
                f"{chapter.word_count:,}",
            ]
            for chapter in book.chapters
        ]
        print(_table(rows, ["#", "TITLE", "ACT", "STATUS", "POV", "WORDS"]))
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    library = _library(args)
    slug = args.slug or scaffold.slugify(args.title)
    path = scaffold.new_book(
        library.library_dir,
        slug=slug,
        title=args.title,
        template_dir=library.template_dir,
        logline=args.logline or "",
        genre=args.genre or "",
    )
    print(f"Created {path.relative_to(library.root)}")
    outline = (path / Book.OUTLINE).relative_to(library.root)
    print(f'Next: edit {outline}, then `books add-chapter {slug} --title "..."`')
    return 0


def cmd_add_chapter(args: argparse.Namespace) -> int:
    library = _library(args)
    book = library.get(args.slug)
    path = scaffold.new_chapter(book, title=args.title, number=args.number, act=args.act)
    print(f"Created {path.relative_to(library.root)}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    library = _library(args)
    books = library.select(args.slugs)
    issues = validate_all(books)
    if args.json:
        payload = [
            {"level": i.level, "code": i.code, "message": i.message, "path": str(i.path), "line": i.line}
            for i in issues
        ]
        _emit_json(payload)
        return 1 if has_errors(issues) or (args.strict and issues) else 0

    if not issues:
        print(f"No problems found in {len(books)} book(s).")
        return 0
    for issue in issues:
        print(issue.format(library.root))

    tally: dict[str, int] = {}
    for issue in issues:
        tally[issue.code] = tally.get(issue.code, 0) + 1
    print("\nBy check:")
    for code, count in sorted(tally.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count:>4}  {code}")

    errors = sum(1 for issue in issues if issue.level == ERROR)
    warnings = sum(1 for issue in issues if issue.level == WARNING)
    print(f"\n{errors} error(s), {warnings} warning(s) across {len(books)} book(s).")
    return 1 if errors or (args.strict and warnings) else 0


def cmd_stats(args: argparse.Namespace) -> int:
    library = _library(args)
    books = library.select(args.slugs)
    if args.json:
        return _emit_json(
            {
                "books": [build_mod.book_to_dict(book, library.root) for book in books],
                "word_count": sum(book.word_count for book in books),
            }
        )
    for book in books:
        print(f"{book.title} ({book.slug})")
        counts = book.status_counts()
        breakdown = ", ".join(f"{count} {status}" for status, count in sorted(counts.items())) or "no chapters"
        longest = max(book.chapters, key=lambda c: c.word_count, default=None)
        shortest = min(book.chapters, key=lambda c: c.word_count, default=None)
        print(f"  chapters   {len(book.chapters)} ({breakdown})")
        target = f" of {book.target_word_count:,}" if book.target_word_count else ""
        print(f"  words      {book.word_count:,}{target}")
        if book.chapters:
            average = book.word_count // len(book.chapters)
            print(f"  average    {average:,} words per chapter")
            if longest:
                print(f"  longest    ch{longest.number} {longest.title} ({longest.word_count:,})")
            if shortest:
                print(f"  shortest   ch{shortest.number} {shortest.title} ({shortest.word_count:,})")
        print(f"  progress   {_bar(book.progress)} {round(book.progress * 100)}%")
        print()
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    library = _library(args)
    books = library.select(args.slugs)
    out_dir = Path(args.out) if args.out else library.root / build_mod.DEFAULT_OUTPUT_DIR
    for book in books:
        path = build_mod.write_manuscript(book, out_dir, include_outline=args.include_outline)
        words = book.word_count
        shown = path.relative_to(library.root) if path.is_relative_to(library.root) else path
        print(f"Wrote {shown} ({words:,} words)")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    library = _library(args)
    out_dir = Path(args.out) if args.out else library.root / build_mod.DEFAULT_OUTPUT_DIR
    issues = validate_all(library.books)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    path = dashboard_mod.write(library.books, issues, library.root, out_dir, generated=stamp)
    build_mod.write_json(library.books, out_dir / "library.json", library.root)
    print(f"Wrote {path}")
    return 0


def cmd_studio(args: argparse.Namespace) -> int:
    """Run the editor: a local web app for writing and managing the library."""
    from . import server as server_mod

    library = _library(args)
    assistant = ai.Studio(model=args.model, use_fallbacks=not args.no_fallbacks)
    httpd = server_mod.serve(library.root, host=args.host, port=args.port, assistant=assistant)

    url = f"http://{args.host}:{args.port}/"
    print(f"Bookshelf studio on {url}")
    print(f"  library  {library.library_dir}")
    print(f"  books    {len(library.books)}")
    print(f"  model    {args.model}")
    if not _ai_ready():
        print("  note     AI features are off: install with `pip install -e \".[ai]\"` and set ANTHROPIC_API_KEY")
    print("  ctrl-c to stop")

    if args.open:
        import webbrowser

        threading.Timer(0.4, webbrowser.open, args=(url,)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


def _ai_ready() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def cmd_ask(args: argparse.Namespace) -> int:
    """Run one assistant task from the terminal."""
    library = _library(args)
    book = library.get(args.slug)
    task = ai.TASKS.get(args.task)
    if task is None:
        print(f"{PROG}: unknown task {args.task!r}; expected one of {', '.join(ai.TASKS)}", file=sys.stderr)
        return 2

    chapter = book.chapter(args.chapter) if args.chapter else None
    if args.chapter and chapter is None:
        print(f"{PROG}: {book.slug} has no chapter {args.chapter}", file=sys.stderr)
        return 2

    context = ai.context_for(book, chapter)
    assistant = ai.Studio(model=args.model, use_fallbacks=not args.no_fallbacks)
    try:
        if task.schema is not None:
            print(json.dumps(assistant.run_structured(context, task, args.instruction or ""), indent=2))
        else:
            for chunk in assistant.stream(context, task, args.instruction or ""):
                sys.stdout.write(chunk)
                sys.stdout.flush()
            print()
    except ai.AIError as exc:
        print(f"\n{PROG}: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    """Print the material the assistant would be given. No API call."""
    library = _library(args)
    book = library.get(args.slug)
    chapter = book.chapter(args.chapter) if args.chapter else None
    context = ai.context_for(book, chapter)
    print(context.brief)
    if context.local:
        print(context.local)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import http.server
    import socketserver

    library = _library(args)
    out_dir = Path(args.out) if args.out else library.root / build_mod.DEFAULT_OUTPUT_DIR
    issues = validate_all(library.books)
    dashboard_mod.write(library.books, issues, library.root, out_dir, generated="live")
    build_mod.write_json(library.books, out_dir / "library.json", library.root)

    handler = type(
        "Handler",
        (http.server.SimpleHTTPRequestHandler,),
        {
            "__init__": lambda self, *a, **kw: http.server.SimpleHTTPRequestHandler.__init__(
                self, *a, directory=str(out_dir), **kw
            )
        },
    )
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"Serving {out_dir} at http://127.0.0.1:{args.port}/  (ctrl-c to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()
    return 0


# -- parser ---------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="Manage a shelf of book ideas and their contents.")
    parser.add_argument(
        "--root", type=Path, default=None, help="repository root (default: nearest parent with library/)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list", help="list every book")
    listing.add_argument("--status", help="only books with this status")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    show = subparsers.add_parser("show", help="show one book in detail")
    show.add_argument("slug")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    new = subparsers.add_parser("new", help="start a new book from the template")
    new.add_argument("slug", nargs="?", help="directory name (default: slugified title)")
    new.add_argument("--title", required=True)
    new.add_argument("--logline", help="one-sentence pitch")
    new.add_argument("--genre")
    new.set_defaults(func=cmd_new)

    chapter = subparsers.add_parser("add-chapter", help="add a chapter file to a book")
    chapter.add_argument("slug")
    chapter.add_argument("--title", required=True)
    chapter.add_argument("--number", type=int, help="chapter number (default: next free)")
    chapter.add_argument("--act", type=int)
    chapter.set_defaults(func=cmd_add_chapter)

    validate = subparsers.add_parser("validate", help="check schema and continuity")
    validate.add_argument("slugs", nargs="*")
    validate.add_argument("--strict", action="store_true", help="treat warnings as failures")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=cmd_validate)

    stats = subparsers.add_parser("stats", help="word counts and progress")
    stats.add_argument("slugs", nargs="*")
    stats.add_argument("--json", action="store_true")
    stats.set_defaults(func=cmd_stats)

    build_cmd = subparsers.add_parser("build", help="compile chapters into one manuscript")
    build_cmd.add_argument("slugs", nargs="*")
    build_cmd.add_argument("--out", help=f"output directory (default: {build_mod.DEFAULT_OUTPUT_DIR}/)")
    build_cmd.add_argument("--include-outline", action="store_true")
    build_cmd.set_defaults(func=cmd_build)

    dash = subparsers.add_parser("dashboard", help="render the library as a static HTML page")
    dash.add_argument("--out", help=f"output directory (default: {build_mod.DEFAULT_OUTPUT_DIR}/)")
    dash.set_defaults(func=cmd_dashboard)

    serve = subparsers.add_parser("serve", help="build the dashboard and serve it locally")
    serve.add_argument("--out")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    def add_ai_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--model", default=os.environ.get("BOOKSHELF_MODEL", ai.DEFAULT_MODEL))
        sub.add_argument(
            "--no-fallbacks",
            action="store_true",
            help="don't ask the API to retry a declined request on a fallback model",
        )

    studio = subparsers.add_parser("studio", help="open the editor: write, manage and get AI help")
    studio.add_argument("--host", default="127.0.0.1")
    studio.add_argument("--port", type=int, default=4321)
    studio.add_argument("--open", action="store_true", help="open a browser window")
    add_ai_flags(studio)
    studio.set_defaults(func=cmd_studio)

    ask = subparsers.add_parser("ask", help="run one assistant task from the terminal")
    ask.add_argument("slug")
    ask.add_argument("task", help=f"one of: {', '.join(sorted(ai.TASKS))}")
    ask.add_argument("--chapter", type=int, help="chapter number to work on")
    ask.add_argument("--instruction", help="extra guidance for this run")
    add_ai_flags(ask)
    ask.set_defaults(func=cmd_ask)

    context = subparsers.add_parser("context", help="print what the assistant would be given, without calling it")
    context.add_argument("slug")
    context.add_argument("--chapter", type=int)
    context.set_defaults(func=cmd_context)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (LibraryError, scaffold.ScaffoldError) as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
