"""A site's voice as the platform holds it today, composed in one place (ADR 0010, step V0).

Read-only: nothing here changes what a writer is told or what a gate refuses.
`resolve` reads the stores that already carry a voice — the guard's built-in
lists, every active `cms.BrandRules`, the site's `SiteSettings`, AIEO's
`BrandContext`, a book's style guide and switch, a chapter's tone and style,
and a distribution channel's limits — in the order the guard and `brand.rules`
apply them, and says of each layer who reads it (`READERS`). `brand.rules`
answers from `told`, so the tool and the studio's Voice tab cannot disagree.

A resolution never makes a row: the settings and the brand context are read
with `filter().first()`, not `for_site`, which would create them. Who may see
it is the view's question (voice/views.py), not this module's: AIEO's brand
context reaches only a site's editors, and a book's material only someone who
may open the page.
"""

import hashlib
import json
import re

from suggestions.guard import BANNED_PATTERNS, FILLER, FOLD, MAX_LEN, builtin_bans

# Every reader of a voice in the platform today: a short name for a column and what it is. The AI panel reads no
# layer — an assistant run on a page is told only its own instructions — and is listed so that gap shows (ADR 0010).
READERS = {
    "guard": ("Suggestion guard", "the brand guard on an agent's suggestion, at propose and at accept"),
    "review": ("Brand review", "the brand review task in the Editorial workflow"),
    "eval": ("Evals", "the brand_clean check of an agent's evals"),
    "distribution": ("Post guard", "the brand guard on a distribution post"),
    "brand_rules": ("brand.rules", "agents and assistants that call the brand.rules tool"),
    "aieo": ("AIEO agents", "AIEO's agents"),
    "book": ("Book tasks", "a book task's context (draft, continue, revise, check)"),
    "ai_panel": ("AI panel", "the editor's AI panel: an assistant run on a page is told its own instructions only"),
}
GATES = ["guard", "review", "eval", "distribution"]


def _ban(name, pattern, flags="i", level="error") -> dict:
    """A ban as the guard would read it: `valid` false (with why) when the guard skips it."""
    entry = {"name": name, "pattern": pattern, "flags": flags, "level": level, "valid": True, "why": ""}
    if not isinstance(name, str) or not isinstance(pattern, str):
        return {
            **entry,
            "name": str(name or ""),
            "pattern": str(pattern or ""),
            "valid": False,
            "why": "not a name and a pattern",
        }
    try:
        re.compile(pattern)
    except re.error as e:
        return {**entry, "valid": False, "why": f"not a regular expression: {e}"}
    return entry


def _entries(raw) -> list[dict]:
    """A stored `banned_patterns` list as bans. An entry that is a mapping keeps the name `brand.rules` lists for
    it (`listed`, whatever it is); anything else is shown as skipped and listed nowhere, as the tool never did."""
    out = []
    for item in raw or []:
        if isinstance(item, dict):
            ban = _ban(item.get("name"), item.get("pattern"), str(item.get("flags", "i")))
            out.append({**ban, "listed": item.get("name")})
        else:
            out.append({**_ban(None, None), "why": "not a {name, pattern} entry"})
    return out


def _layer(key, label, scope, source, edit, readers, *, guidance=(), bans=(), limits=None, active=True, lifted_by=""):
    return {
        "key": key,
        "label": label,
        "scope": scope,
        "source": source,
        "edit": edit,
        "readers": list(readers),
        "guidance": [{"label": g_label, "text": text} for g_label, text in guidance if text],
        "bans": list(bans),
        "limits": limits or {},
        "active": active,
        "lifted_by": lifted_by,
        "hidden": False,
    }


def _book_of(page):
    """The book a chapter or a book page belongs to, as its latest revision (where the studio saves it), or None."""
    from cms.models import BookPage, ChapterPage

    specific = getattr(page, "specific", page)
    if isinstance(specific, ChapterPage):
        parent = specific.get_parent().specific
        return parent.get_latest_revision_as_object() if isinstance(parent, BookPage) else None
    if isinstance(specific, BookPage):
        return specific.get_latest_revision_as_object()
    return None


def _filler(*, post: bool) -> list[dict]:
    """The built-in warnings as the guard applies them (suggestions/guard.py `_filler`): one that shares an error's
    name never fires, because the error catches the same words first; the exclamation mark is never checked on a
    page, and on a post the commentary guard warns on it with a check of its own."""
    errors = {name for name, _ in BANNED_PATTERNS}
    out = []
    for pattern, name in FILLER:
        ban = _ban(name, pattern.pattern, level="warning")
        if name in errors:
            ban.update(valid=False, why="never fires: the error of the same name catches it first")
        elif name == "exclamation mark" and not post:
            ban.update(valid=False, why="not checked on a page; a post's commentary guard warns on it")
        out.append(ban)
    return out


def _unfilled(value: str, template: str) -> bool:
    """Empty, or still AIEO's template — whitespace aside, which saving through the API trims."""
    return not value.split() or value.split() == template.split()


def _lifted_by(page, own) -> str:
    """Who switched the built-in bans off for a chapter the guard's `builtin_bans` says they are off for."""
    return "site" if own is not None and own.chapter_builtin_bans is False else "book"


def resolve(site, *, page=None, channel=None) -> dict:
    """Every layer of voice that holds for `page` on `site` (and, for a post, `channel`), in the order applied."""
    from aieo.models import CONTEXT_TEMPLATES, BrandContext
    from cms.models import BrandRules, ChapterPage
    from sites.models import SiteSettings

    own = SiteSettings.objects.filter(site=site).first() if site is not None else None
    # A post's text is commentary: the distribution guard holds the built-in lists whatever the page is.
    builtin_on = channel is not None or builtin_bans(page)
    layers = [
        _layer(
            "builtin",
            "Built-in bans",
            "platform",
            "suggestions/guard.py — code, the same for every site",
            "",  # code: no screen changes it (ADR 0010 VD1 proposes a starter profile instead)
            [*GATES, "brand_rules"],
            bans=[_ban(name, p.pattern) for name, p in BANNED_PATTERNS] + _filler(post=channel is not None),
            active=builtin_on,
            lifted_by="" if builtin_on else _lifted_by(page, own),
        )
    ]
    for rules in BrandRules.objects.filter(is_active=True):
        layers.append(
            _layer(
                f"brand-rules-{rules.pk}",
                f"Brand rules: {rules.name}",
                "platform",
                "cms.BrandRules — a snippet that holds for every site",
                "Wagtail admin → Snippets → Brand rules",
                [*GATES, "brand_rules"],
                guidance=[("Style guide", rules.style_guide)],
                bans=_entries(rules.banned_patterns),
            )
        )
    if own is not None:
        layers.append(
            _layer(
                "site",
                "Site settings",
                "site",
                "sites.SiteSettings — brand voice and banned phrases",
                "Sites → this site → Settings",
                [*GATES, "brand_rules"],
                guidance=[("Brand voice", own.brand_voice)],
                bans=_entries(own.banned_patterns),
            )
        )
    context = BrandContext.objects.filter(site=site).first() if site is not None else None
    if context is not None:
        filled = [
            (label, value)
            for field, label in (
                ("brand_voice", "Brand voice"),
                ("style_guide", "Style guide"),
                ("writing_examples", "Writing examples"),
            )
            if not _unfilled(value := getattr(context, field) or "", CONTEXT_TEMPLATES[field])
        ]
        layers.append(
            _layer(
                "aieo",
                "AIEO brand context",
                "site",
                "aieo.BrandContext — a second copy of the site's voice, for AIEO",
                "Sites → AIEO → Context",
                ["aieo"],
                guidance=filled,
            )
        )
    book = _book_of(page) if page is not None else None
    if book is not None:
        layers.append(
            _layer(
                "book",
                f"Book: {book.title}",
                "book",
                "cms.BookPage — its style guide and its switch for the built-in bans",
                "Books → this book → Overview and Style guide",
                ["book"],
                guidance=[("Style guide", book.style_guide)],
            )
        )
    specific = getattr(page, "specific", page)
    if isinstance(specific, ChapterPage):
        chapter = specific.get_latest_revision_as_object()
        hints = [("Tone", ", ".join(chapter.tone or [])), ("Style", ", ".join(chapter.style or []))]
        if any(text for _, text in hints):
            layers.append(
                _layer(
                    "chapter",
                    f"Chapter: {chapter.title}",
                    "chapter",
                    "cms.ChapterPage — its front matter's tone and style",
                    "Books → this chapter → Fields",
                    ["book"],
                    guidance=hints,
                )
            )
    if channel is not None:
        limits = {"max_length": MAX_LEN, "fold": FOLD}
        if channel.kind == "linkedin":
            limits["max_escaped_length"] = MAX_LEN  # LinkedIn's limit once its text is escaped (lane/pipeline.py)
        layers.append(
            _layer(
                "channel",
                f"Channel: {channel.name}",
                "channel",
                "distribution.Channel — the commentary guard's limits; a channel holds no voice of its own",
                "Distribution → Channels",
                ["distribution"],
                limits=limits,
            )
        )
    return {"layers": layers, "digest": digest(layers)}


def digest(layers) -> str:
    """The sha256 of what the layers say — not who reads them or where they are edited."""
    said = [
        {k: layer[k] for k in ("key", "active", "guidance", "limits")}
        | {"bans": [{k: b[k] for k in ("name", "pattern", "flags", "level")} for b in layer["bans"]]}
        for layer in layers
    ]
    return hashlib.sha256(json.dumps(said, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def told(resolved) -> dict:
    """What the `brand.rules` tool tells an agent: the BrandRules' style guides and the site's voice, and the names
    of the built-in errors (unless lifted), then every BrandRules' and the site's ban — as the tool always has."""
    layers = resolved["layers"]
    rules = [layer for layer in layers if layer["key"].startswith("brand-rules-")]
    site = [layer for layer in layers if layer["key"] == "site"]
    builtin = next(layer for layer in layers if layer["key"] == "builtin")
    return {
        "style_guides": [g["text"] for layer in rules + site for g in layer["guidance"]],
        "banned": ([b["name"] for b in builtin["bans"] if b["level"] == "error"] if builtin["active"] else [])
        + [b["listed"] for layer in rules + site for b in layer["bans"] if "listed" in b],
    }
