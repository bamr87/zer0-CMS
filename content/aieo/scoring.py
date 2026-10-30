"""The five-dimension score of a document: AIEO's scoring engine, ported.

The `aieo` dimension is the citability score — the ten patterns of the pattern
library, each scored up to its maximum and weighted, less the anti-pattern
penalties — and the other four (`seo`, `readability`, `humanity`, `cro`) come
from the analyzers (aieo/analyzers.py). Two ways to score the patterns, as in
`apps/aieo/backend/app/services/scoring_engine.py`:

* `heuristic(parsed, patterns)` — the deterministic checks, the fallback, and
  what the CI runner and `manage.py aieo audit` use without a model;
* `from_evaluation(evaluation, parsed, patterns)` — a model's evaluation,
  asked for with `evaluation_prompt` (the system prompt, the scoring rubric and
  the pattern definitions, byte for byte as AIEO built it) through the AI
  content layer (aieo/handlers.py), its JSON held to `evaluation_schema`.

Both return the same shape: score, grade, per-pattern evidence and
recommendations, gaps, anti-pattern penalties, the dimensions and the analyses
behind them. Patterns are plain dicts here (`name`, `display_name`, `weight`,
`max_score`, `body`) — the library's rows (`aieo.models.Pattern.as_spec`) or the
bundled files (`bundled_patterns`), so nothing in this module needs a database.
"""

import copy
import re
from functools import cache
from pathlib import Path

import yaml

from . import analyzers, parser

DATA = Path(__file__).resolve().parent / "data"
PROMPTS = DATA / "prompts"
FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)
GRADES = ((90, "A+"), (80, "A"), (70, "B"), (60, "C"), (50, "D"))
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
ENTITY_STOPS = set(
    "THE AND FOR BUT NOT YOU ALL CAN HER WAS ONE OUR OUT ARE HAS HIS HOW ITS FROM WITH THIS THAT HAVE WILL WHAT WHEN".split()
)


# ── the prompt files ───────────────────────────────────────────────────────


def front_matter(text: str) -> tuple[dict, str]:
    """A prompt file's front matter and body (the whole text when it has none)."""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    return yaml.safe_load(match.group(1)) or {}, match.group(2)


def read_patterns(directory: Path) -> list[dict]:
    """The pattern files of a prompts directory (`patterns/*.md`), in name order."""
    found = []
    for path in sorted((directory / "patterns").glob("*.md")):
        meta, body = front_matter(path.read_text(encoding="utf-8"))
        found.append(
            {
                "name": str(meta.get("name", path.stem)),
                "display_name": str(meta.get("display_name", path.stem.replace("_", " ").title())),
                "weight": int(meta.get("weight", 10)),
                "max_score": int(meta.get("max_score", 10)),
                "body": body.strip(),
            }
        )
    return found


@cache
def bundled_patterns() -> tuple:
    return tuple(read_patterns(PROMPTS))


@cache
def prompt(name: str) -> str:
    """A bundled prompt file (`system.md`, `scoring_rubric.md`, `optimize_expand.md`) as written."""
    return (PROMPTS / name).read_text(encoding="utf-8")


# ── scoring ────────────────────────────────────────────────────────────────


def score(content: str, format: str = "markdown", patterns=None, *, keywords=(), competitor_topics=()) -> dict:
    """Parse and score `content` with the heuristics (the bundled patterns unless given)."""
    return heuristic(parser.parse(content, format), patterns, keywords=keywords, competitor_topics=competitor_topics)


def grade(value: float) -> str:
    return next((letter for floor, letter in GRADES if value >= floor), "F")


def weighted(pattern_scores: dict, weights: dict) -> float:
    total = sum(weights.values())
    earned = sum(
        (data["score"] / data["max"]) * weights.get(name, 0) for name, data in pattern_scores.items() if data["max"] > 0
    )
    return round((earned / total) * 100, 1) if total > 0 else 0


def gaps(pattern_scores: dict, weights: dict) -> list[dict]:
    """The patterns under 60% of their maximum, the heaviest and lowest first."""
    found = []
    for name, data in pattern_scores.items():
        if data["max"] == 0:
            continue
        ratio, weight = data["score"] / data["max"], weights.get(name, 0)
        if ratio >= 0.6:
            continue
        if ratio < 0.3:
            severity = "high" if weight >= 15 else "medium"
        else:
            severity = "medium" if weight >= 15 else "low"
        found.append(
            {
                "id": f"gap_{name}",
                "category": name,
                "severity": severity,
                "description": data.get("recommendation") or f"Improve {name.replace('_', ' ')} to increase score.",
                "pattern_score": data["score"],
                "pattern_max": data["max"],
                "weight": weight,
            }
        )
    found.sort(key=lambda g: (SEVERITY_ORDER.get(g["severity"], 3), -g["weight"]))
    return found


def dimensions(parsed: dict, *, keywords=(), competitor_topics=()) -> dict:
    """The analyses behind the seo, readability, humanity and cro dimensions, and the extra signals."""
    text = parsed.get("text", "")
    primary, *secondary = list(keywords) or [None]
    seo = analyzers.seo_quality(text)
    readable = analyzers.readability(text)
    human = analyzers.humanity(text)
    cro = {"landing_page": analyzers.landing_page(text), "checklist": analyzers.cro_checklist(text)}
    return {
        "seo_quality": seo,
        "readability": readable,
        "search_intent": analyzers.search_intent(text),
        "keyword_analysis": analyzers.keywords(text, primary, secondary),
        "serp_comparison": analyzers.length_against(text),
        "humanity": human,
        "cro": cro,
        "engagement": analyzers.engagement(text),
        "competitor_gaps": analyzers.competitor_gaps(text, list(competitor_topics)),
        "dimensions": {
            "aieo": None,
            "seo": seo.get("score", 0),
            "readability": readable.get("score", 0),
            "humanity": human.get("humanity", 0),
            "cro": cro["landing_page"].get("score", 0),
        },
    }


def _result(pattern_scores, penalty, parsed, patterns, *, keywords, competitor_topics, **rest) -> dict:
    weights = {p["name"]: p["weight"] for p in patterns}
    final = max(0, weighted(pattern_scores, weights) - penalty)
    enriched = dimensions(parsed, keywords=keywords, competitor_topics=competitor_topics)
    enriched["dimensions"]["aieo"] = final
    return {
        "score": final,
        "grade": grade(final),
        "pattern_scores": pattern_scores,
        "gaps": gaps(pattern_scores, weights),
        "anti_pattern_penalties": penalty,
        "word_count": parsed["word_count"],
        **rest,
        **enriched,
    }


def heuristic(parsed: dict, patterns=None, *, keywords=(), competitor_topics=()) -> dict:
    """The deterministic score: each pattern's check, then the anti-pattern penalties. A pattern with no check — one a
    person added to the library — is a model's to score: left out here and named (`model_only`), where AIEO scored it
    0 and weighed it in, so adding one lowered every heuristic score."""
    patterns = list(patterns if patterns is not None else bundled_patterns())
    checked = [p for p in patterns if p["name"] in HEURISTICS]
    pattern_scores = {p["name"]: HEURISTICS[p["name"]](parsed, p["max_score"]) for p in checked}
    unchecked = [p["name"] for p in patterns if p["name"] not in HEURISTICS]
    return _result(
        pattern_scores,
        anti_patterns(parsed),
        parsed,
        checked,
        **({"model_only": unchecked} if unchecked else {}),
        keywords=keywords,
        competitor_topics=competitor_topics,
        anti_pattern_details={"detected": [], "evidence": []},
        content_type="unknown",
        overall_assessment="Scored with heuristic fallback. Configure an AI API key for contextual analysis.",
        scoring_method="heuristic",
        model=None,
        provider=None,
    )


def from_evaluation(
    evaluation: dict, parsed: dict, patterns, *, provider="", model="", keywords=(), competitor_topics=()
):
    """A model's evaluation as a score: each pattern's score clamped to its maximum, the penalties capped at 50."""
    patterns = list(patterns)
    given = evaluation.get("patterns", {})
    pattern_scores = {}
    for p in patterns:
        found = given.get(p["name"], {})
        pattern_scores[p["name"]] = {
            "score": max(0, min(p["max_score"], found.get("score", 0))),
            "max": p["max_score"],
            "detected": found.get("detected", False),
            "evidence": found.get("evidence", []),
            "recommendation": found.get("recommendation", ""),
        }
    anti = evaluation.get("anti_patterns", {})
    return _result(
        pattern_scores,
        min(50, anti.get("penalties", 0)),
        parsed,
        patterns,
        keywords=keywords,
        competitor_topics=competitor_topics,
        anti_pattern_details={"detected": anti.get("detected", []), "evidence": anti.get("evidence", [])},
        content_type=evaluation.get("content_type", "unknown"),
        overall_assessment=evaluation.get("overall_assessment", ""),
        executive_summary=evaluation.get("executive_summary", ""),
        priority_actions=evaluation.get("priority_actions", []),
        sample_improvements=evaluation.get("sample_improvements", []),
        visual_analysis=evaluation.get("visual_analysis", {}),
        scoring_method="ai",
        model=model,
        provider=provider,
    )


# ── the evaluator's prompt and the shape of its answer ─────────────────────


def evaluation_prompt(parsed: dict, patterns, rubric: str | None = None) -> str:
    """The request a model evaluates: the content's summary, the rubric and the pattern definitions — AIEO's."""
    rubric = prompt("scoring_rubric.md") if rubric is None else rubric
    definitions = "\n\n---\n\n".join(
        f"### {p['display_name']} (name: `{p['name']}`, weight: {p['weight']}, max: {p['max_score']})\n\n{p['body']}"
        for p in patterns
    )
    return f"""## Content to Evaluate

{summary(parsed)}

## Scoring Rubric

{rubric}

## Pattern Definitions

{definitions}

## Instructions

Evaluate the content above against EACH pattern listed. Return your analysis as the JSON structure defined in the Scoring Rubric. Every pattern must appear in your response — score 0 if not applicable to this content type.

Evaluate contextually: consider what type of content this is and what patterns are appropriate for it. A personal blog post is scored differently from technical documentation."""


def summary(parsed: dict) -> str:
    sections = [f"**Word count:** {parsed.get('word_count', 0)}", f"**Character count:** {parsed.get('char_count', 0)}"]
    found = parsed.get("headers", [])
    if found:
        listed = "\n".join(f"  - {'#' * h['level']} {h['text']}" for h in found[:30])
        sections.append(f"**Headers ({len(found)}):**\n{listed}")
    else:
        sections.append("**Headers:** None")
    found = parsed.get("tables", [])
    if found:
        lines = []
        for i, t in enumerate(found[:10]):
            lines.append(f"  - Table {i + 1}: {t.get('row_count', 0)} rows × {t.get('column_count', 0)} columns")
            if t.get("rows"):
                lines.append(f"    Headers: {' | '.join(str(c) for c in t['rows'][0][:5])}")
        sections.append(f"**Tables ({len(found)}):**\n" + "\n".join(lines))
    else:
        sections.append("**Tables:** None")
    found = parsed.get("lists", [])
    if found:
        listed = "\n".join(f"  - {lst['type']} list: {lst.get('item_count', 0)} items" for lst in found[:10])
        sections.append(f"**Lists ({len(found)}):**\n{listed}")
    else:
        sections.append("**Lists:** None")
    every = parsed.get("links", [])
    outside = [link for link in every if link.get("url", "").startswith(("http://", "https://"))]
    sections.append(f"**Links:** {len(every)} total, {len(outside)} external")
    text = parsed.get("text", "")
    if len(text) > 12000:
        sections.append(f"**Content text (truncated to 12000 chars):**\n\n{text[:12000]}...")
    else:
        sections.append(f"**Content text:**\n\n{text}")
    return "\n\n".join(sections)


@cache
def bundled_evaluation() -> dict:
    """The bundled `aieo-evaluation` schema (data/bundled.yaml)."""
    spec = yaml.safe_load((DATA / "bundled.yaml").read_text(encoding="utf-8"))
    return next(item["schema"] for item in spec["schemas"] if item["key"] == "aieo-evaluation")


def evaluation_schema(base: dict, patterns) -> dict:
    """The evaluator's schema — the bundled one when a person left it without one that answers per pattern — with
    one required property per pattern of the library as it is now, so a pattern added or switched off changes what
    the model must answer."""
    answers = (base or {}).get("properties", {}).get("patterns", {}).get("properties")
    schema = copy.deepcopy(base if isinstance(answers, dict) and answers else bundled_evaluation())
    one = next(iter(schema["properties"]["patterns"]["properties"].values()))  # every pattern answers alike
    schema["properties"]["patterns"] = {
        "type": "object",
        "properties": {p["name"]: one for p in patterns},
        "required": [p["name"] for p in patterns],
        "additionalProperties": False,
    }
    return schema


# ── the heuristic checks, one per bundled pattern ──────────────────────────


def _pattern(score, max_score, detected, evidence, recommendation) -> dict:
    return {
        "score": round(score, 1),
        "max": max_score,
        "detected": detected,
        "evidence": [evidence],
        "recommendation": recommendation,
    }


def _structured_data(parsed, max_score):
    wc = parsed["word_count"] or 1
    t, li, h = len(parsed["tables"]), len(parsed["lists"]), len(parsed["headers"])
    density = ((t + li + h) / wc) * 500
    return _pattern(
        min(max_score, (density / 2) * max_score),
        max_score,
        density >= 1,
        f"{t} tables, {li} lists, {h} headers",
        "Add tables or lists to organize your content.",
    )


def _entity_density(parsed, max_score):
    text, wc = parsed["text"], parsed["word_count"] or 1
    caps = set(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text))
    acronyms = set(re.findall(r"\b[A-Z]{2,6}\b", text))
    entities = {e for e in (caps | acronyms) if e.upper() not in ENTITY_STOPS and len(e) > 1}
    per100 = (len(entities) / wc) * 100
    return _pattern(
        min(max_score, (per100 / 3) * max_score),
        max_score,
        per100 >= 1,
        f"{len(entities)} entities ({round(per100, 1)} per 100 words)",
        "Add specific names, organizations, and product references.",
    )


def _citation_hooks(parsed, max_score):
    text = parsed["text"].lower()
    hooks = [
        r"according to\b",
        r"research (?:from|by)\b",
        r"study (?:found|shows)\b",
        r"source:",
        r"references?:",
        r"published (?:by|in)\b",
    ]
    count = sum(len(re.findall(p, text)) for p in hooks)
    external = [link for link in parsed.get("links", []) if link.get("url", "").startswith(("http://", "https://"))]
    count += len(external)
    per1k = (count / (parsed["word_count"] or 1)) * 1000
    return _pattern(
        min(max_score, (per1k / 2) * max_score),
        max_score,
        count > 0,
        f"{count} citation signals ({len(external)} external links)",
        "Add source attributions like 'According to [source]...'",
    )


def _recursive_depth(parsed, max_score):
    # AIEO counted `re.findall(r"[^.!?\n]+\?", text)`, whose time grows with the square of a long run with no stop or
    # newline. Each of its matches ends at a "?" right after a character that is none of those, so counting those
    # question marks is the same number in linear time.
    questions = len(re.findall(r"(?<=[^.!?\n])\?", parsed["text"]))
    headed = [h for h in parsed["headers"] if "?" in h["text"]]
    return _pattern(
        min(max_score, questions * 0.5 + len(headed) * 2.5),
        max_score,
        questions > 0,
        f"{questions} questions, {len(headed)} question headers",
        "Add FAQ sections or question-style headers.",
    )


def _temporal_anchoring(parsed, max_score):
    text = parsed["text"]
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", text))
    fresh = re.findall(r"(?:as of|updated|version\s+\d)", text, re.IGNORECASE)
    count = len(years) + len(fresh)
    return _pattern(
        min(max_score, count * 2),
        max_score,
        count > 0,
        f"{len(years)} year references, {len(fresh)} freshness signals",
        "Add dates, version numbers, or 'as of [date]' markers.",
    )


def _comparison_tables(parsed, max_score):
    found = parsed["tables"]
    return _pattern(
        min(max_score, len(found) * 5),
        max_score,
        len(found) > 0,
        f"{len(found)} tables found",
        "Add comparison tables for key topics.",
    )


def _definitional_precision(parsed, max_score):
    found = re.findall(r"(?:is defined as|refers to|means that)\b", parsed["text"], re.IGNORECASE)
    return _pattern(
        min(max_score, len(found) * 3),
        max_score,
        len(found) > 0,
        f"{len(found)} definitional phrases",
        "Add explicit definitions for key terms.",
    )


def _procedural_clarity(parsed, max_score):
    steps = re.findall(r"step\s+\d+", parsed["text"], re.IGNORECASE)
    ordered = [li for li in parsed["lists"] if li["type"] == "ordered"]
    return _pattern(
        min(max_score, len(steps) * 0.5 + len(ordered) * 1),
        max_score,
        len(steps) > 0 or len(ordered) > 0,
        f"{len(steps)} step refs, {len(ordered)} ordered lists",
        "Add numbered step-by-step instructions.",
    )


def _faq_injection(parsed, max_score):
    has_faq = bool(re.search(r"(?:frequently asked questions|faq|common questions)", parsed["text"].lower()))
    headed = [h for h in parsed["headers"] if "?" in h["text"]]
    return _pattern(
        min(max_score, (8 if has_faq else 0) + min(4, len(headed))),
        max_score,
        has_faq or len(headed) > 0,
        f"FAQ section: {'yes' if has_faq else 'no'}, {len(headed)} question headers",
        "Add a FAQ section with common questions.",
    )


def _meta_context(parsed, max_score):
    text = parsed["text"].lower()
    signals = [r"this (?:is |matters? )(?:important|critical|crucial) because", r"significantly", r"essential"]
    count = sum(len(re.findall(p, text)) for p in signals)
    return _pattern(
        min(max_score, count * 2),
        max_score,
        count > 0,
        f"{count} meta-context signals",
        "Explain why your content matters to the reader.",
    )


HEURISTICS = {
    "structured_data": _structured_data,
    "entity_density": _entity_density,
    "citation_hooks": _citation_hooks,
    "recursive_depth": _recursive_depth,
    "temporal_anchoring": _temporal_anchoring,
    "comparison_tables": _comparison_tables,
    "definitional_precision": _definitional_precision,
    "procedural_clarity": _procedural_clarity,
    "faq_injection": _faq_injection,
    "meta_context": _meta_context,
}


def anti_patterns(parsed: dict) -> int:
    """The heuristic penalties: over-structuring, a word over 5% of the text, a long text with no structure."""
    penalties, text, wc = 0, parsed["text"].lower(), parsed["word_count"]
    if wc > 0 and (len(parsed["tables"]) + len(parsed["lists"]) + len(parsed["headers"])) / wc * 1000 > 10:
        penalties += 20
    tokens = text.split()
    if tokens:
        frequency: dict[str, int] = {}
        for token in tokens:
            if len(token) > 4:
                frequency[token] = frequency.get(token, 0) + 1
        if any(count > len(tokens) * 0.05 for count in frequency.values()):
            penalties += 15
    if wc > 1000 and not parsed["tables"] and not parsed["lists"]:
        penalties += 15
    return penalties
