"""The analyzers, the parser and the heuristic scorer say what AIEO said.

`golden/source.json` was written by running `apps/aieo/backend`'s own code —
its ContentParser, ScoringEngine (heuristic mode) and analyzers, under the same
Markdown and BeautifulSoup versions — on `fixtures/` before any of it was
ported. Every Markdown document scores here exactly as it scored there, every
analyzer returns exactly what it returned, and the evaluator's prompt is built
byte for byte. An HTML document parses into the same text, headers, tables,
lists and links; only its word and character counts differ, by design
(aieo/parser.py: AIEO counted html2text's Markdown, which is GPL). The rest are
the source's own backend tests (tests/test_scoring_engine.py,
test_analyzers_bundle.py, test_content_parser.py), ported.
"""

import json
import random
import re
import time
from pathlib import Path

import pytest

from aieo import analyzers, parser, scoring

HERE = Path(__file__).resolve().parent
GOLDEN = json.loads((HERE / "golden" / "source.json").read_text(encoding="utf-8"))
FIXTURES = HERE / "fixtures"
MARKDOWN = [name for name, doc in GOLDEN["documents"].items() if doc["format"] == "markdown"]


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", MARKDOWN)
def test_a_markdown_document_parses_and_scores_as_aieo_scored_it(name):
    recorded = GOLDEN["documents"][name]
    assert parser.parse(read(name), "markdown") == recorded["parsed"]
    result = scoring.score(read(name), "markdown")
    assert {key: result[key] for key in recorded["result"]} == recorded["result"]


def test_an_html_page_parses_into_the_same_parts_and_counts_the_words_a_reader_sees():
    recorded = GOLDEN["documents"]["page.html"]["parsed"]
    parsed = parser.parse(read("page.html"), "html")
    same = ("text", "headers", "tables", "lists", "links", "content_hash")
    assert {key: parsed[key] for key in same} == {key: recorded[key] for key in same}
    assert parsed["word_count"] == len(recorded["text"].split()) < recorded["word_count"]


@pytest.mark.parametrize("name", sorted(GOLDEN["analyzers"]))
def test_every_analyzer_returns_what_aieo_returned(name):
    text, recorded = read(name), GOLDEN["analyzers"][name]
    assert analyzers.readability(text) == recorded["readability"]
    assert analyzers.keywords(text, "backup", ["restore", "site"]) == recorded["keywords"]
    assert analyzers.keywords(text) == recorded["keywords_none"]
    assert analyzers.search_intent(text) == recorded["intent"]
    assert analyzers.length_against(text) == recorded["length"]
    assert analyzers.length_against(text, [300, 900, 600, 1200]) == recorded["length_custom"]
    assert analyzers.seo_quality(text) == recorded["seo"]
    assert analyzers.humanity(text) == recorded["humanity"]
    assert analyzers.landing_page(text) == recorded["landing"]
    assert analyzers.cro_checklist(text) == recorded["cro_checklist"]
    assert analyzers.ctas(text) == recorded["cta"]
    assert analyzers.trust_signals(text) == recorded["trust"]
    assert analyzers.above_fold(text) == recorded["above_fold"]
    assert analyzers.engagement(text) == recorded["engagement"]
    assert analyzers.competitor_gaps(text, ["pricing", "restore", "FAQ", "migration"]) == recorded["competitor_gap"]


def test_the_opportunity_rule_ranks_as_aieo_ranked():
    for case in GOLDEN["opportunity"]:
        assert analyzers.opportunity(**case["input"]) == case["output"]


def test_the_bundled_patterns_and_the_evaluators_prompt_are_aieos():
    assert list(scoring.bundled_patterns()) == GOLDEN["patterns"]
    parsed = parser.parse(read("article.md"), "markdown")
    assert scoring.evaluation_prompt(parsed, scoring.bundled_patterns()) == GOLDEN["prompt"]["evaluation"]
    assert scoring.prompt("system.md") == GOLDEN["prompt"]["system"]


# ── the source's own backend tests, ported ─────────────────────────────────


def test_score_basic_content():
    result = scoring.score("# Test Article\n\nThis is a test article.")
    for key in ("score", "grade", "gaps", "pattern_scores", "word_count", "scoring_method"):
        assert key in result
    assert 0 <= result["score"] <= 100
    assert result["grade"] in ["A+", "A", "B", "C", "D", "F"]
    assert result["scoring_method"] == "heuristic"


def test_score_with_tables_and_entities():
    tables = scoring.score("# Test Article\n\n| Feature | Value |\n|---------|-------|\n| Test    | 123   |\n")
    assert tables["pattern_scores"]["structured_data"]["score"] > 0
    entities = scoring.score(
        "# Test Article\n\nOpenAI released GPT-4 in March 2023. Anthropic's Claude was released in 2024.\n"
    )
    assert entities["pattern_scores"]["entity_density"]["detected"]


def test_gap_generation_and_the_result_shape():
    result = scoring.score("# Test\n\nSimple content without patterns.")
    assert result["gaps"] and all({"category", "severity", "description"} <= set(gap) for gap in result["gaps"])
    for key in ("scoring_method", "content_type", "overall_assessment", "anti_pattern_details"):
        assert key in result
    assert all({"evidence", "recommendation"} <= set(data) for data in result["pattern_scores"].values())


def test_the_pattern_library_weighs_125_across_ten_patterns():
    patterns = scoring.bundled_patterns()
    assert len(patterns) == 10 and sum(p["weight"] for p in patterns) == 125
    assert all(p["weight"] > 0 and p["max_score"] > 0 and p["body"] for p in patterns)
    assert "AIEO" in scoring.prompt("system.md") and "JSON" in scoring.prompt("scoring_rubric.md")


def test_the_analyzers_bundle():
    text = "# Title\n\n## Section\n\nThis is a short sentence. This is another one."
    assert 0 <= analyzers.readability(text)["score"] <= 100 and 0 <= analyzers.seo_quality(text)["score"] <= 100
    short = "Content marketing strategy guide for B2B SaaS teams."
    assert "primary" in analyzers.keywords(short, "content")
    assert analyzers.search_intent(short)["intent"] in {"informational", "navigational", "transactional", "commercial"}
    assert "optimal_target" in analyzers.length_against(short, [100, 200, 300])
    assert "humanity" in analyzers.humanity(short)
    landing = "# Landing\n\nTrusted by teams.\n\nStart trial today.\n"
    assert 0 <= analyzers.landing_page(landing)["score"] <= 100 and analyzers.cro_checklist(landing)["total"] == 4


def test_the_content_parser():
    parsed = parser.parse("# Title\n\nSome text here.", "markdown")
    assert {"text", "headers", "tables", "lists"} <= set(parsed) and parsed["headers"]
    assert parser.parse("<h1>Title</h1><p>Some text</p>", "html")["headers"]
    table = parser.parse("# Test\n\n| Col1 | Col2 |\n|------|------|\n| Val1 | Val2 |\n")
    assert table["tables"][0]["row_count"] > 0


def test_a_models_evaluation_is_clamped_weighed_and_penalised():
    patterns = scoring.bundled_patterns()
    parsed = parser.parse(read("article.md"), "markdown")
    evaluation = {
        "patterns": {p["name"]: {"score": p["max_score"] * 2, "detected": True, "evidence": ["x"]} for p in patterns},
        "anti_patterns": {"penalties": 80, "detected": ["keyword stuffing"], "evidence": ["…"]},
        "content_type": "tutorial",
    }
    result = scoring.from_evaluation(evaluation, parsed, patterns, provider="fake", model="fake-1")
    assert all(data["score"] == data["max"] for data in result["pattern_scores"].values())
    assert result["anti_pattern_penalties"] == 50 and result["score"] == 50.0 and result["grade"] == "D"
    assert result["scoring_method"] == "ai" and result["dimensions"]["aieo"] == 50.0 and result["gaps"] == []


AIEO_QUESTIONS = re.compile(r"[^.!?\n]+\?")  # what AIEO's recursive-depth check counted


def test_questions_are_counted_as_aieo_counted_them_in_linear_time():
    """AIEO's question pattern takes time with the square of a long run with no stop, question mark or newline (the
    parser joins a document's lines into one), so a long text pinned the thread scoring it — 50,000 characters took
    seconds, 200,000 minutes. The count here is the same number, at once."""
    rng = random.Random(7)
    for _ in range(5000):
        text = "".join(rng.choice("ab ?.!\nA?") for _ in range(rng.randint(0, 40)))
        found = scoring._recursive_depth({"text": text, "headers": []}, 30)
        assert found["evidence"] == [f"{len(AIEO_QUESTIONS.findall(text))} questions, 0 question headers"], text
    started = time.perf_counter()
    scoring._recursive_depth({"text": "why " * 12_500, "headers": []}, 30)
    assert time.perf_counter() - started < 1


def test_a_pattern_with_no_heuristic_is_left_to_a_model_and_never_lowers_a_heuristic_score():
    """A pattern a person adds to the library has no deterministic check: the heuristics leave it out and name it,
    so adding one never drags down every heuristic score (score/, the CI runner, the citability review)."""
    added = {"name": "brand_story", "display_name": "Brand story", "weight": 100, "max_score": 10, "body": "Tell it."}
    before = scoring.score(read("article.md"), "markdown")
    after = scoring.score(read("article.md"), "markdown", [*scoring.bundled_patterns(), added])
    assert after["score"] == before["score"] and after["model_only"] == ["brand_story"]
    assert "brand_story" not in after["pattern_scores"] and "model_only" not in before
