"""Render the library as a single self-contained HTML page.

No build step, no network, no external assets -- open ``dist/index.html`` in a
browser and the whole shelf is there: a hero total, stat tiles, one card per
book with a progress meter and chapter table, and any validation findings.

Colour follows the project's data-visualisation reference palette. Only two
roles are used: a single sequential blue ramp for the progress meters
(magnitude) and the reserved status palette for validation state (state).
Lifecycle values such as "drafting" are *not* severities, so they render as
neutral chips rather than borrowing a reserved status colour.
"""

from __future__ import annotations

import html
from pathlib import Path

from .models import Book, Issue
from .validate import ERROR, WARNING

_STYLE = """
:root {
  color-scheme: light;
  --plane: #f9f9f7;
  --surface: #fcfcfb;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --rule: #e1e0d9;
  --border: rgba(11, 11, 11, 0.10);
  /* Sequential blue ramp. Track is step 200, not the lightest step: at 1.29:1
     against the surface step 100 disappears, so a barely-started book would
     read as no meter at all. Step 200 is 1.74:1 vs surface, 2.47:1 vs fill. */
  --meter-fill: #2a78d6;
  --meter-track: #9ec5f4;
  --good: #0ca30c;
  --warning: #fab219;
  --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --plane: #0d0d0d;
    --surface: #1a1a19;
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --rule: #2c2c2a;
    --border: rgba(255, 255, 255, 0.10);
    --meter-fill: #3987e5;
    --meter-track: #184f95;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0d0d0d;
  --surface: #1a1a19;
  --ink: #ffffff;
  --ink-2: #c3c2b7;
  --muted: #898781;
  --rule: #2c2c2a;
  --border: rgba(255, 255, 255, 0.10);
  --meter-fill: #3987e5;
  --meter-track: #184f95;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2rem 1.25rem 4rem;
  background: var(--plane);
  color: var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.5;
}
.wrap { max-width: 68rem; margin: 0 auto; }
h1 { font-size: 1.25rem; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
h2 { font-size: 1.05rem; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
p { margin: 0; }
a { color: inherit; }

header { margin-bottom: 2rem; }
.sub { color: var(--ink-2); font-size: 0.875rem; margin-top: 0.25rem; }

.hero { margin: 1.75rem 0 0.25rem; }
.hero .value { font-size: 3.25rem; font-weight: 600; line-height: 1; letter-spacing: -0.03em; }
.hero .label { color: var(--ink-2); font-size: 0.875rem; margin-top: 0.35rem; }

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
  gap: 0.75rem;
  margin: 1.5rem 0 2.25rem;
}
.tile {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 0.85rem 1rem;
}
.tile .value { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.02em; }
.tile .label { color: var(--ink-2); font-size: 0.8125rem; }

.book {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 1.25rem;
  margin-bottom: 1rem;
}
.book-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.5rem 0.75rem; }
.slug { color: var(--muted); font-size: 0.8125rem; }
.logline { color: var(--ink-2); font-size: 0.9375rem; margin-top: 0.5rem; max-width: 52rem; }

.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0.1rem 0.55rem;
  font-size: 0.75rem;
  color: var(--ink-2);
  white-space: nowrap;
}
.dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; flex: none; }
.dot.good { background: var(--good); }
.dot.warning { background: var(--warning); }
.dot.critical { background: var(--critical); }

.meter-row { display: flex; align-items: center; gap: 0.75rem; margin: 1rem 0 0.35rem; }
.meter { flex: 1; height: 0.5rem; border-radius: 999px; background: var(--meter-track); overflow: hidden; }
.meter > span { display: block; height: 100%; border-radius: 999px; background: var(--meter-fill); }
.meter-value { font-size: 0.8125rem; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.meter-note { color: var(--muted); font-size: 0.8125rem; }

.scroll { overflow-x: auto; margin-top: 1rem; }
table { border-collapse: collapse; width: 100%; font-size: 0.875rem; }
caption { text-align: left; color: var(--muted); font-size: 0.8125rem; padding-bottom: 0.4rem; }
th, td {
  text-align: left;
  padding: 0.4rem 0.75rem 0.4rem 0;
  border-bottom: 1px solid var(--rule);
  white-space: nowrap;
}
th { color: var(--muted); font-weight: 500; font-size: 0.8125rem; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; padding-right: 1.25rem; }
td.wide { white-space: normal; min-width: 14rem; }

details { margin-top: 1rem; }
summary { cursor: pointer; font-size: 0.875rem; color: var(--ink-2); }
.issues { list-style: none; margin: 0.6rem 0 0; padding: 0; font-size: 0.8125rem; }
.issues li { display: flex; gap: 0.5rem; padding: 0.2rem 0; align-items: baseline; }
.issues code { color: var(--muted); font-size: 0.75rem; }
.empty { color: var(--muted); font-size: 0.875rem; font-style: italic; }
footer { color: var(--muted); font-size: 0.8125rem; margin-top: 2.5rem; }
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _compact(number: int) -> str:
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M".replace(".0M", "M")
    if number >= 10_000:
        return f"{number / 1000:.0f}K"
    return f"{number:,}"


def _validation_chip(issues: list[Issue]) -> str:
    errors = sum(1 for issue in issues if issue.level == ERROR)
    warnings = sum(1 for issue in issues if issue.level == WARNING)
    if errors:
        return f'<span class="chip"><span class="dot critical"></span>{errors} error{"s" if errors != 1 else ""}</span>'
    if warnings:
        plural = "s" if warnings != 1 else ""
        return f'<span class="chip"><span class="dot warning"></span>{warnings} warning{plural}</span>'
    return '<span class="chip"><span class="dot good"></span>clean</span>'


def _chapter_table(book: Book) -> str:
    if not book.chapters:
        return '<p class="empty">No chapters yet.</p>'
    rows = []
    for chapter in book.chapters:
        rows.append(
            "<tr>"
            f'<td class="num">{_esc(chapter.number or "")}</td>'
            f"<td class=\"wide\">{_esc(chapter.title)}</td>"
            f"<td>{_esc(chapter.act or '')}</td>"
            f"<td>{_esc(chapter.status)}</td>"
            f"<td>{_esc(chapter.pov or '—')}</td>"
            f"<td>{_esc(', '.join(chapter.characters) or '—')}</td>"
            f'<td class="num">{chapter.word_count:,}</td>'
            "</tr>"
        )
    return (
        '<div class="scroll"><table>'
        f"<caption>{len(book.chapters)} chapters</caption>"
        '<thead><tr><th class="num">#</th><th>Title</th><th>Act</th><th>Status</th>'
        '<th>POV</th><th>Characters</th><th class="num">Words</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _issue_list(book: Book, issues: list[Issue], root: Path) -> str:
    if not issues:
        return ""
    items = []
    for issue in issues:
        level = "critical" if issue.level == ERROR else "warning"
        try:
            location = str(issue.path.relative_to(root))
        except ValueError:
            location = str(issue.path)
        if issue.line:
            location += f":{issue.line}"
        items.append(
            f'<li><span class="dot {level}" aria-hidden="true"></span>'
            f"<span><strong>{_esc(issue.level)}</strong> {_esc(issue.message)} "
            f"<code>{_esc(location)}</code></span></li>"
        )
    return (
        f"<details><summary>{len(issues)} validation finding"
        f"{'s' if len(issues) != 1 else ''}</summary>"
        f'<ul class="issues">{"".join(items)}</ul></details>'
    )


def _book_card(book: Book, issues: list[Issue], root: Path) -> str:
    percent = round(book.progress * 100)
    if book.target_word_count:
        note = f"{book.word_count:,} of {book.target_word_count:,} words"
    else:
        note = f"{len(book.chapters)} of {book.planned_chapters} planned chapters"

    tags = "".join(f'<span class="chip">{_esc(tag)}</span>' for tag in book.tags[:6])
    logline = f'<p class="logline">{_esc(book.logline)}</p>' if book.logline else ""

    return (
        '<section class="book">'
        '<div class="book-head">'
        f"<h2>{_esc(book.title)}</h2>"
        f'<span class="slug">{_esc(book.slug)}</span>'
        f'<span class="chip">{_esc(book.status)}</span>'
        f"{_validation_chip(issues)}"
        "</div>"
        f"{logline}"
        '<div class="meter-row">'
        f'<div class="meter"><span style="width: {percent}%"></span></div>'
        f'<span class="meter-value">{percent}%</span>'
        "</div>"
        f'<p class="meter-note">{_esc(note)}</p>'
        f"{_chapter_table(book)}"
        f'<div class="book-head" style="margin-top:1rem">{tags}</div>'
        f"{_issue_list(book, issues, root)}"
        "</section>"
    )


def render(books: list[Book], issues: list[Issue], root: Path, generated: str = "") -> str:
    """Render the whole library as one HTML document."""
    by_book: dict[str, list[Issue]] = {book.slug: [] for book in books}
    for issue in issues:
        for book in books:
            if str(issue.path).startswith(str(book.root)):
                by_book[book.slug].append(issue)
                break

    total_words = sum(book.word_count for book in books)
    total_chapters = sum(len(book.chapters) for book in books)
    open_issues = len(issues)
    active = sum(1 for book in books if book.status in ("outlining", "drafting", "revising"))

    tiles = [
        (str(len(books)), "books on the shelf"),
        (str(active), "in active development"),
        (str(total_chapters), "chapters"),
        (_compact(open_issues), "validation findings"),
    ]
    tile_html = "".join(
        f'<div class="tile"><div class="value">{_esc(value)}</div><div class="label">{_esc(label)}</div></div>'
        for value, label in tiles
    )

    cards = "".join(_book_card(book, by_book[book.slug], root) for book in books)
    if not books:
        cards = '<p class="empty">No books yet. Run <code>books new &lt;slug&gt;</code> to start one.</p>'

    footer = "Generated by <code>books dashboard</code>"
    if generated:
        footer += f" · {_esc(generated)}"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bookshelf</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Bookshelf</h1>
  <p class="sub">Every book idea in this repository, and how far along each one is.</p>
  <div class="hero">
    <div class="value">{_compact(total_words)}</div>
    <div class="label">words of narrative prose across the library</div>
  </div>
</header>
<div class="tiles">{tile_html}</div>
{cards}
<footer>{footer}</footer>
</div>
</body>
</html>
"""


def write(books: list[Book], issues: list[Issue], root: Path, out_dir: Path, generated: str = "") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(render(books, issues, root, generated), encoding="utf-8")
    return path
