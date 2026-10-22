"""The drafter's "abc" profile: an ABC board book, letter by letter.

Ported from the Rails ABC generator (`rails/lib/zer0_cms/abc`): a theme with a
bundled lexicon (`agents/data/abc_lexicons/<slug>.yml`, a vendored copy of the
Ruby one — workspace.yml keeps them identical) generates offline and
deterministically; any other theme falls back to the model, with the same
tools. The book is a `BookPage` with `profile="abc"`; each letter becomes one
`letter` block. At policy `suggest` (every agent's start) each missing letter
is a Suggestion, and accepting the run's suggestions together writes the
whole alphabet as one revision; at `draft` the drafter writes that revision
itself. Letters the page already has are left alone.
"""

import re
from pathlib import Path

import yaml

from cms.models import POLICY_DRAFT, POLICY_ORDER

from ..registry import registry

LEXICONS = Path(__file__).resolve().parent.parent / "data" / "abc_lexicons"
LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower().strip()).strip("_")


def lexicon(theme: str) -> dict | None:
    path = LEXICONS / f"{slugify(theme)}.yml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = [letter for letter in LETTERS if letter not in data.get("letters", {})]
    if missing:
        raise ValueError(f"lexicon {path.name} is missing letters: {', '.join(missing)}")
    return data


def available() -> list[str]:
    return sorted(p.stem for p in LEXICONS.glob("*.yml"))


def draft(run, ctx):
    page = run.target
    theme = (run.input or {}).get("theme") or (page.front_matter or {}).get("theme") or page.title
    data = lexicon(theme)
    if data is None:
        from ..runner import model_loop

        return {**model_loop(run, ctx, ctx.agent), "theme": theme, "provider": "model"}

    current = registry.call("content.get_page", {"page_id": page.pk}, ctx)
    have = {b["value"].get("letter") for b in current.get("body", []) if b["type"] == "letter"}
    ops = []
    for letter in LETTERS:
        if letter in have:
            continue
        entry = data["letters"][letter]
        block = {
            "type": "letter",
            "value": {
                "letter": letter,
                "word": entry["word"],
                "tagline": entry["tagline"],
                "subject": entry.get("subject", ""),
                "alt": entry.get("alt", ""),
                "image": None,
            },
        }
        ops.append({"op": "insert", "block": block})

    policy = page.effective_policy(ctx.policy)
    rationale = f"ABC book from the bundled {data['theme']!r} lexicon"
    if not ops:
        return {"theme": data["theme"], "provider": "lexicon", "letters_added": 0}
    if POLICY_ORDER.index(policy) >= POLICY_ORDER.index(POLICY_DRAFT) and "content.draft_revision" in ctx.agent.tools:
        result = registry.call("content.draft_revision", {"page_id": page.pk, "ops": ops, "rationale": rationale}, ctx)
        return {
            "theme": data["theme"],
            "provider": "lexicon",
            "letters_added": len(ops),
            "revision_id": result["revision_id"],
        }
    suggested = []
    for op in ops:
        out = registry.call(
            "content.propose_edit",
            {"page_id": page.pk, "op": "insert", "block": op["block"], "rationale": rationale},
            ctx,
        )
        suggested.append(out["suggestion_id"])
    return {"theme": data["theme"], "provider": "lexicon", "letters_added": len(ops), "suggestions": suggested}
