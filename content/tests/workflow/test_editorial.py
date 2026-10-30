"""The seeded "Editorial" workflow (P4, G2's backend items): `seed_editorial`
makes it once — the brand agent's review, then a moderator's approval — and
gives it to the sites named; a page sent through it is reviewed by the agent
and waits for a person, and a second run changes nothing."""

import pytest
from django.core.management import call_command
from wagtail.models import GroupApprovalTask, Workflow, WorkflowPage

from workflow.models import AgentReviewTask

from ..conftest import make_article


@pytest.mark.django_db
def test_the_editorial_workflow_is_seeded_once_and_reviews_a_sites_pages(
    site_root, editor, django_capture_on_commit_callbacks, capsys
):
    call_command("seed_editorial", "--site", "test-site")
    call_command("seed_editorial", "--site", "test-site")
    assert "Editorial: Brand review → Moderators approval for test-site" in capsys.readouterr().out
    flow = Workflow.objects.get(name="Editorial")
    review, approval = (task.specific for task in flow.tasks)
    assert isinstance(review, AgentReviewTask) and review.agent == "brand" and not review.is_last_in(flow)
    assert isinstance(approval, GroupApprovalTask) and [g.name for g in approval.groups.all()] == ["Moderators"]
    assert WorkflowPage.objects.get(page=site_root).workflow == flow

    page = make_article(site_root, "Plain notes", publish=False, body=[{"type": "markdown", "value": "We copy files."}])
    assert page.get_workflow() == flow
    with django_capture_on_commit_callbacks(execute=True):
        state = flow.start(page, editor)
    state.refresh_from_db()
    assert [ts.status for ts in state.task_states.order_by("id")] == ["approved", "in_progress"]
    assert state.current_task_state.task.specific == approval
    page.refresh_from_db()
    assert not page.live  # the brand review passed it; a moderator publishes


@pytest.mark.django_db
def test_seeding_for_a_site_that_does_not_exist_is_refused(db):
    with pytest.raises(Exception, match="no such site: nowhere"):
        call_command("seed_editorial", "--site", "nowhere")
    assert not Workflow.objects.filter(name="Editorial").exists()
