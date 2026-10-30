"""AIEO's analyzers: the deterministic checks behind four of the five dimensions
(seo, readability, humanity, cro) and the extra signals an audit carries —
search intent, keyword use, length against competitors, the CRO checklist,
engagement and competitor gaps — and the opportunity rule priorities rank by.

Ported from `apps/aieo/backend/app/analyzers/` as they were, quirks included:
`tests/aieo/test_analyzers.py` holds every one of them to what the source
computed on the fixtures (`tests/aieo/golden/source.json`), so a score here is
the score AIEO gave. They read plain text and touch nothing else.
"""

import re

WORD = re.compile(r"\b[\w'-]+\b")
SENTENCE = re.compile(r"[^.!?]+[.!?]?")
PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+\w+ed\b", re.IGNORECASE)


# ── text helpers ───────────────────────────────────────────────────────────


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def word_count(text: str) -> int:
    return len(words(text))


def sentence_count(text: str) -> int:
    return max(1, len([s for s in SENTENCE.findall(text) if s.strip()]))


def avg_sentence_length(text: str) -> float:
    wc, sc = word_count(text), sentence_count(text)
    return (wc / sc) if sc else 0.0


def top_terms(text: str, min_len: int = 4, limit: int = 20) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for token in words(text):
        if len(token) >= min_len:
            counts[token] = counts.get(token, 0) + 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]


# ── readability, keywords, intent, length, seo, humanity ───────────────────


def readability(text: str) -> dict:
    """A lightweight Flesch approximation (higher is easier) from sentence length, with passive voice."""
    wc, sc = max(1, word_count(text)), max(1, sentence_count(text))
    asl = avg_sentence_length(text)
    passive = len(PASSIVE.findall(text))
    ease = round(max(0, min(100, 110 - (asl * 2.2))), 1)
    return {
        "score": round(max(0, min(100, ease)), 1),
        "flesch_reading_ease": ease,
        "flesch_kincaid_grade": round(max(1, min(18, 16 - (ease / 8))), 1),
        "average_sentence_length": round(asl, 1),
        "sentence_count": sc,
        "word_count": wc,
        "passive_voice_ratio": round((passive / sc) * 100, 1),
    }


def keywords(text: str, primary_keyword: str | None = None, secondary_keywords: list[str] | None = None) -> dict:
    """Keyword density and placement, the terms the text leans on, and the stuffing risk."""
    tokens, wc = words(text), max(1, word_count(text))

    def density(keyword: str) -> dict:
        if not keyword:
            return {"keyword": "", "count": 0, "density": 0.0}
        kw = keyword.lower()
        count = sum(1 for t in tokens if t == kw or kw in t)
        return {"keyword": keyword, "count": count, "density": round((count / wc) * 100, 2)}

    top = top_terms(text, min_len=4, limit=15)
    return {
        "word_count": wc,
        "primary": density(primary_keyword or ""),
        "secondary": [density(k) for k in secondary_keywords or []],
        "lsi_keywords": [term for term, _ in top[:10]],
        "topic_clusters": [[term for term, _ in top[:5]], [term for term, _ in top[5:10]]],
        "keyword_stuffing_risk": any((count / wc) > 0.05 for _, count in top),
        "distribution": {
            "intro": text[: max(1, len(text) // 5)],
            "body": text[max(1, len(text) // 5) : max(1, len(text) * 4 // 5)],
            "outro": text[max(1, len(text) * 4 // 5) :],
        },
    }


INTENTS = {
    "informational": ["what", "how", "guide", "learn", "tips", "best practices"],
    "navigational": ["login", "official", "website", "pricing page", "docs"],
    "transactional": ["buy", "purchase", "demo", "trial", "subscribe", "book"],
    "commercial": ["vs", "compare", "review", "alternatives", "top"],
}


def search_intent(query_or_content: str) -> dict:
    text = query_or_content.lower()
    scores = {intent: sum(1 for term in terms if term in text) for intent, terms in INTENTS.items()}
    intent = max(scores, key=scores.get)
    total = sum(scores.values()) or 1
    return {"intent": intent, "confidence": round((scores[intent] / total) * 100, 1), "signals": scores}


def length_against(text: str, competitor_word_counts: list[int] | None = None) -> dict:
    """The text's length against competitors' (AIEO's assumed spread when none are given)."""
    ordered = sorted(competitor_word_counts or [1200, 1500, 1800, 2200, 2600])
    wc = word_count(text)
    median = ordered[len(ordered) // 2]
    p75 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.75))]
    return {
        "word_count": wc,
        "competitor_median": median,
        "competitor_p75": p75,
        "optimal_target": p75,
        "gap_to_target": median - wc,
        "recommendation": "Expand depth with examples and FAQs." if wc < median else "Length is competitive.",
    }


def seo_quality(text: str) -> dict:
    wc = word_count(text)
    has_h1, has_h2 = "# " in text, "## " in text
    has_links = "http://" in text or "https://" in text
    has_meta = "meta title" in text.lower() or "meta description" in text.lower()
    has_list = "- " in text or "1. " in text
    score = 20 if wc >= 1200 else max(0, int((wc / 1200) * 20))
    score += (15 if has_h1 else 0) + (15 if has_h2 else 0) + (15 if has_links else 0) + (15 if has_meta else 0)
    score = min(100, score + (20 if has_list else 0))
    return {
        "score": score,
        "category_breakdown": {
            "content": min(20, int((wc / 1200) * 20)),
            "structure": 30 if (has_h1 and has_h2) else (15 if has_h1 or has_h2 else 0),
            "links": 15 if has_links else 0,
            "meta": 15 if has_meta else 0,
            "readability_structure": 20 if has_list else 0,
        },
        "critical_issues": [] if score >= 70 else ["Missing key SEO elements"],
        "warnings": [] if score >= 50 else ["Content likely under-optimized for search"],
    }


def humanity(text: str) -> dict:
    """The humanity and quality score: specificity (distinct terms) and sentence length, with structure and links."""
    wc = max(1, word_count(text))
    avg_len = avg_sentence_length(text)
    unique_terms = len({term for term, _ in top_terms(text, min_len=4, limit=100)})
    specificity = min(100, int((unique_terms / 80) * 100))
    readable = max(0, min(100, int(100 - (avg_len - 18) * 2)))
    structure = 100 if "## " in text else 55
    seo = 100 if "http" in text else 50
    human = min(100, int((specificity * 0.5) + (readable * 0.5)))
    return {
        "score": round((human + specificity + structure + seo + readable) / 5, 1),
        "humanity": human,
        "specificity": specificity,
        "structure": structure,
        "seo": seo,
        "readability": readable,
        "word_count": wc,
    }


# ── conversion ─────────────────────────────────────────────────────────────


def above_fold(text: str) -> dict:
    head = text[:1500].lower()
    value_prop = any(term in head for term in ["why", "benefit", "helps", "for teams"])
    cta = any(term in head for term in ["start", "book", "try", "sign up", "get started"])
    trust = any(term in head for term in ["trusted", "customers", "reviews", "testimonials"])
    score = (35 if value_prop else 0) + (35 if cta else 0) + (30 if trust else 0)
    return {"score": score, "value_prop": value_prop, "cta": cta, "trust": trust}


def ctas(text: str) -> dict:
    found = re.findall(r"\b(start|book|buy|subscribe|contact|try)\b", text.lower())
    return {"score": min(100, len(found) * 15), "cta_count": len(found), "cta_variants": sorted(set(found))}


def trust_signals(text: str) -> dict:
    lower = text.lower()
    testimonials = len(re.findall(r"\btestimonial|review|case study\b", lower))
    social_proof = len(re.findall(r"\bcustomers|companies|teams\b", lower))
    risk_reversal = len(re.findall(r"\bguarantee|cancel anytime|refund\b", lower))
    return {
        "score": min(100, testimonials * 20 + social_proof * 10 + risk_reversal * 20),
        "testimonials": testimonials,
        "social_proof": social_proof,
        "risk_reversal": risk_reversal,
    }


def landing_page(text: str) -> dict:
    """The composite CRO score: above the fold 40%, calls to action 35%, trust 25%."""
    above, cta, trust = above_fold(text), ctas(text), trust_signals(text)
    total = round((above["score"] * 0.4) + (cta["score"] * 0.35) + (trust["score"] * 0.25), 1)
    return {"score": total, "above_fold": above, "cta": cta, "trust": trust}


def cro_checklist(text: str) -> dict:
    lower = text.lower()
    checks = {
        "headline": "# " in text,
        "cta_present": any(term in lower for term in ["start", "book", "buy", "try"]),
        "social_proof": any(term in lower for term in ["testimonial", "review", "trusted"]),
        "objection_handling": any(term in lower for term in ["faq", "questions", "pricing", "guarantee"]),
    }
    passed = sum(1 for ok in checks.values() if ok)
    return {"passed": passed, "total": len(checks), "checks": checks, "score": round((passed / len(checks)) * 100, 1)}


# ── the two the source exported and never wired ────────────────────────────


def engagement(text: str) -> dict:
    questions = len(re.findall(r"\?", text))
    calls = len(re.findall(r"\b(try|start|book|download|learn more|contact)\b", text.lower()))
    examples = len(re.findall(r"\b(example|for instance|case study)\b", text.lower()))
    return {
        "score": min(100, questions * 8 + calls * 12 + examples * 10),
        "questions": questions,
        "ctas": calls,
        "examples": examples,
    }


def competitor_gaps(text: str, competitor_topics: list[str] | None = None) -> dict:
    """The competitors' topics the text never mentions."""
    lower = text.lower()
    missing = [topic for topic in competitor_topics or [] if topic.lower() not in lower]
    return {
        "missing_topics": missing,
        "gap_count": len(missing),
        "recommendation": "Add sections for missing high-intent topics." if missing else "Coverage looks complete.",
    }


# ── priorities ─────────────────────────────────────────────────────────────


def opportunity(
    *,
    position: float = 50.0,
    impressions: int = 0,
    ctr: float = 0.0,
    trend_delta: float = 0.0,
    business_priority: float = 0.5,
) -> dict:
    """OpportunityScorer's rule: position 30%, impressions 25%, CTR gap 20%, trend 15%, business priority 10%."""
    position_score = max(0, min(100, (100 - min(position, 100))))
    impressions_score = min(100, impressions / 100)
    ctr_gap_score = max(0, min(100, 100 - (ctr * 100)))
    trend_score = max(0, min(100, 50 + trend_delta))
    business_score = max(0, min(100, business_priority * 100))
    overall = round(
        (position_score * 0.3)
        + (impressions_score * 0.25)
        + (ctr_gap_score * 0.2)
        + (trend_score * 0.15)
        + (business_score * 0.1),
        1,
    )
    return {
        "score": overall,
        "components": {
            "position": position_score,
            "impressions": impressions_score,
            "ctr_gap": ctr_gap_score,
            "trend": trend_score,
            "business_priority": business_score,
        },
    }
