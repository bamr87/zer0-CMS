"""`/api/v2/research/` (research/views.py): people only; rows scoped by
`visible_to` (someone else's private source is a 404, changing a visible one
you may not change a 403, and a site's research is changed by the people who
edit that site); capturing a page answers 202 and a worker fetches it, an
address off the public web is refused at once; questions, fact-checks,
summaries, searches and research briefs answer 202 with their run, executed
here as the worker would; an `Idempotency-Key` replays the first answer. The
fake provider answers, HTTP is recorded, names resolve from a table."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from wagtail.models import Site

from agents.models import AgentRun
from ai import providers
from research.models import Citation, Collection, Quote, Source
from suggestions.models import Suggestion

from ..conftest import make_article
from .conftest import FEED, at, tiny_pdf

BASE = "/api/v2/research"
LISTS = ("collections/", "sources/", "quotes/", "citations/", "feeds/", "questions/", "fact-checks/")


def ran(response):
    assert response.status_code == 202, response.content
    return AgentRun.objects.get(pk=response.json()["run"]["id"])


@pytest.mark.django_db
def test_every_endpoint_is_for_a_signed_in_person(api, alice):
    agent = get_user_model().objects.get(username="agent:seo")
    for path in LISTS:
        assert api().get(f"{BASE}/{path}").status_code == 401
        assert api(agent).get(f"{BASE}/{path}").status_code == 403
        assert api(alice).get(f"{BASE}/{path}").status_code == 200


@pytest.mark.django_db
def test_sources_are_scoped_and_a_sites_research_is_shared_by_its_editors(api, alice, bob, site_root):
    from tests.ai.conftest import _person

    carol = _person("carol", editor=True)
    site = Site.objects.get(root_page=site_root)
    private = api(alice).post(f"{BASE}/sources/", {"kind": "note", "text": "Mine alone."}, format="json").json()
    assert api(bob).get(f"{BASE}/sources/{private['id']}/").status_code == 404
    url = f"{BASE}/collections/"
    team = api(alice).post(url, {"name": "Team", "site": site.pk, "visibility": "site"}, format="json")
    assert team.status_code == 201, team.content
    team = team.json()
    assert api(carol).patch(f"{url}{team['id']}/", {"name": "Our team"}, format="json").status_code == 200
    assert api(bob).get(f"{url}{team['id']}/").status_code == 404
    note = (
        api(carol)
        .post(f"{BASE}/sources/", {"kind": "note", "text": "For all of us.", "collection": team["id"]}, format="json")
        .json()
    )
    assert (note["visibility"], note["site"], note["owner"]) == ("site", site.pk, "carol")
    assert api(alice).patch(f"{BASE}/sources/{note['id']}/", {"summary": "Agreed."}, format="json").status_code == 200
    listed = api(alice).get(f"{BASE}/sources/", {"collection": team["id"]}).json()
    assert [s["id"] for s in listed["results"]] == [note["id"]] and "text" not in listed["results"][0]
    shared = api(alice).post(f"{BASE}/sources/", {"kind": "note", "text": "Everyone."}, format="json").json()
    api(alice).patch(f"{BASE}/sources/{shared['id']}/", {"visibility": "shared"}, format="json")
    assert api(bob).get(f"{BASE}/sources/{shared['id']}/").json()["text"] == "Everyone."
    assert api(bob).patch(f"{BASE}/sources/{shared['id']}/", {"title": "taken"}, format="json").status_code == 403


@pytest.mark.django_db
def test_a_sites_editors_change_its_research_but_only_its_owner_changes_who_sees_it(api, alice, bob, site_root):
    from tests.ai.conftest import _person

    carol = _person("carol", editor=True)
    site = Site.objects.get(root_page=site_root)
    url = f"{BASE}/collections/"
    team = api(alice).post(url, {"name": "Team", "site": site.pk, "visibility": "site"}, format="json").json()
    for change in ({"visibility": "shared"}, {"visibility": "private"}, {"site": None, "visibility": "shared"}):
        refused = api(carol).patch(f"{url}{team['id']}/", change, format="json")
        assert refused.status_code == 403 and "only its owner" in refused.json()["error"]["message"]
    assert api(bob).get(f"{url}{team['id']}/").status_code == 404
    same = {"name": "Our team", "visibility": "site", "site": site.pk}  # what a form sends back unchanged
    assert api(carol).patch(f"{url}{team['id']}/", same, format="json").status_code == 200
    assert api(alice).patch(f"{url}{team['id']}/", {"visibility": "shared"}, format="json").status_code == 200
    assert api(bob).get(f"{url}{team['id']}/").json()["name"] == "Our team"


@pytest.mark.django_db
def test_a_page_is_captured_by_a_worker_and_an_address_off_the_web_refused_at_once(
    api, alice, site_web, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = api(alice).post(
            f"{BASE}/sources/", {"kind": "url", "url": "https://example.com/backups"}, format="json"
        )
    assert response.status_code == 202 and response.json()["status"] == "pending"
    source = api(alice).get(f"{BASE}/sources/{response.json()['id']}/").json()
    assert (source["status"], source["title"]) == ("ready", "Backups explained") and "nightly" in source["text"]
    refused = api(alice).post(f"{BASE}/sources/", {"kind": "url", "url": "http://10.0.0.8/admin"}, format="json")
    assert refused.status_code == 422 and "not a public address" in refused.json()["error"]["message"]
    assert api(alice).post(f"{BASE}/sources/", {"kind": "url"}, format="json").status_code == 422
    site_web.get(at("/backups")).respond(503)
    with django_capture_on_commit_callbacks(execute=True):
        again = api(alice).post(f"{BASE}/sources/{source['id']}/refetch/")
    assert again.status_code == 202 and Source.objects.get(public_id=source["id"]).status == "failed"


@pytest.mark.django_db
def test_a_document_is_uploaded_and_a_search_needs_a_provider_that_can(api, alice, site_web, hits, monkeypatch):
    from .conftest import SearchingFake

    pdf = SimpleUploadedFile("guide.pdf", tiny_pdf("Restore every month."), content_type="application/pdf")
    uploaded = api(alice).post(f"{BASE}/sources/upload/", {"file": pdf, "title": "Restore guide"}, format="multipart")
    assert uploaded.status_code == 201 and uploaded.json()["text"] == "Restore every month."
    assert uploaded.json()["kind"] == "document" and uploaded.json()["title"] == "Restore guide"
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    refused = api(alice).post(f"{BASE}/sources/search/", {"query": "backups"}, format="json")
    assert refused.status_code == 422 and "can search the web" in refused.json()["error"]["message"]
    with providers.override(SearchingFake(hits), "fake"):
        run = ran(api(alice).post(f"{BASE}/sources/search/", {"query": "backups", "max_results": 2}, format="json"))
    assert run.input == {
        "kind": "research.search",
        "query": "backups",
        "collection": None,
        "provider": "fake",
        "max_results": 2,
    }


@pytest.mark.django_db
def test_quotes_and_citations_follow_their_source_and_what_cites_it(api, alice, bob, site_root):
    page = make_article(site_root, "Restores", publish=False)
    source = api(alice).post(f"{BASE}/sources/", {"kind": "note", "text": "Restore monthly."}, format="json").json()
    api(alice).patch(f"{BASE}/sources/{source['id']}/", {"visibility": "shared"}, format="json")
    quote = api(bob).post(f"{BASE}/quotes/", {"source": source["id"], "text": "Restore monthly."}, format="json")
    assert quote.status_code == 201 and quote.json()["owner"] == "bob"
    assert [q["id"] for q in api(alice).get(f"{BASE}/quotes/", {"source": source["id"]}).json()["results"]] == [
        quote.json()["id"]
    ]
    body = {"source": source["id"], "quote": quote.json()["id"], "page": page.pk, "note": "the rule"}
    assert api(bob).post(f"{BASE}/citations/", body, format="json").status_code == 403  # bob may not edit the page
    cited = api(alice).post(f"{BASE}/citations/", body, format="json")
    assert cited.status_code == 201 and cited.json()["page_title"] == "Restores" and cited.json()["note"] == "the rule"
    assert api(alice).post(f"{BASE}/citations/", {"source": source["id"]}, format="json").status_code == 422
    listed = api(alice).get(f"{BASE}/citations/", {"page_id": page.pk}).json()["results"]
    assert [c["source_title"] for c in listed] == ["Restore monthly."]
    assert api(bob).get(f"{BASE}/citations/").json()["results"] == []  # a page bob may not edit stays hidden
    assert api(bob).delete(f"{BASE}/quotes/{quote.json()['id']}/").status_code == 204
    assert not Citation.objects.exists() and not Quote.objects.exists()


@pytest.mark.django_db
def test_a_feed_is_subscribed_refreshed_and_listed(api, alice, web, django_capture_on_commit_callbacks):
    web.get(at("/feed.xml")).respond(200, text=FEED)
    with django_capture_on_commit_callbacks(execute=True):
        created = api(alice).post(
            f"{BASE}/feeds/", {"url": "https://example.com/feed.xml", "interval_minutes": 60}, format="json"
        )
    assert created.status_code == 201
    feed = api(alice).get(f"{BASE}/feeds/{created.json()['id']}/").json()
    assert (feed["title"], feed["items"], feed["error"]) == ("Example News", 2, "")
    with django_capture_on_commit_callbacks(execute=True):
        assert api(alice).post(f"{BASE}/feeds/{feed['id']}/refresh/").status_code == 202
    assert Source.objects.filter(kind="feed").count() == 2
    paused = api(alice).patch(f"{BASE}/feeds/{feed['id']}/", {"active": False}, format="json")
    assert paused.status_code == 200 and paused.json()["active"] is False
    refused = api(alice).post(f"{BASE}/feeds/{feed['id']}/refresh/")
    assert refused.status_code == 422 and "paused" in refused.json()["error"]["message"]
    too_often = api(alice).post(
        f"{BASE}/feeds/", {"url": "https://example.com/x.xml", "interval_minutes": 1}, format="json"
    )
    assert too_often.status_code == 422


@pytest.mark.django_db
def test_what_reaches_the_web_is_throttled_per_person_and_runs_on_its_own_queue(api, alice, bob, web, monkeypatch):
    from django.conf import settings
    from django.core.cache import cache

    from config.celery import app
    from research.tasks import fetch_source, refresh_feed
    from research.views import FetchThrottle

    cache.clear()
    monkeypatch.setattr(FetchThrottle, "rate", "2/min", raising=False)  # the tests' rates are off; this one is on, low
    page = {"kind": "url", "url": "https://example.com/backups"}
    assert [api(alice).post(f"{BASE}/sources/", page, format="json").status_code for _ in range(2)] == [202, 202]
    assert api(alice).post(f"{BASE}/sources/", page, format="json").status_code == 429
    feed = {"url": "https://example.com/feed.xml"}
    assert api(alice).post(f"{BASE}/feeds/", feed, format="json").status_code == 429  # the same allowance
    assert (
        api(alice).post(f"{BASE}/sources/", {"kind": "note", "text": "Not a fetch."}, format="json").status_code == 201
    )
    assert api(bob).post(f"{BASE}/sources/", page, format="json").status_code == 202  # per person
    for task in (fetch_source, refresh_feed):
        assert app.amqp.router.route({}, task.name)["queue"].name == "research"
        assert (task.soft_time_limit, task.time_limit) == (
            settings.RESEARCH_TASK_TIME_LIMIT,
            settings.RESEARCH_TASK_TIME_LIMIT + 30,
        )


@pytest.mark.django_db
def test_a_question_answers_with_its_citations_and_a_key_replays_it(
    api, alice, fake, django_capture_on_commit_callbacks
):
    collection = Collection.objects.create(owner=alice, name="Backups")
    with django_capture_on_commit_callbacks(execute=True):
        note = (
            api(alice)
            .post(
                f"{BASE}/sources/",
                {
                    "kind": "note",
                    "title": "Basics",
                    "text": "Back up nightly.",
                    "collection": str(collection.public_id),
                },
                format="json",
            )
            .json()
        )
    fake.script.append(
        {"text": json.dumps({"answer": "Nightly [S1].", "citations": [{"source": "S1", "quote": "Back up nightly."}]})}
    )
    body = {"text": "How often?", "collection": str(collection.public_id)}
    headers = {"HTTP_IDEMPOTENCY_KEY": "ask-1"}
    with django_capture_on_commit_callbacks(execute=True):
        response = api(alice).post(f"{BASE}/questions/", body, format="json", **headers)
    assert ran(response).status == "succeeded" and response.json()["question"]["status"] == "pending"
    replay = api(alice).post(f"{BASE}/questions/", body, format="json", **headers)
    assert replay.json() == response.json() and replay.headers["Idempotent-Replayed"] == "true"
    question = api(alice).get(f"{BASE}/questions/{response.json()['question']['id']}/").json()
    assert (question["status"], question["answer"], question["error"]) == ("ready", "Nightly [S1].", "")
    assert question["citations"] == [
        {"label": "S1", "source": note["id"], "title": "Basics", "quote": "Back up nightly.", "verified": True}
    ]
    listed = api(alice).get(f"{BASE}/questions/", {"collection": str(collection.public_id)}).json()["results"]
    assert [q["id"] for q in listed] == [question["id"]]


@pytest.mark.django_db
def test_a_fact_check_of_a_draft_lists_findings_and_the_suggestions_they_became(
    api, alice, bob, fake, site_root, django_capture_on_commit_callbacks
):
    page = make_article(
        site_root, "Boiling", body=[{"type": "markdown", "value": "Water boils at 90 C."}], publish=False
    )
    source = (
        api(alice)
        .post(f"{BASE}/sources/", {"kind": "note", "title": "Physics", "text": "Water boils at 100 C."}, format="json")
        .json()
    )
    api(alice).post(f"{BASE}/citations/", {"source": source["id"], "page": page.pk}, format="json")
    finding = {
        "block": "B1",
        "claim": "Water boils at 90 C",
        "verdict": "contradicted",
        "explanation": "It boils at 100 C.",
        "sources": ["S1"],
        "find": "90 C",
        "replace": "100 C",
    }
    fake.script.append({"text": json.dumps({"summary": "One error.", "findings": [finding]})})
    assert api(bob).post(f"{BASE}/fact-checks/", {"page_id": page.pk}, format="json").status_code == 403
    with django_capture_on_commit_callbacks(execute=True):
        response = api(alice).post(f"{BASE}/fact-checks/", {"page_id": page.pk}, format="json")
    run = ran(response)
    check = api(alice).get(f"{BASE}/fact-checks/{response.json()['fact_check']['id']}/").json()
    suggestion = Suggestion.objects.get(run=run)
    assert (check["status"], check["page_title"], check["summary"]) == ("ready", "Boiling", "One error.")
    assert check["findings"][0]["suggestion"] == suggestion.pk and check["findings"][0]["verdict"] == "contradicted"
    assert [c["id"] for c in api(alice).get(f"{BASE}/fact-checks/", {"page_id": page.pk}).json()["results"]] == [
        check["id"]
    ]
    assert api(alice).post(f"{BASE}/fact-checks/", {"page_id": 999999}, format="json").status_code == 404


@pytest.mark.django_db
def test_summaries_and_research_briefs_are_runs(api, alice, bob, fake, django_capture_on_commit_callbacks):
    source = api(alice).post(f"{BASE}/sources/", {"kind": "note", "text": "Back up nightly."}, format="json").json()
    fake.script.append(
        {"text": json.dumps({"summary": "Nightly.", "key_points": [], "entities": [], "quotes": ["Back up nightly."]})}
    )
    with django_capture_on_commit_callbacks(execute=True):
        response = api(alice).post(f"{BASE}/sources/{source['id']}/summarize/")
    assert ran(response).status == "succeeded" and response.json()["source"]["summary_run"]["status"] == "queued"
    summarized = api(alice).get(f"{BASE}/sources/{source['id']}/").json()
    assert (summarized["summary"], summarized["highlights"]) == ("Nightly.", ["Back up nightly."])
    assert summarized["summary_run"]["status"] == "succeeded"
    assert api(bob).post(f"{BASE}/sources/{source['id']}/summarize/").status_code == 404
    collection = api(alice).post(f"{BASE}/collections/", {"name": "Backups"}, format="json").json()
    fake.script.append({"text": "## Target intent\n\nSafety."})
    with django_capture_on_commit_callbacks(execute=True):
        brief = api(alice).post(
            f"{BASE}/collections/{collection['id']}/research-brief/", {"topic": "backups"}, format="json"
        )
    assert ran(brief).output["markdown"] == "## Target intent\n\nSafety."
