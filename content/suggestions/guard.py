"""The mechanical brand guard, ported from the extension
(`src/core/governance/guard.ts`) so a phrase that fails in the editor, in CI
and here fails with the same name and message.

`guard_text` is the full commentary guard — length, the 13 hard bans, the
exclamation and filler warnings, the weak hook and the fold — and keeps the
extension's two deduplications. `page_findings` is what applies to a page:
the bans (errors) and filler (warnings), without the commentary-only length
ceiling, fold or hook, which make no sense for an article (the extension's
guard README says the same). Extra patterns come from the active
`cms.BrandRules` snippets; a malformed one is skipped, never fatal, like a
broken `governance.bannedPatternsFile`.

An accepted suggestion whose text has an error-level finding is refused: the
guard is a validator in the accept flow (M10), not a report. A suggestion that
replaces text is judged on what it adds (`before`): a banned phrase the text
already had is its author's, so it is refused only when the new text uses that
phrase more often than the old (a novel's character may say "unlocking value";
an agent continuing the chapter does not get to say it again).
"""

import re

FOLD = 140
MAX_LEN = 3000

BANNED_PATTERNS = [
    ("cutting-edge", re.compile(r"\bcutting[- ]edge\b", re.I)),
    ("next-generation", re.compile(r"\bnext[- ]generation\b", re.I)),
    ("disruptive", re.compile(r"\bdisruptive\b", re.I)),
    ("revolutionary", re.compile(r"\brevolutionar(?:y|ies)\b", re.I)),
    (
        "in today's ... world/age/era",
        re.compile(r"\bin\s+today[’']s\s+[^.\n]{0,40}?\b(world|age|era|landscape|climate|environment)\b", re.I),
    ),
    ("leverage synergies", re.compile(r"\bleverag\w*\s+synerg\w*", re.I)),
    ("unlock value", re.compile(r"\bunlock(?:ing|s)?\s+value\b", re.I)),
    ("best-of-breed", re.compile(r"\bbest[- ]of[- ]breed\b", re.I)),
    ("world-class", re.compile(r"\bworld[- ]class\b", re.I)),
    ("solutioning", re.compile(r"\bsolutioning\b", re.I)),
    ("ideate", re.compile(r"\bideat(?:e|es|ed|ing|ion)\b", re.I)),
    ("circle back", re.compile(r"\bcircl(?:e|ing)\s+back\b", re.I)),
    ("low-hanging fruit", re.compile(r"\blow[- ]hanging\s+fruit\b", re.I)),
]

FILLER = [
    (re.compile(r"\bgame[- ]chang(?:er|ing)\b", re.I), "game-changer"),
    (re.compile(r"\bcutting[- ]edge\b", re.I), "cutting-edge"),
    (re.compile(r"\bnext[- ]generation\b", re.I), "next-generation"),
    (re.compile(r"\brevolutionar(?:y|ies)\b", re.I), "revolutionary"),
    (re.compile(r"\bexcited to announce\b", re.I), "excited to announce"),
    (re.compile(r"\bthrilled to\b", re.I), "thrilled to"),
    (re.compile(r"\bhumbled\b", re.I), "humbled"),
    (re.compile(r"\bsynerg\w*", re.I), "synergy"),
    (re.compile(r"!{1,}"), "exclamation mark"),
]


def extra_patterns() -> list[tuple[str, re.Pattern]]:
    from cms.models import BrandRules

    patterns = []
    for rules in BrandRules.objects.filter(is_active=True):
        for entry in rules.banned_patterns or []:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("name"), str)
                or not isinstance(entry.get("pattern"), str)
            ):
                continue
            flags = re.I if "i" in str(entry.get("flags", "i")) else 0
            try:
                patterns.append((entry["name"], re.compile(entry["pattern"], flags)))
            except re.error:
                continue  # a broken addition never bricks the guard; the built-in bans still run
    return patterns


def _bans(text: str, extra, before: str | None = None) -> tuple[list[dict], set[str]]:
    findings, errored = [], set()
    for name, pattern in BANNED_PATTERNS + list(extra):
        match = pattern.search(text)
        if match and (before is None or len(pattern.findall(text)) > len(pattern.findall(before))):
            findings.append({"level": "error", "message": f'banned phrase "{match.group(0)}" ({name})'})
            errored.add(name)
    return findings, errored


def _filler(text: str, errored: set[str]) -> list[dict]:
    out = []
    for pattern, name in FILLER:
        if name == "exclamation mark" or name in errored:
            continue
        if pattern.search(text):
            out.append({"level": "warning", "message": f"reads as filler: {name}"})
    return out


def guard_text(text: str, extra=()) -> list[dict]:
    """The commentary guard, rule for rule and in the same order as guard.ts."""
    findings = []
    if len(text) > MAX_LEN:
        findings.append({"level": "error", "message": f"commentary is {len(text)} chars (max {MAX_LEN})"})
    bans, errored = _bans(text, extra)
    findings.extend(bans)
    if "!" in text:
        findings.append({"level": "warning", "message": "exclamation mark in commentary (house style: none)"})
    findings.extend(_filler(text, errored))
    first = text[:FOLD]
    if "\n" in first and len(first.split("\n")[0]) < 40:
        findings.append({"level": "warning", "message": "weak hook: the first line ends before it says anything"})
    findings.append({"level": "info", "message": f'fold at {FOLD} chars: "{first}"'})
    return findings


def page_findings(text: str, extra=None, before: str | None = None) -> list[dict]:
    """The bans and the filler; given `before` (the text this one replaces), only a ban it adds."""
    extra = extra_patterns() if extra is None else extra
    bans, errored = _bans(text or "", extra, before)
    return bans + _filler(text or "", errored)


# Markup that runs code or loads a frame. Raw HTML stays allowed in a
# Markdown block (it is lossless on purpose), but an *agent* never gets to
# propose active content: page text is untrusted input to a model, and a
# prompt-injected script would otherwise reach a published page through one
# careless accept.
ACTIVE_MARKUP = re.compile(r"<\s*(script|iframe|object|embed|style|form)\b|javascript\s*:|\son[a-z]+\s*=", re.I)


def markup_findings(text: str) -> list[dict]:
    match = ACTIVE_MARKUP.search(text or "")
    if not match:
        return []
    return [{"level": "error", "message": f'active markup "{match.group(0).strip()}" is not accepted from an agent'}]


def has_errors(findings) -> bool:
    return any(f["level"] == "error" for f in findings)


def text_of(value) -> str:
    """Every string inside a block value or a meta value, joined."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(text_of(v) for v in value.values())
    if isinstance(value, list):
        return "\n".join(text_of(v) for v in value)
    return ""
