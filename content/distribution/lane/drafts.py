"""The draft queue of a site's checkout — the folder proposed LinkedIn posts
wait in, and the only place the lane publishes from.

The dialect is the one the VS Code extension (`src/core/governance/drafts.ts`)
and the Ruby lane share, so a queue written by any of them reads the same:

    type:   article | update   (`text` is accepted for update; default article)
    status: pending | approved | published   (default pending)
    source: the page an article shares (a path, or `section/YYYY-MM-DD-slug`)
    title / description / link: an article's own card, for a link that is not a page here
    no_thumbnail: true to post without a card image

The body is the text that publishes. Top-level `*.md` files only, so an
`examples/` folder never publishes, and a file with no front matter (a README)
is documentation, not a draft. A new draft is always `pending`: creating one and
approving one are different acts, and only the second is a person's. Status
changes are line surgery, so approving is a one-line diff in review.
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from books.files import set_keys
from importers import frontmatter

STATUSES = ("pending", "approved", "published")
TYPES = ("article", "update")
ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,150}\Z")
SLUG = re.compile(r"\A[a-z0-9]+(?:-[a-z0-9]+)*\Z")


@dataclass
class Draft:
    path: Path
    relative: str
    meta: dict = field(default_factory=dict)
    body: str = ""

    @property
    def id(self) -> str:
        return self.path.stem

    @property
    def status(self) -> str:
        return str(self.meta.get("status") or "").strip().lower() or "pending"

    @property
    def type(self) -> str:
        value = str(self.meta.get("type") or "").strip().lower()
        return "article" if not value else "update" if value == "text" else value

    @property
    def update(self) -> bool:
        return self.type == "update"

    @property
    def commentary(self) -> str:
        return self.body.strip() or str(self.meta.get("commentary") or "").strip()

    def text(self, key: str) -> str:
        return str(self.meta.get(key) or "").strip()

    @property
    def no_thumbnail(self) -> bool:
        return self.meta.get("no_thumbnail") in (True, "true", "yes", "1")


def directory(config) -> Path:
    return config.path(config.queue)


def read(config, path: Path) -> Draft:
    text = path.read_text(encoding="utf-8")
    try:
        meta, body = frontmatter.split(text)
    except yaml.YAMLError:
        meta, body = None, text
    return Draft(path=path, relative=path.relative_to(config.root).as_posix(), meta=meta or {}, body=body)


def all_drafts(config) -> list[Draft]:
    folder = directory(config)
    if not folder.is_dir():
        return []
    out = []
    for name in sorted(os.listdir(folder)):
        path = folder / name
        if name.endswith(".md") and path.is_file() and not path.is_symlink():
            draft = read(config, path)
            if draft.meta:
                out.append(draft)
    return out


def find(config, ref) -> Draft | None:
    """By id (`2026-07-30-x`), filename (`2026-07-30-x.md`) or queue path — reduced to a name inside the queue."""
    name = os.path.basename(str(ref or "").strip()).removesuffix(".md")
    if not ID.match(name):
        raise ValueError(f"not a draft id: {ref!r}")
    return next((d for d in all_drafts(config) if d.id == name), None)


def find_required(config, ref) -> Draft:
    draft = find(config, ref)
    if draft is None:
        raise ValueError(f"no draft named {ref!r} in {config.queue}")
    return draft


def _scalar(value: str) -> str:
    """A plain YAML scalar when it reads back as the same string, else a double-quoted one."""
    try:
        plain = not value.strip() != value and yaml.safe_load(f"k: {value}") == {"k": value}
    except yaml.YAMLError:
        plain = False
    return value if plain and "\n" not in value else json.dumps(value, ensure_ascii=False)


def create(config, *, type: str, slug: str, body: str, meta: dict | None = None) -> Draft:
    """Write a new pending draft. A name collision becomes `-2`, `-3`, … — never an overwrite."""
    if type not in TYPES:
        raise ValueError("type must be article or update")
    if not SLUG.match(slug or ""):
        raise ValueError(f"draft slug must be lowercase words joined by hyphens: {slug!r}")
    if type == "update" and not str(body or "").strip():
        raise ValueError("a draft needs a body")
    fields = {"type": type, "status": "pending"}
    for key, value in (meta or {}).items():
        if key != "status" and value not in (None, ""):
            fields[key] = str(value)
    text = "---\n" + "".join(f"{k}: {_scalar(v)}\n" for k, v in fields.items()) + f"---\n\n{str(body or '').strip()}\n"
    folder = directory(config)
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(1, 101):
        path = folder / (f"{slug}.md" if n == 1 else f"{slug}-{n}.md")
        try:
            with open(path, "x", encoding="utf-8") as out:
                out.write(text)
        except FileExistsError:
            continue
        return read(config, path)
    raise ValueError(f"too many drafts named {slug}")


def set_status(draft: Draft, status: str, extra: dict | None = None) -> str:
    """Flip `status` (and set any `extra` keys) by line surgery inside the front matter."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    text = draft.path.read_text(encoding="utf-8")
    match = frontmatter.FENCE.match(text)
    if match is None:
        raise ValueError(f"{draft.relative} has no front matter")
    block = set_keys(match.group(1), {"status": status, **(extra or {})})
    updated = text[: match.start(1)] + block + text[match.end(1) :]
    if updated != text:
        draft.path.write_text(updated, encoding="utf-8")
    return status
