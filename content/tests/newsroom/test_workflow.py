"""The newsroom workflow (PLAN G15): pitch → assigned → drafting → editing → copy
→ scheduled → published → updated or corrected. Editing and copy are Wagtail's
workflow, approved by the story's desk; a move the workflow does not allow is
refused; the breaking-news fast path skips copy and records why; an embargo
holds a story back until its time; a page goes live only through
`cms.services`, under the person's publish permission; and a publish outside
the newsroom, or a stage sent back in Wagtail, keeps the story's status true."""

from datetime import timedelta
from unittest import mock

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from wagtail.models import Page, TaskState, WorkflowState

from cms import services as pages
from cms.models import ArticlePage
from cms.tasks import publish_scheduled
from newsroom import services
from newsroom.models import Correction, StageTask, Story
from ops.errors import Conflict, Forbidden, Invalid

from .conftest import person

S = Story.Status


def page_of(story):
    return Page.objects.get(pk=Story.objects.get(pk=story.pk).page_id).specific


def history(story):
    return [(e.action, e.from_status, e.to_status) for e in story.events.all()]


@pytest.mark.django_db
def test_a_story_goes_from_pitch_to_published_through_wagtails_workflow(desk, ed, copyeditor, reporter):
    story = services.pitch(desk, user=ed, headline="Council votes on the bridge", summary="The vote is Tuesday.")
    assert (story.status, story.slug) == (S.PITCH, "council-votes-on-the-bridge")

    story = services.move(story, S.ASSIGNED, user=ed, assignee=reporter)
    story = services.move(story, S.DRAFTING, user=reporter)
    page = page_of(story)
    assert isinstance(page, ArticlePage) and not page.live and page.get_parent().pk == desk.section_id
    assert (page.title, page.owner) == ("Council votes on the bridge", reporter)

    story = services.move(story, S.EDITING, user=reporter)
    assert story.status == S.EDITING
    state = page.current_workflow_state
    assert state.workflow.name == "Newsroom" and state.current_task_state.task.specific.stage == S.EDITING
    assert pages.lock_for(page, reporter) is not None  # at editing, only the desk's editors change the page
    assert pages.lock_for(page, ed) is None

    story = services.move(story, S.COPY, user=ed, comment="Tight.")
    assert story.status == S.COPY
    assert page.current_workflow_task_state.task.specific.stage == S.COPY

    story = services.move(story, S.PUBLISHED, user=copyeditor)
    page.refresh_from_db()
    assert story.status == S.PUBLISHED and page.live
    state.refresh_from_db()
    assert state.status == WorkflowState.STATUS_APPROVED
    assert [ts.status for ts in state.task_states.order_by("id")] == ["approved", "approved"]
    assert history(story) == [
        ("pitched", "pitch", ""),
        ("assigned", "pitch", "assigned"),
        ("drafting", "assigned", "drafting"),
        ("moved", "drafting", "editing"),
        ("moved", "editing", "copy"),
        ("published", "copy", "published"),
    ]
    assert story.events.get(action="assigned").assignee == reporter


@pytest.mark.django_db
def test_moves_the_workflow_does_not_allow_are_refused(desk, ed, reporter, advance):
    story = services.pitch(desk, user=ed, headline="A pitch")
    for to in (S.DRAFTING, S.EDITING, S.PUBLISHED, S.CORRECTED):
        with pytest.raises(Conflict) as refused:
            services.move(story, to, user=ed)
        assert refused.value.code == "story.transition" and "moves to assigned" in refused.value.message
    drafting = advance(desk, S.DRAFTING, headline="Drafting")
    with pytest.raises(Conflict, match="moves to editing, not to copy"):
        services.move(drafting, S.COPY, user=ed)
    with pytest.raises(Invalid):
        services.move(story, S.ASSIGNED, user=ed)  # assigned needs a person to assign


@pytest.mark.django_db
def test_only_the_desk_assigns_and_approves_its_stages(desk, ed, copyeditor, reporter, advance):
    story = services.pitch(desk, user=reporter, headline="From the reporter")
    with pytest.raises(Forbidden, match="editors assign"):
        services.move(story, S.ASSIGNED, user=reporter, assignee=reporter)
    editing = advance(desk, S.EDITING)
    for someone in (reporter, copyeditor):  # the copy desk does not approve editing
        with pytest.raises(Forbidden, match="editors approve at editing"):
            services.move(editing, S.COPY, user=someone)
    at_copy = services.move(editing, S.COPY, user=ed)
    with pytest.raises(Forbidden, match="copy editors approve at copy"):
        services.move(at_copy, S.PUBLISHED, user=ed)  # the desk has copy editors: copy is theirs
    assert services.move(at_copy, S.PUBLISHED, user=copyeditor).status == S.PUBLISHED


@pytest.mark.django_db
def test_sending_back_returns_the_story_to_drafting_and_it_resumes_where_it_was(
    desk, ed, copyeditor, reporter, advance
):
    story = advance(desk, S.COPY)
    story = services.move(story, S.DRAFTING, user=copyeditor, comment="Check the date in the second paragraph.")
    assert story.status == S.DRAFTING
    assert story.events.last().note == "Check the date in the second paragraph."
    assert page_of(story).current_workflow_state.status == WorkflowState.STATUS_NEEDS_CHANGES
    story = services.move(story, S.EDITING, user=reporter)
    assert story.status == S.COPY  # Wagtail resumes the stage that sent it back


@pytest.mark.django_db
def test_the_breaking_news_fast_path_skips_copy_and_records_why(desk, ed, reporter, advance):
    story = advance(desk, S.EDITING)
    with pytest.raises(Invalid, match="say why"):
        services.move(story, S.PUBLISHED, user=ed)
    with pytest.raises(Forbidden, match="editors publish breaking news"):
        services.move(story, S.PUBLISHED, user=reporter, reason="Bridge closed")
    story = services.move(story, S.PUBLISHED, user=ed, reason="The bridge is closed now")
    page = page_of(story)
    assert story.status == S.PUBLISHED and page.live
    assert (story.breaking, story.fast_path_reason) == (True, "The bridge is closed now")
    assert story.events.last().action == "breaking news" and story.events.last().note == "The bridge is closed now"
    states = {ts.task.specific.stage: ts for ts in TaskState.objects.filter(workflow_state__object_id=str(page.pk))}
    assert states[S.EDITING].status == TaskState.STATUS_APPROVED
    assert states[S.COPY].status == TaskState.STATUS_SKIPPED and "The bridge is closed now" in states[S.COPY].comment


@pytest.mark.django_db
def test_an_embargo_holds_a_story_back_until_its_time(desk, ed, copyeditor, advance):
    embargo = timezone.now() + timedelta(days=1)
    story = advance(desk, S.COPY, embargo=embargo)
    with pytest.raises(Conflict) as held:
        services.move(story, S.PUBLISHED, user=copyeditor)
    assert held.value.code == "story.embargoed"
    with pytest.raises(Conflict, match="embargoed"):
        services.move(story, S.SCHEDULED, user=copyeditor, go_live_at=embargo - timedelta(hours=1))
    story = services.move(story, S.SCHEDULED, user=copyeditor)  # no time given: the embargo's
    page = page_of(story)
    assert story.status == S.SCHEDULED and not page.live
    assert page.scheduled_revision.approved_go_live_at == embargo
    with pytest.raises(Conflict, match="embargo no longer holds"):
        services.update(story, user=ed, embargo=None)
    with mock.patch("django.utils.timezone.now", return_value=embargo + timedelta(minutes=1)):
        publish_scheduled()  # Celery beat, once the time has come
    page.refresh_from_db()
    story.refresh_from_db()
    assert page.live and story.status == S.PUBLISHED and story.events.last().action == "went live"


@pytest.mark.django_db
def test_publishing_is_only_through_the_publish_service_and_its_permission(desk, ed, advance):
    no_publish = person("nopublish", "add", "change")
    desk.copy_editors.set([no_publish])
    story = advance(desk, S.COPY)
    with pytest.raises(PermissionDenied):
        services.move(story, S.PUBLISHED, user=no_publish)
    story.refresh_from_db()
    page = page_of(story)
    assert story.status == S.COPY and not page.live  # the copy approval was rolled back with the refusal
    assert page.current_workflow_task_state.status == TaskState.STATUS_IN_PROGRESS


@pytest.mark.django_db
def test_a_correction_goes_on_the_log_and_a_saved_fix_goes_live_with_it(desk, ed, reporter, advance):
    story = advance(desk, S.PUBLISHED)
    page = page_of(story)
    with pytest.raises(Invalid):
        services.move(story, S.CORRECTED, user=ed, text=" ")
    with pytest.raises(Forbidden):
        services.move(story, S.CORRECTED, user=reporter, text="Wrong date.")
    pages.save_changes(page, ed, base_revision_id=page.latest_revision_id, fields={"title": "Council votes Tuesday"})
    story = services.move(story, S.CORRECTED, user=ed, text="An earlier version gave the wrong day of the vote.")
    page.refresh_from_db()
    assert story.status == S.CORRECTED and page.live and not page.has_unpublished_changes
    assert page.title == "Council votes Tuesday"
    story = services.move(story, S.UPDATED, user=ed, text="Updated with the mayor's statement.")
    assert story.status == S.UPDATED
    log = [(c.kind, c.text) for c in Correction.objects.filter(page=page)]
    assert log == [
        ("correction", "An earlier version gave the wrong day of the vote."),
        ("update", "Updated with the mayor's statement."),
    ]
    assert [c["kind"] for c in page.corrections] == ["correction", "update"]  # what the page API shows


@pytest.mark.django_db
def test_a_publish_outside_the_newsroom_and_a_send_back_in_wagtail_keep_the_story_true(desk, ed, advance, root_page):
    story = advance(desk, S.EDITING)
    page = page_of(story)
    state = page.current_workflow_task_state
    StageTask.objects.get(stage=S.EDITING).on_action(state, ed, "reject", comment="Rework the lede.")
    story.refresh_from_db()
    assert story.status == S.DRAFTING and story.events.last().note == "Rework the lede."

    admin = person("admin", is_superuser=True, is_staff=True)
    pages.publish_now(page_of(story), admin)  # the Wagtail admin's publish, say
    story.refresh_from_db()
    assert story.status == S.PUBLISHED and story.events.last().action == "went live"


@pytest.mark.django_db
def test_other_workflows_still_publish_when_approved(site_root, ed):
    from wagtail.models import GroupApprovalTask, Workflow, WorkflowTask

    from tests.conftest import make_article

    page = make_article(site_root, "Plain page", publish=False)
    workflow = Workflow.objects.create(name="Review")
    task = GroupApprovalTask.objects.create(name="Approve")
    WorkflowTask.objects.create(workflow=workflow, task=task, sort_order=0)
    state = workflow.start(page, ed)
    state.current_task_state.approve(user=ed)
    page.refresh_from_db()
    assert page.live  # WAGTAIL_FINISH_WORKFLOW_ACTION changes only the newsroom's workflow
