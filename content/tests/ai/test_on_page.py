"""An assistant or a pipeline run on a page from the editor's AI panel
(`POST /api/v2/ai/assistants|pipelines/<id>/run/` with `suggest`): the run
reads the whole page, one block, or text selected in it, and its answer lands
on that page as suggestions the `assistant` agent proposes through the
registry's `content.propose_edit`, acting for the person who asked — new
blocks at the end, or the aimed block replaced — which a person accepts or
rejects; nothing is written until then. Only a person asks; they must be able
to edit the page, and the registry's checks for the agent (its policy narrowed
by the page's, its group's page permissions, the tool's rate) hold when the
run is asked for and again when its answer is proposed. A selection is placed
by its field and the character it starts at, in the text a person sees, and
only that text changes — never a paragraph's tags or attributes, never another
field, never another occurrence. Also: the tools an assistant may list, and
the `can_edit` every owned row carries for the studio. The fake provider
answers; nothing reaches a model."""

from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from wagtail.models import GroupPagePermission, Page

from agents.models import AgentRun, AgentToken
from agents.registry import registry
from agents.runner import execute
from ai import services
from ai.models import Assistant, Brief, Pipeline, PipelineStep
from ops.errors import Conflict, Forbidden, Invalid
from suggestions.models import Suggestion
from suggestions.services import accept, describe, propose

from .test_api import BASE, ran


def blocks(page):
    return page.get_latest_revision_as_object().body.get_prep_value()


@pytest.fixture
def helper(alice):
    return Assistant.objects.create(owner=alice, name="Helper", instructions="Help.", prompt_template="{{ prompt }}")


@pytest.fixture
def varied(article, site_root):
    """The article with a block of every kind a selection can be in: links and an entity in paragraphs, a digit
    a heading shares with its level, a word a code block shares with its language, a word written twice."""
    article.body = [
        {
            "type": "paragraph",
            "id": "p1",
            "value": f'<p>Read <a id="{site_root.pk}" linktype="page">the page</a> about the page type.</p>',
        },
        {
            "type": "paragraph",
            "id": "p2",
            "value": '<p>See <a href="https://example.com/docs">example.com/docs</a> for Q&amp;A.</p>',
        },
        {"type": "heading", "id": "h1", "value": {"level": "2", "text": "Top 2 tips"}},
        {"type": "code", "id": "c1", "value": {"language": "python", "code": "print('python')"}},
        {"type": "markdown", "id": "m1", "value": "We copy the site nightly. Then we copy the backup offsite."},
    ]
    article.save_revision()
    return {b["id"]: b for b in blocks(article)}


def run_on(api, user, assistant, body, capture):
    with capture(execute=True):
        return api(user).post(f"{BASE}/assistants/{assistant.public_id}/run/", body, format="json")


@pytest.mark.django_db
def test_an_assistant_on_a_page_proposes_its_answer_there_as_new_blocks(
    api, alice, helper, fake, article, django_capture_on_commit_callbacks
):
    fake.script.append({"text": "## In short\n\nBack up nightly."})
    body = {"prompt": "Add a summary", "page_id": article.pk, "suggest": True}
    run = ran(run_on(api, alice, helper, body, django_capture_on_commit_callbacks))
    run.refresh_from_db()
    assert run.status == AgentRun.SUCCEEDED, run.error
    assert run.target == article and run.input["kind"] == "page"
    sent = fake.calls[0]["messages"][0]["content"]
    assert sent.startswith("Add a summary\n\n") and "We copy the site to a second disk every night." in sent
    assert "content.propose_edit" not in {t["name"] for t in fake.calls[0]["tools"]}  # the model only reads
    proposed = list(Suggestion.objects.filter(run=run).order_by("id"))
    assert [s.pk for s in proposed] == run.output["suggestions"]
    assert [(s.op, s.block_id, s.payload["type"], s.status) for s in proposed] == [
        ("insert", "", "heading", "pending"),
        ("insert", "", "markdown", "pending"),
    ]
    assert all(s.agent.slug == "assistant" and "Add a summary" in s.rationale for s in proposed)
    # Each proposal was a call of the registry's tool, a step of the run, as the assistant agent.
    calls = run.steps.filter(kind="tool", name="content.propose_edit")
    assert calls.count() == 2 and {c.user.username for c in calls} == {"agent:assistant"}
    assert len(blocks(article)) == 2  # nothing is written until a person accepts
    accept(proposed, alice)
    after = blocks(Page.objects.get(pk=article.pk).specific)
    assert [b["type"] for b in after] == ["heading", "markdown", "heading", "markdown"]
    assert after[-1]["value"] == "Back up nightly." and Page.objects.get(pk=article.pk).has_unpublished_changes


@pytest.mark.django_db
def test_a_block_or_a_selection_in_it_is_replaced_in_place(alice, helper, fake, worker, article):
    heading, text = (b["id"] for b in blocks(article))
    fake.script += [{"text": "What it does"}, {"text": "duplicate"}, {"text": "Twice a night, we copy it."}]
    for block_id, selection in ((heading, ""), (text, "copy")):
        run = worker(
            services.suggest_on_page,
            helper,
            user=alice,
            page=article,
            prompt="Better",
            block_id=block_id,
            selection=selection,
        )
        run.refresh_from_db()
        assert run.status == AgentRun.SUCCEEDED, run.error
    assert run.input["selection_start"] == 3  # placed when asked for: the one "copy" in the block
    renamed, swapped = Suggestion.objects.filter(run__input__kind="page").order_by("id")
    assert (renamed.op, renamed.block_id, renamed.payload) == (
        "replace",
        heading,
        {"type": "heading", "value": {"level": "2", "text": "What it does"}},
    )
    assert (swapped.op, swapped.block_id) == ("replace", text)
    assert swapped.payload == {"type": "markdown", "value": "We duplicate the site to a second disk every night."}
    assert fake.calls[1]["messages"][0]["content"].endswith("\n\ncopy")  # the selection is what the model reads
    run = worker(services.suggest_on_page, helper, user=alice, page=article, prompt="Rewrite", block_id=text)
    run.refresh_from_db()
    whole = Suggestion.objects.get(run=run)
    assert (whole.op, whole.payload) == ("replace", {"type": "markdown", "value": "Twice a night, we copy it."})


@pytest.mark.django_db
def test_a_selection_in_a_paragraph_changes_its_text_never_its_links(varied, site_root):
    internal, external = varied["p1"], varied["p2"]
    # The visible "page" of "the page" (the 10th character on), not the link's linktype="page".
    link = f'<a id="{site_root.pk}" linktype="page">'
    assert services.in_place_of(internal, "article", "page", start=9) == {
        "type": "paragraph",
        "value": f"<p>Read {link}the article</a> about the page type.</p>",
    }
    with pytest.raises(Invalid, match="appears 2 times"):
        services.place(internal, "page")  # which "page"? Never guessed.
    # A link's text, never its href; the answer takes the place and the formatting of where the selection starts.
    assert services.in_place_of(external, "the docs", "example.com/docs")["value"] == (
        '<p>See <a href="https://example.com/docs">the docs</a> for Q&amp;A.</p>'
    )
    assert services.in_place_of(external, "our <docs> & more", "docs for")["value"] == (
        '<p>See <a href="https://example.com/docs">example.com/our &lt;docs&gt; &amp; more</a> Q&amp;A.</p>'
    )
    # Entities are read as a person reads them, and written back as entities.
    assert services.place(external, "Q&A") == ("", 25)
    assert services.in_place_of(external, "questions", "Q&A")["value"].endswith("for questions.</p>")
    with pytest.raises(Invalid, match="not in that block"):
        services.place(external, "Q&amp;A")
    with pytest.raises(Invalid, match="not at that place"):
        services.place(internal, "page", start=23)


@pytest.mark.django_db
def test_a_selection_in_a_structured_block_changes_its_own_field(varied):
    heading, code = varied["h1"], varied["c1"]
    # A heading's text, never its level: the level is a choice, not text a person selects.
    assert services.place(heading, "2") == ("text", 4)
    assert services.in_place_of(heading, "3", "2")["value"] == {"level": "2", "text": "Top 3 tips"}
    with pytest.raises(Invalid, match="'level' is not text"):
        services.place(heading, "2", "level")
    # "python" is the language and in the code: only the field the person selected in changes.
    with pytest.raises(Invalid, match="appears 2 times"):
        services.place(code, "python")
    assert services.in_place_of(code, "ruby", "python", "code", 7)["value"] == {
        "language": "python",
        "code": "print('ruby')",
    }
    assert services.in_place_of(code, "py", "python", "language", 0)["value"]["code"] == "print('python')"


@pytest.mark.django_db
def test_the_selected_occurrence_is_the_one_replaced(varied):
    markdown = varied["m1"]
    with pytest.raises(Invalid, match="appears 2 times"):
        services.place(markdown, "copy")
    assert services.in_place_of(markdown, "send", "copy", start=34)["value"] == (
        "We copy the site nightly. Then we send the backup offsite."
    )
    assert services.in_place_of(markdown, "send", "copy", start=33) is None  # not there: answered beside it


@pytest.mark.django_db
def test_a_selection_is_placed_through_the_api_and_lands_exactly_there(
    api, alice, helper, fake, varied, article, site_root, django_capture_on_commit_callbacks
):
    url = f"{BASE}/assistants/{helper.public_id}/run/"
    at = {"prompt": "Better", "page_id": article.pk, "suggest": True, "block_id": "p1", "selection": "page"}
    refused = api(alice).post(url, at, format="json")
    assert refused.status_code == 422 and "appears 2 times" in refused.json()["error"]["message"]
    assert (
        api(alice).post(url, {**at, "block_id": "h1", "selection": "2", "field": "level"}, format="json").status_code
        == 422
    )
    assert (
        api(alice)
        .post(url, {"prompt": "x", "page_id": article.pk, "suggest": True, "selection_start": 3}, format="json")
        .status_code
        == 422
    )
    fake.script.append({"text": "article"})
    run = ran(run_on(api, alice, helper, {**at, "selection_start": 9}, django_capture_on_commit_callbacks))
    run.refresh_from_db()
    assert run.status == AgentRun.SUCCEEDED, run.error
    assert (run.input["field"], run.input["selection_start"]) == ("", 9)
    suggestion = Suggestion.objects.get(run=run)
    assert suggestion.op == "replace" and f'id="{site_root.pk}" linktype="page"' in suggestion.payload["value"]
    assert "the article</a> about the page type." in suggestion.payload["value"]
    change = describe(suggestion)
    assert (change["before"], change["after"]) == (
        "Read the page about the page type.",
        "Read the article about the page type.",
    )
    accept([suggestion], alice)
    saved = {b["id"]: b for b in blocks(Page.objects.get(pk=article.pk).specific)}["p1"]["value"]
    assert f'<a id="{site_root.pk}" linktype="page">the article</a>' in saved


@pytest.mark.django_db
def test_a_change_only_its_markup_shows_is_described_by_its_source(varied, article):
    assistant_user = get_user_model().objects.get(username="agent:assistant")
    quiet = propose(
        target=article,
        op="replace",
        user=assistant_user,
        block_id="p2",
        payload={
            "type": "paragraph",
            "value": '<p>See <a href="https://example.org/">example.com/docs</a> for Q&amp;A.</p>',
        },
    )
    change = describe(quiet)
    assert change["label"] == "replace paragraph (markup only)"
    assert "https://example.com/docs" in change["before"] and "https://example.org/" in change["after"]


@pytest.mark.django_db
def test_a_selection_gone_by_the_time_the_run_works_is_answered_beside_it(alice, helper, fake, article):
    text = blocks(article)[1]["id"]
    run = services.suggest_on_page(helper, user=alice, page=article, prompt="Better", block_id=text, selection="copy")
    article.body = [{"type": "markdown", "value": "We mirror it.", "id": text}]
    article.save_revision()
    fake.script.append({"text": "duplicate"})
    execute(run)
    added = Suggestion.objects.get(run=run)
    assert (added.op, added.block_id, added.payload) == ("insert", text, {"type": "markdown", "value": "duplicate"})


@pytest.mark.django_db
def test_a_pipeline_on_a_page_suggests_its_last_steps_answer(
    api, alice, helper, fake, article, django_capture_on_commit_callbacks
):
    pipeline = Pipeline.objects.create(owner=alice, name="Two passes")
    PipelineStep.objects.create(pipeline=pipeline, position=1, assistant=helper)
    PipelineStep.objects.create(pipeline=pipeline, position=2, assistant=helper)
    fake.script += [{"text": "A long ending."}, {"text": "An ending."}]
    with django_capture_on_commit_callbacks(execute=True):
        response = api(alice).post(
            f"{BASE}/pipelines/{pipeline.public_id}/run/", {"page_id": article.pk, "suggest": True}, format="json"
        )
    run = ran(response)
    run.refresh_from_db()
    assert run.status == AgentRun.SUCCEEDED and run.children.count() == 2
    assert [s.payload["value"] for s in Suggestion.objects.filter(run=run)] == ["An ending."]


@pytest.mark.django_db
def test_suggesting_on_a_page_needs_the_right_the_policy_and_a_saved_selection(
    api, alice, bob, helper, fake, article, root_page, django_capture_on_commit_callbacks
):
    url = f"{BASE}/assistants/{helper.public_id}/run/"
    helper.visibility = "shared"
    helper.save()
    refused = api(bob).post(url, {"prompt": "x", "page_id": article.pk, "suggest": True}, format="json")
    assert refused.status_code == 403
    for body in (
        {"prompt": "x", "suggest": True},
        {"prompt": "x", "page_id": article.pk, "block_id": "b1"},
        {"prompt": "x", "page_id": article.pk, "suggest": True, "block_id": "nope"},
        {"prompt": "x", "page_id": article.pk, "suggest": True, "selection": "copy"},
        {"prompt": "x", "page_id": root_page.pk, "suggest": True},
    ):
        assert api(alice).post(url, body, format="json").status_code == 422, body
    text = blocks(article)[1]["id"]
    with pytest.raises(Invalid, match="not in that block as saved"):
        services.suggest_on_page(helper, user=alice, page=article, prompt="x", block_id=text, selection="unsaved words")
    with pytest.raises(Invalid, match="say what"):
        services.suggest_on_page(helper, user=alice, page=article, prompt="  ")
    with pytest.raises(Forbidden):
        services.suggest_on_page(helper, user=bob, page=article, prompt="x")
    article.agent_policy = "off"
    article.save()
    with pytest.raises(Conflict, match="needs policy suggest; assistant has off"):
        services.suggest_on_page(helper, user=alice, page=article, prompt="x")
    assert (
        api(alice).post(url, {"prompt": "x", "page_id": article.pk, "suggest": True}, format="json").status_code == 409
    )
    assert not AgentRun.objects.filter(input__kind="page").exists()


@pytest.mark.django_db
def test_an_agent_never_asks_for_suggestions_through_a_persons_screens(helper, fake, article, worker, ready_brief):
    """An agent changes content through the registry under its own policy, tools and token; the AI layer's
    person-facing commands — suggestions on a page, a brief applied — refuse it."""
    helper.visibility = "shared"
    helper.save()
    seo = get_user_model().objects.get(username="agent:seo")
    _, raw = AgentToken.issue(seo, name="read only", tools=["content.get_page"])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    body = {"prompt": "x", "page_id": article.pk, "suggest": True}
    refused = client.post(f"{BASE}/assistants/{helper.public_id}/run/", body, format="json")
    assert refused.status_code == 403 and "asked for by a person" in refused.json()["error"]["message"]
    with pytest.raises(Forbidden, match="a person applies a brief"):
        services.apply_brief(ready_brief, user=seo)
    # A page run an agent started on another surface fails in the worker before it reads anything.
    run = services.start(seo, {"kind": "page", "assistant": str(helper.public_id), "prompt": "x"}, target=article)
    execute(run)
    run.refresh_from_db()
    assert run.status == AgentRun.FAILED and "asked for by a person" in run.error and not fake.calls
    assert not Suggestion.objects.filter(target_id=article.pk).exists()


@pytest.fixture
def ready_brief(alice, site_root):
    run = AgentRun.objects.create(agent=services.agent(), trigger="rest", status="succeeded")
    return Brief.objects.create(
        owner=alice, prompt="cats", status=Brief.READY, run=run, markdown="Cats.", parent=site_root
    )


@pytest.mark.django_db
def test_the_assistant_agents_own_page_permissions_and_rate_hold(
    api, alice, helper, fake, worker, article, django_capture_on_commit_callbacks, monkeypatch
):
    """Narrowing the `agent:assistant` group's page permissions confines it, as it confines any agent; and its
    proposals spend `content.propose_edit`'s rate."""
    body = {"prompt": "x", "page_id": article.pk, "suggest": True}
    queued = services.suggest_on_page(helper, user=alice, page=article, prompt="x")
    rights = GroupPagePermission.objects.filter(group__name="agent:assistant")
    kept = list(rights.values_list("group_id", "page_id", "permission_id"))
    rights.delete()
    refused = api(alice).post(f"{BASE}/assistants/{helper.public_id}/run/", body, format="json")
    assert refused.status_code == 403 and "agent:assistant lacks wagtailcore.change_page" in refused.content.decode()
    execute(queued)  # narrowed after the run was queued: refused before it works
    queued.refresh_from_db()
    assert queued.status == AgentRun.FAILED and "lacks wagtailcore.change_page" in queued.error and not fake.calls
    GroupPagePermission.objects.bulk_create(
        GroupPagePermission(group_id=g, page_id=p, permission_id=perm) for g, p, perm in kept
    )
    tool = registry.get("content.propose_edit")
    monkeypatch.setitem(registry._tools, tool.name, replace(tool, rate="0/m"))
    fake.script.append({"text": "Fine words."})
    run = worker(services.suggest_on_page, helper, user=alice, page=article, prompt="x")
    run.refresh_from_db()
    assert run.status == AgentRun.FAILED and "allows 0/m" in run.error
    assert not Suggestion.objects.filter(run=run).exists()


@pytest.mark.django_db
def test_the_worker_asks_again_before_it_proposes(alice, helper, fake, worker, article):
    run = services.suggest_on_page(helper, user=alice, page=article, prompt="x")
    type(article).objects.filter(pk=article.pk).update(agent_policy="off")
    execute(run)
    run.refresh_from_db()
    assert run.status == AgentRun.FAILED and "needs policy suggest" in run.error and not fake.calls
    assert not Suggestion.objects.filter(run=run).exists()


@pytest.mark.django_db
def test_an_answer_the_brand_guard_refuses_proposes_nothing(alice, helper, fake, worker, article):
    fake.script.append({"text": "## And more\n\nFine words.\n\n## The end\n\nA world-class backup."})
    run = worker(services.suggest_on_page, helper, user=alice, page=article, prompt="x")
    run.refresh_from_db()
    assert run.status == AgentRun.FAILED and "brand guard" in run.error
    assert not Suggestion.objects.filter(run=run).exists()


@pytest.mark.django_db
def test_an_assistant_lists_only_the_read_tools_its_runs_use(api, alice):
    tools = api(alice).get(f"{BASE}/assistants/tools/").json()
    names = {t["name"] for t in tools}
    assert {"content.get_page", "content.search"} <= names and "content.propose_edit" not in names
    assert all(t["description"] for t in tools)


@pytest.mark.django_db
def test_rows_say_whether_the_requester_may_change_them(api, alice, bob, staff):
    shared = Assistant.objects.create(owner=alice, name="Ours", visibility="shared")
    url = f"{BASE}/assistants/{shared.public_id}/"
    assert api(alice).get(url).json()["can_edit"] is True
    assert api(bob).get(url).json()["can_edit"] is False
    assert api(staff).get(url).json()["can_edit"] is True
    brief = Brief.objects.create(owner=alice, prompt="cats")
    seen = api(alice).get(f"{BASE}/briefs/{brief.public_id}/").json()
    assert seen["page"] is None and seen["source_message"] is None and seen["can_edit"] is True
