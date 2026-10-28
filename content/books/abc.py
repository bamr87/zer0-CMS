"""The ABC Book Spec's planning rules, as the deleted Rails generator applied
them (docs/plan/rails-cms-spec.md § rails.abc-generator): how a plate's prompt
is composed from the art-style catalog (`render_prompt`), where its image is
planned (`image_path`), and the spec sidecar a Jekyll site keeps beside an ABC
book, `_data/abc_books/<slug>.json` (`sidecar_path`, `dumps`).

What the platform builds on them so far is an edited letter
(exporters/jekyll.py): a plate whose word or subject changed in the studio is
planned again for it (`replan`) — its image named for the new word, its prompt
composed afresh, its status `planned` — and the sidecar is rewritten to agree
with the exported page (`sidecar_text`), so drsai's
`tools/import_abc_book.py --check` holds. The rest of the generator (the spec
and its validation, the wizard, the cover, the command) is G9's, and starts
from these functions.

The catalog is `data/abc_art_styles.yml`, a byte-identical copy of the image
generator's (workspace.yml `vendored:`): the platform's image carries only
`content/`. Nothing here reads the database.
"""

import json
import posixpath
import re
from functools import cache
from pathlib import Path

import yaml

CATALOG = Path(__file__).resolve().parent / "data" / "abc_art_styles.yml"
SIDECARS = "_data/abc_books"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# The front matter's audience label for each of the spec's audiences (the Rails exporter's).
AUDIENCES = {
    "toddler": "Ages 1–4 (toddler board book)",
    "preschool": "Ages 3–5 (preschool)",
    "early-reader": "Ages 5–7 (early reader)",
}
# The spec's key order (spec.rb `to_h`), a letter's (wizard.rb) and the cover's.
SPEC_KEYS = (
    "spec_version",
    "series",
    "slug",
    "title",
    "subtitle",
    "theme",
    "audience",
    "language",
    "art_style",
    "palette",
    "background",
    "mood",
    "lettering",
    "art_style_prompt",
    "generator",
    "cover",
    "alphabet",
)
ENTRY_KEYS = ("letter", "word", "subject", "tagline", "alt", "prompt", "image", "status")
COVER_KEYS = ("subject", "prompt", "image", "alt")
# What a book's page and its sidecar both hold under one key (jekyll_exporter.rb's front matter);
# the page's cover keys are the cover's image and prompt.
BOOK_KEYS = ("title", "subtitle", "series", "art_style", "art_style_prompt", "palette", "lettering", "generator")
COVER_FROM = {"cover_image": "image", "cover_prompt": "prompt"}
BOOK_STATUSES = ("illustrations-planned", "complete")
_RUBY_SPACE = " \t\n\v\f\r\0"  # what Ruby's String#strip removes


class UnknownStyle(ValueError):
    """An art style the catalog does not have."""


@cache
def catalog() -> dict:
    """The art styles and the option fragments, by id."""
    data = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    options = data.get("options") or {}

    def by_id(items):
        return {item["id"]: item for item in items or []}

    return {
        "styles": by_id(data["styles"]),
        "palettes": by_id(options.get("palettes")),
        "backgrounds": by_id(options.get("backgrounds")),
        "moods": by_id(options.get("moods")),
        "safety_suffix": _squish(data.get("safety_suffix", "")),
    }


def render_prompt(letter, word, subject, style, palette=None, background="plain", mood="playful") -> str:
    """One plate's text-free prompt (art_styles.rb `render_prompt`, the image
    generator's StylePack): the style's prompt, the background, palette (the
    style's own when none), the subject standing for the WORD and the letter,
    the mood and the safety suffix, joined with ". ". An unknown palette,
    background or mood adds nothing; an unknown style is refused."""
    styles = catalog()
    found = styles["styles"].get(style) if isinstance(style, str) else None
    if found is None:
        raise UnknownStyle(f"unknown ABC art style: {style!r} (known: {', '.join(sorted(styles['styles']))})")
    parts = [
        _squish(found["prompt"]),
        _fragment(styles["backgrounds"], background),
        _fragment(styles["palettes"], found.get("default_palette") if palette is None else palette),
        f"Subject: {_strip(subject)}, standing for the word {_strip(word).upper()} (letter {_strip(letter).upper()}).",
        _fragment(styles["moods"], mood),
        styles["safety_suffix"],
    ]
    joined = ". ".join(part for part in parts if part)
    return _squish(re.sub(r"\.\s*\.", ".", joined, flags=re.ASCII))


def slugify(text) -> str:
    """The wizard's slug: lower case, each run of anything but a-z0-9 one hyphen, none at either end."""
    return re.sub(r"[^a-z0-9]+", "-", _strip(text).lower()).strip("-")


def image_path(folder: str, letter: str, word: str) -> str:
    """Where a plate's image is planned: `<folder>/<l>-<word slug>.png`
    (the wizard's folder is `/assets/images/books/<book slug>`)."""
    name = f"{_strip(letter).lower()}-{slugify(word)}.png"
    return f"{folder}/{name}" if folder else name


def replan(entry: dict, *, word: str, subject: str, style, palette=None, background=None, mood=None) -> dict:
    """A page's `alphabet:` entry planned again for a new word or subject, as
    the wizard planned a plate: its image beside the old one, named for the new
    word; its prompt composed for the new word and subject — or left out when
    the style or the subject is unknown, since a prompt naming the old word
    would draw the wrong picture —; and its status `planned`, the value that
    says a plate needs drawing (the spec's other is `rendered`: the theme shows
    a placeholder for `planned`, and drsai's generate_illustrations.py renders
    any image path with no file behind it)."""
    out = dict(entry)
    if isinstance(entry.get("image"), str) and entry["image"]:
        out["image"] = image_path(posixpath.dirname(entry["image"]), str(entry["letter"]), word)
    if "prompt" in entry:
        if subject and isinstance(style, str) and style in catalog()["styles"]:
            background = "plain" if background is None else background  # the spec's defaults
            mood = "playful" if mood is None else mood
            out["prompt"] = render_prompt(entry["letter"], word, subject, style, palette, background, mood)
        else:
            del out["prompt"]
    out["status"] = "planned"
    return out


def book_status(alphabet: list) -> str:
    """The book's front-matter `status`: complete once every plate is rendered."""
    rendered = all(isinstance(e, dict) and e.get("status") == "rendered" for e in alphabet)
    return "complete" if rendered else "illustrations-planned"


def sidecar_path(slug) -> str | None:
    """The spec sidecar of the book `slug` (its front matter's `book:`), or None for no slug or one that is not a slug."""
    return f"{SIDECARS}/{slug}.json" if isinstance(slug, str) and SLUG.fullmatch(slug) else None


def load(text: str) -> dict:
    """A sidecar's spec, or {} for a file that is not one (not a JSON object,
    or an `alphabet` that is not a list of objects, or a `cover` that is not one)."""
    try:
        spec = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(spec, dict) or not isinstance(spec.get("cover", {}), dict):
        return {}
    alphabet = spec.get("alphabet", [])
    return spec if isinstance(alphabet, list) and all(isinstance(e, dict) for e in alphabet) else {}


def dumps(spec: dict) -> str:
    """A sidecar's text, as the Rails exporter wrote it (`JSON.pretty_generate` and a newline)."""
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def sidecar_text(stored: str, front_matter: dict, subjects: dict) -> str:
    """The sidecar that agrees with a book's exported front matter: `stored`
    (the file as it was read) while it already does, else the spec rewritten.

    Every value the page holds too is the page's — the title, subtitle, series,
    audience, art style and its prompt, palette, lettering, generator note, the
    cover's image and prompt, and each letter's word, tagline, alt, prompt,
    image and status, in the page's order — and each letter's subject is
    `subjects`' (a plate's subject is not on the page), else the stored one.
    The rest (theme, language, background, mood, the cover's subject and alt)
    stays as read. Keys keep the spec's order, and an empty value is left out,
    as the Rails spec left it out. A file that is not a spec is left as it is."""
    spec = load(stored)
    if not spec:
        return stored
    out = dict(spec)
    for key in BOOK_KEYS:
        _put(out, key, front_matter.get(key))
    audience = front_matter.get("audience")
    labels = {label: key for key, label in AUDIENCES.items()}
    if isinstance(audience, str) and (audience in labels or audience in AUDIENCES):
        out["audience"] = labels.get(audience, audience)
    cover = dict(out.get("cover") or {})
    for page_key, key in COVER_FROM.items():
        _put(cover, key, front_matter.get(page_key))
    _put(out, "cover", _ordered(cover, COVER_KEYS))
    planned = {e["letter"]: e for e in out.get("alphabet") or [] if _is_letter(e)}
    alphabet = []
    page_alphabet = front_matter.get("alphabet")
    for item in page_alphabet if isinstance(page_alphabet, list) else []:
        if not isinstance(item, dict) or not _is_letter(item):
            continue
        letter = item["letter"]
        entry = {**planned.get(letter, {}), "letter": letter}
        _put(entry, "subject", subjects.get(letter) or entry.get("subject") or item.get("subject"))
        for key in ("word", "tagline", "alt", "prompt", "image", "status"):
            _put(entry, key, item.get(key))
        alphabet.append(_ordered(entry, ENTRY_KEYS))
    _put(out, "alphabet", alphabet)
    out = _ordered(out, SPEC_KEYS)
    return stored if out == spec else dumps(out)


def _is_letter(entry: dict) -> bool:
    return isinstance(entry.get("letter"), str)


def _put(target: dict, key: str, value) -> None:
    if value in (None, "", [], {}):
        target.pop(key, None)
    else:
        target[key] = value


def _ordered(values: dict, keys) -> dict:
    return {**{key: values[key] for key in keys if key in values}, **values}


def _fragment(options: dict, key) -> str | None:
    found = options.get(key) if isinstance(key, str) else None  # Ruby looks up `id.to_s`: no other id is there
    return _squish(found["fragment"]) if found and found.get("fragment") else None


def _strip(text) -> str:
    return ("" if text is None else str(text)).strip(_RUBY_SPACE)


def _squish(text) -> str:
    return re.sub(r"\s+", " ", "" if text is None else str(text), flags=re.ASCII).strip(_RUBY_SPACE)
