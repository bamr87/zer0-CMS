"""An assistant or a pipeline run on a page from the editor's AI panel
(`POST /api/v2/ai/assistants|pipelines/<id>/run/` with `suggest`): the run
reads the whole page, one block, or text selected in it, and its answer lands
on that page as suggestions from the assistant agent — new blocks at the end,
or the aimed block replaced — which a person accepts or rejects; nothing is
written until then. The person must be able to edit the page and the page's
agent policy must let agents suggest, when the run is asked for and again
when its answer is proposed. Also: the tools an assistant may list, and the
`can_edit` every owned row carries for the studio. The fake provider answers;
nothing reaches a model."""

import pytest
from wagtail.models import Page

from agents.models import AgentRun
from ai import services
from ai.models import Assistant, Brief, Pipeline, PipelineStep
from ops.errors import Conflict, Forbidden, Invalid
from suggestions.models import Suggestion
from suggestions.services import accept

from .test_api import BASE, ran


def blocks(page):
    return page.get_latest_revision_as_object().body.get_prep_value()


@pytest.fixture
def helper(alice):
    return Assistant.objects.create(owner=alice, name="Helper", instructions="Help.", prompt_template="{{ prompt }}")


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
    proposed = list(Suggestion.objects.filter(run=run).order_by("id"))
    assert [s.pk for s in proposed] == run.output["suggestions"]
    assert [(s.op, s.block_id, s.payload["type"], s.status) for s in proposed] == [
        ("insert", "", "heading", "pending"),
        ("insert", "", "markdown", "pending"),
    ]
    assert all(s.agent.slug == "assistant" and "Add a summary" in s.rationale for s in proposed)
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
def test_a_selection_gone_by_the_time_the_run_works_is_answered_beside_it(alice, helper, fake, article):
    text = blocks(article)[1]["id"]
    run = services.suggest_on_page(helper, user=alice, page=article, prompt="Better", block_id=text, selection="copy")
    article.body = [{"type": "markdown", "value": "We mirror it.", "id": text}]
    article.save_revision()
    fake.script.append({"text": "duplicate"})
    from agents.runner import execute

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
    with pytest.raises(Conflict, match="policy is off"):
        services.suggest_on_page(helper, user=alice, page=article, prompt="x")
    assert (
        api(alice).post(url, {"prompt": "x", "page_id": article.pk, "suggest": True}, format="json").status_code == 409
    )
    assert not AgentRun.objects.filter(input__kind="page").exists()


@pytest.mark.django_db
def test_the_worker_asks_again_before_it_proposes(alice, helper, fake, worker, article):
    run = services.suggest_on_page(helper, user=alice, page=article, prompt="x")
    type(article).objects.filter(pk=article.pk).update(agent_policy="off")
    from agents.runner import execute

    execute(run)
    run.refresh_from_db()
    assert run.status == AgentRun.FAILED and "policy is off" in run.error and not fake.calls
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
