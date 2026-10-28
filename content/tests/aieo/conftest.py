"""Fixtures for AIEO's tests: the AI layer's people, scripted provider, worker and API client
(tests/ai/conftest.py); the research library's table of names and recorded HTTP at the address the guard pins the
connection to (tests/research/conftest.py), so every page, robots.txt, sitemap and feed an audit or a crawl reads is
answered by respx and nothing reaches a network; a site with an article to audit; and a model's evaluation that
matches the rubric's schema. Nothing reaches a network or a model."""

import json

import pytest
from wagtail.models import Page, Site

from aieo import scoring
from cms.models import SiteRootPage
from tests.ai.conftest import alice, api, bob, fake, staff, worker  # noqa: F401 — shared fixtures
from tests.conftest import make_article
from tests.research.conftest import PUBLIC, at, table_dns, web  # noqa: F401 — shared fixtures

ARTICLE = [
    {"type": "markdown", "value": "Backups are copies of a site. A backup is defined as a restorable copy."},
    {"type": "heading", "value": {"level": "2", "text": "How often?"}},
    {"type": "markdown", "value": "Daily backups suit a busy site. Weekly backups suit a brochure site."},
    {"type": "heading", "value": {"level": "2", "text": "Where to keep them"}},
    {"type": "markdown", "value": "Keep one copy off the server."},
]


def evaluation(score=0.5, penalties=5, **extra) -> dict:
    """A model's evaluation that matches the rubric's schema: every bundled pattern at `score` of its maximum."""
    return {
        "patterns": {
            p["name"]: {
                "score": p["max_score"] * score,
                "max": p["max_score"],
                "detected": score > 0,
                "evidence": [f"{p['display_name']} seen"],
                "recommendation": f"More {p['display_name'].lower()}.",
            }
            for p in scoring.bundled_patterns()
        },
        "anti_patterns": {"penalties": penalties, "detected": [], "evidence": []},
        "content_type": "article",
        "overall_assessment": "Clear, but thin on sources.",
        "executive_summary": "The page explains backups plainly.",
        "priority_actions": [
            {"title": "Add sources", "impact": "high", "effort": "low", "description": "Cite the survey."}
        ],
        "sample_improvements": [
            {
                "section": "Intro",
                "current": "Backups are copies.",
                "improved": "A backup is …",
                "patterns_addressed": [],
            }
        ],
        "visual_analysis": {
            "layout_quality": "",
            "visual_hierarchy": "",
            "readability": "",
            "trust_signals": "",
            "mobile_readiness": "",
            "scannability": "",
            "design_score": 0,
            "design_recommendations": [],
        },
        **extra,
    }


def answer(data) -> dict:
    """A scripted completion whose text is `data` as JSON."""
    return {"text": json.dumps(data), "tokens_in": 120, "tokens_out": 80}


@pytest.fixture
def site(db):
    """The default site, served at backups.example.com, with a root of its own (alice edits every page)."""
    root = SiteRootPage(title="Backups site", slug="backups-site", site_key="backups-site")
    Page.get_first_root_node().add_child(instance=root)
    root.save_revision().publish()
    Site.objects.filter(is_default_site=True).update(root_page=root, hostname="backups.example.com")
    return Site.objects.get(is_default_site=True)


@pytest.fixture
def page(site):
    return make_article(site.root_page.specific, "Nightly backups", body=ARTICLE)
