"""AIEO's content lifecycle on the platform: a long-form draft written from a topic by the bundled Article writer
(AIEO) as a brief and applied as a draft page whose text arrives as suggestions, then the SEO, meta, internal-link and
keyword agents run on that page; a landing page drafted by the Landing page writer as the platform's LandingPage
type, its copy CRO-audited; and the stages counted from the platform's own rows. The bundled assistants and the
pattern library are made from AIEO's prompt files after every migrate — once, and a person's edit is kept."""

from agents.models import AgentRun
from ai import services as ai_services
from ai.models import Assistant, Brief
from aieo import prompts, services
from aieo.models import LandingPage, Pattern
from tests.ai.test_services import DETAIL

from .conftest import answer


def _brief(alice, site, key, prompt, page_type="cms.ArticlePage"):
    return Brief.objects.create(
        owner=alice,
        site=site,
        visibility="site",
        prompt=prompt,
        assistant=services.bundled(key, alice),
        page_type=page_type,
        parent=site.root_page,
    )


def test_a_draft_is_written_from_a_topic_and_the_four_agents_read_it(alice, fake, worker, site):
    fake.script = [{"text": "## What a backup is\n\nA copy of a site.\n\n## FAQ\n\nHow often? Daily."}, answer(DETAIL)]
    brief = _brief(alice, site, "aieo-writer", "Topic: nightly backups\n\nResearch brief: keep copies off-site.")
    worker(ai_services.generate_brief, brief, user=alice)
    brief.refresh_from_db()
    assert brief.status == Brief.READY and "long-form article" in fake.calls[0]["system"]  # AIEO's write prompt
    page, suggestions = ai_services.apply_brief(brief, user=alice)
    assert not page.live and len(suggestions) >= 3
    answers = {
        "aieo-seo-optimizer": {"score": 60, "critical_fixes": [], "quick_wins": ["Add an FAQ"], "updated_outline": []},
        "aieo-meta-creator": {
            "titles": ["A"],
            "descriptions": ["B"],
            "recommended_pair": {"title": "A", "description": "B"},
        },
        "aieo-internal-linker": {"suggestions": []},
        "aieo-keyword-mapper": {"density_report": [], "missing_keywords": ["backup"], "revisions": []},
    }
    for key, data in answers.items():
        fake.script = [answer(data)]
        run = worker(services.run_agent, alice, key, page=page)
        run.refresh_from_db()
        assert run.status == AgentRun.SUCCEEDED and run.output["json"] == data, run.error
    assert all(f"## Content\n\n# {page.title}" in call["messages"][0]["content"] for call in fake.calls[-4:])


def test_a_landing_page_is_drafted_as_its_own_type_and_its_copy_cro_audited(alice, fake, worker, site):
    copy = "# Bookkeeping for founders\n\nStart your free trial today. Trusted by 2,000 customers.\n\n## Why\n\nIt helps teams close the books."
    fake.script = [{"text": copy}, answer(DETAIL)]
    brief = _brief(alice, site, "aieo-landing-writer", "Ledgerly, bookkeeping for founders", "aieo.LandingPage")
    worker(ai_services.generate_brief, brief, user=alice)
    brief.refresh_from_db()
    page, _ = ai_services.apply_brief(brief, user=alice)
    assert isinstance(page, LandingPage) and not page.live and page.get_parent().pk == site.root_page.pk
    cro = services.quick_score(copy)["cro"]
    assert cro["landing_page"]["score"] > 0 and cro["checklist"]["checks"]["cta_present"]
    assert services.lifecycle(alice, site)["landing_pages"] == 1


def test_the_library_and_the_assistants_are_seeded_once_and_a_persons_edit_is_kept(db):
    assert Pattern.objects.count() == 10 and Pattern.objects.filter(bundled=True).count() == 10
    keys = [spec.key for spec in prompts.ASSISTANTS]
    found = {
        a.name: a for a in Assistant.objects.filter(visibility="shared", name__in=[s.name for s in prompts.ASSISTANTS])
    }
    assert len(found) == len(keys) == 18
    evaluator = found["AIEO evaluator"]
    assert evaluator.instructions == (prompts.DATA / "prompts" / "system.md").read_text() and evaluator.output_schema
    assert found["Meta creator"].instructions.startswith("Generate 5 meta title options")
    Pattern.objects.filter(name="meta_context").update(body="Edited by a person.")
    report = prompts.seed()
    assert report.created == [] and Pattern.objects.get(name="meta_context").body == "Edited by a person."
    assert AgentRun.objects.count() == 0
