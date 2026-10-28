"""Review as a workflow task and evals as a gate (M14): a failing review
blocks the workflow with comments on the blocks; a passing one approves; an
eval regression fails `run_evals` (and so CI); a definition revision goes
live only through a passing suite, and promotion needs an accept rate."""

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import override_settings
from wagtail.models import Comment, GroupApprovalTask, Workflow, WorkflowTask

from agents.evals import gate, run_suite
from agents.models import EvalCase, EvalGateError, EvalResult
from workflow.models import AgentReviewTask

from ..conftest import make_article


def workflow_with(*slugs, human=True):
    """Agent review tasks, then (by default) a human approval — the note's order."""
    workflow = Workflow.objects.create(name="Agent review")
    for i, slug in enumerate(slugs):
        task = AgentReviewTask.objects.create(name=f"{slug} review", agent=slug)
        WorkflowTask.objects.create(workflow=workflow, task=task, sort_order=i)
    if human:
        approval = GroupApprovalTask.objects.create(name="Editor approval")
        approval.groups.set(Group.objects.filter(name="Moderators"))
        WorkflowTask.objects.create(workflow=workflow, task=approval, sort_order=len(slugs))
    return workflow


@pytest.mark.django_db
def test_a_failing_brand_review_blocks_the_workflow_with_block_comments(
    site_root, editor, django_capture_on_commit_callbacks
):
    page = make_article(
        site_root,
        "Launch notes",
        publish=False,
        body=[{"type": "markdown", "value": "Our cutting-edge backup is world-class."}],
    )
    with django_capture_on_commit_callbacks(execute=True):
        state = workflow_with("brand").start(page, editor)
    state.refresh_from_db()
    assert state.status == "needs_changes"
    task_state = state.current_task_state or state.task_states.get()
    assert task_state.status == "rejected" and task_state.finished_by.username == "agent:brand"
    comments = Comment.objects.filter(page=page)
    assert comments.count() == 2 and all(c.contentpath == f"body.{page.body[0].id}" for c in comments)
    assert {c.user.username for c in comments} == {"agent:brand"}


@pytest.mark.django_db
def test_clean_reviews_approve_in_order_and_leave_publishing_to_a_person(
    site_root, editor, django_capture_on_commit_callbacks
):
    page = make_article(
        site_root,
        "Clean notes",
        publish=False,
        body=[
            {"type": "heading", "value": {"level": "2", "text": "Plain"}},
            {"type": "markdown", "value": "We copy files nightly."},
        ],
    )
    with django_capture_on_commit_callbacks(execute=True):
        state = workflow_with("brand", "a11y").start(page, editor)
    state.refresh_from_db()
    assert state.status == "in_progress"
    statuses = [ts.status for ts in state.task_states.order_by("id")]
    assert statuses == ["approved", "approved", "in_progress"]
    assert state.current_task_state.task.specific.name == "Editor approval"
    page.refresh_from_db()
    assert not page.live  # the agents passed it; only the person publishes


@pytest.mark.django_db
def test_the_brand_review_leaves_the_built_in_bans_off_a_chapter_whose_book_switched_them_off(
    site_root, editor, django_capture_on_commit_callbacks
):
    """PLAN P-D7: the review judges a book's chapter as propose and accept do; the site's own bans still hold."""
    from cms.models import BookPage, ChapterPage
    from sites.models import SiteSettings

    own = SiteSettings.for_site(site_root.get_site())
    own.banned_patterns = [{"name": "nightly", "pattern": r"\bnightly\b"}]
    own.save()
    book = BookPage(title="A novel", slug="a-novel", builtin_bans=False)
    site_root.add_child(instance=book)
    states = []
    for number, text in ((1, "It was a revolutionary night."), (2, "The nightly ferry was late.")):
        chapter = ChapterPage(title=f"Chapter {number}", slug=f"ch0{number}", number=number, live=False)
        chapter.body = [{"type": "markdown", "value": text}]
        book.add_child(instance=chapter)
        chapter.save_revision()
        with django_capture_on_commit_callbacks(execute=True):
            states.append(workflow_with("brand").start(chapter, editor))
    for state in states:
        state.refresh_from_db()
    assert [state.status for state in states] == ["in_progress", "needs_changes"]


@pytest.mark.django_db
def test_an_agent_review_cannot_be_the_last_task(site_root, editor, django_capture_on_commit_callbacks):
    page = make_article(site_root, "Last", publish=False, body=[{"type": "markdown", "value": "Fine."}])
    with django_capture_on_commit_callbacks(execute=True):
        state = workflow_with("brand", human=False).start(page, editor)
    state.refresh_from_db()
    assert state.status == "needs_changes"
    assert "last task" in state.task_states.get().comment
    page.refresh_from_db()
    assert not page.live


@pytest.mark.django_db
def test_a_review_task_naming_an_unrunnable_agent_rejects(site_root, editor, django_capture_on_commit_callbacks):
    page = make_article(site_root, "Orphan", publish=False)
    with django_capture_on_commit_callbacks(execute=True):
        state = workflow_with("seo").start(page, editor)  # seo is not a review agent
    state.refresh_from_db()
    assert state.status == "needs_changes"


@pytest.mark.django_db
def test_run_evals_passes_for_the_committed_suites_and_fails_on_a_regression(agent, capsys):
    call_command("run_evals", "--all", "--recorded")
    assert "FAIL" not in capsys.readouterr().out
    seo = agent("seo")
    case = EvalCase.objects.get(agent=seo)
    case.checks = [*case.checks, {"check": "max_length", "field": "seo_title", "max": 10}]
    case.save()
    with pytest.raises(SystemExit) as exit_:
        call_command("run_evals", "--agent", "seo", "--recorded")
    assert exit_.value.code == 1
    assert "FAIL  seo/meta-for-article" in capsys.readouterr().out


@pytest.mark.django_db
def test_a_lower_score_than_the_live_revision_is_a_regression(agent):
    seo = agent("seo")
    case = EvalCase.objects.get(agent=seo)
    EvalResult.objects.create(case=case, revision=seo.live_revision, score=1.0, passed=True)
    draft = seo.get_latest_revision_as_object()
    draft.description = "a new revision"
    revision = draft.save_revision()
    case.checks = [*case.checks, {"check": "max_length", "field": "seo_title", "max": 10}]
    case.save()
    [result] = run_suite(seo, revision)
    assert not result.passed and any(d["check"] == "regression" for d in result.details)


@pytest.mark.django_db
def test_publishing_a_definition_revision_requires_a_passing_suite(agent):
    brand = agent("brand")
    draft = brand.get_latest_revision_as_object()
    draft.description = "untested change"
    revision = draft.save_revision()
    with pytest.raises(EvalGateError, match="has not been run"):
        revision.publish()
    run_suite(brand, revision)
    revision.publish()
    brand.refresh_from_db()
    assert brand.live_revision_id == revision.pk and brand.description == "untested change"


@pytest.mark.django_db
def test_a_definition_without_cases_never_goes_live(agent):
    brand = agent("brand")
    EvalCase.objects.filter(agent=brand).delete()
    assert gate(brand, brand.get_latest_revision()).reasons == [
        "brand has no eval cases; a definition goes live only by passing its suite"
    ]


@pytest.mark.django_db
@override_settings(AGENT_PROMOTION_MIN_DECISIONS=3)
def test_promotion_past_suggest_needs_the_accept_rate(agent):
    seo = agent("seo")
    draft = seo.get_latest_revision_as_object()
    draft.policy = "draft"
    revision = draft.save_revision()
    run_suite(seo, revision)
    reasons = gate(agent("seo"), revision).reasons
    assert len(reasons) == 1 and "accept rate" in reasons[0] and "no decisions" in reasons[0]
