"""Jobs (jobs/, PLAN G4): a handler's log, artifacts and result; failure and a
crash; cancel before and while it runs; exclusive kinds per site; and the API —
scoped lists, the detail with its log, the log as server-sent events, an
artifact, cancel."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from wagtail.models import Site

from jobs import services
from jobs.models import Job

pytestmark = pytest.mark.django_db


@pytest.fixture
def handlers():
    """Test handlers, registered for the test only."""
    seen = []

    def work(job, ctx):
        ctx.log("first")
        ctx.artifact("report.txt", "all good\n")
        ctx.log("second", "warning")
        seen.append(job.params)
        return {"done": 2}

    def fail(job, ctx):
        ctx.log("trying", "error")
        raise services.Failed("it could not")

    def crash(job, ctx):
        raise RuntimeError("boom")

    def stop(job, ctx):
        Job.objects.filter(pk=job.pk).update(cancel_requested=True)  # someone asks it to stop meanwhile
        ctx.check()
        ctx.log("never reached")

    saved = dict(services.HANDLERS)
    services.handler("t-work")(work)
    services.handler("t-fail")(fail)
    services.handler("t-crash")(crash)
    services.handler("t-stop")(stop)
    services.handler("t-alone", exclusive=True)(work)
    yield seen
    services.HANDLERS.clear()
    services.HANDLERS.update(saved)


def run(kind, **kwargs):
    return services.execute(services.start(kind, enqueue=False, **kwargs).pk)


def test_a_handler_logs_leaves_artifacts_and_a_result(handlers):
    job = run("t-work", params={"x": 1})
    assert job.status == Job.Status.SUCCEEDED and job.is_final and job.result == {"done": 2}
    assert [(line.idx, line.level, line.text) for line in job.lines.all()] == [
        (0, "info", "first"),
        (1, "warning", "second"),
    ]
    assert job.artifacts.get().content == "all good\n" and handlers == [{"x": 1}]
    assert job.started_at and job.finished_at


def test_a_failure_and_a_crash_end_the_job_as_failed(handlers):
    failed = run("t-fail")
    assert failed.status == Job.Status.FAILED and failed.error == "it could not"
    crashed = run("t-crash")
    assert crashed.status == Job.Status.FAILED and crashed.error == "RuntimeError: boom"
    assert crashed.lines.last().text == "RuntimeError: boom"


def test_cancel_before_it_starts_and_while_it_runs(handlers):
    queued = services.start("t-work", enqueue=False)
    assert services.cancel(queued).status == Job.Status.CANCELLED
    assert services.execute(queued.pk).status == Job.Status.CANCELLED and handlers == [], "it never ran"
    stopped = run("t-stop")
    assert stopped.status == Job.Status.CANCELLED
    assert [line.text for line in stopped.lines.all()] == ["Cancelled."]
    with pytest.raises(services.NotCancellable):
        services.cancel(stopped)


def test_an_exclusive_kind_runs_one_at_a_time_per_site(handlers):
    site = Site.objects.get(is_default_site=True)
    first = services.start("t-alone", site=site, enqueue=False)
    with pytest.raises(services.Busy):
        services.start("t-alone", site=site, enqueue=False)
    services.start("t-work", site=site, enqueue=False)  # not exclusive: fine
    services.execute(first.pk)
    services.start("t-alone", site=site, enqueue=False)  # the first has ended


def test_a_job_queued_by_a_request_runs_once_the_transaction_commits(handlers, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        job = services.start("t-work")
    job.refresh_from_db()
    assert job.status == Job.Status.SUCCEEDED


# ── the API ────────────────────────────────────────────────────────────────


@pytest.fixture
def people(db):
    users = get_user_model().objects
    manager = users.create_user("manager", password="pw")
    manager.user_permissions.add(Permission.objects.get(codename="manage_site"))
    return {
        "owner": users.create_user("owner", password="pw"),
        "manager": manager,
        "other": users.create_user("other", password="pw"),
    }


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_the_api_lists_and_shows_only_what_a_person_may_see(handlers, people):
    mine = run("t-work", user=people["owner"])
    theirs = run("t-work", user=people["other"])
    owner = client_for(people["owner"])
    listed = owner.get("/api/v2/jobs/").json()
    assert [j["id"] for j in listed["results"]] == [str(mine.public_id)]
    detail = owner.get(f"/api/v2/jobs/{mine.public_id}/").json()
    assert detail["status"] == "succeeded" and [line["text"] for line in detail["lines"]] == ["first", "second"]
    assert detail["artifacts"] == [{"name": "report.txt", "media_type": "text/plain", "size": 9}]
    assert owner.get(f"/api/v2/jobs/{theirs.public_id}/").status_code == 404
    artifact = owner.get(f"/api/v2/jobs/{mine.public_id}/artifacts/report.txt/")
    assert artifact.status_code == 200 and artifact.content == b"all good\n"
    assert owner.get(f"/api/v2/jobs/{mine.public_id}/artifacts/missing.txt/").status_code == 404


def test_a_sites_jobs_are_seen_by_whoever_may_manage_it(handlers, people, site_root):
    site = Site.objects.get(root_page=site_root)
    job = run("t-work", user=people["owner"], site=site)
    assert client_for(people["other"]).get(f"/api/v2/jobs/{job.public_id}/").status_code == 404
    # A manager sees the sites whose pages they find; a superuser sees them all.
    admin = get_user_model().objects.create_superuser("admin", password="pw")
    assert client_for(admin).get(f"/api/v2/jobs/?site={site.pk}").json()["results"][0]["id"] == str(job.public_id)


def test_the_log_streams_as_server_sent_events(handlers, people):
    job = run("t-work", user=people["owner"])
    response = client_for(people["owner"]).get(
        f"/api/v2/jobs/{job.public_id}/stream/?after=0", HTTP_ACCEPT="text/event-stream"
    )
    body = b"".join(response.streaming_content).decode()
    assert response["Content-Type"] == "text/event-stream"
    assert body.startswith(": open") and '"text": "second"' in body and '"text": "first"' not in body
    assert "event: status" in body and '"status": "succeeded"' in body and body.rstrip().endswith("data: {}")


def test_cancel_over_the_api(handlers, people):
    queued = services.start("t-work", user=people["owner"], enqueue=False)
    owner = client_for(people["owner"])
    assert owner.post(f"/api/v2/jobs/{queued.public_id}/cancel/").json()["status"] == "cancelled"
    again = owner.post(f"/api/v2/jobs/{queued.public_id}/cancel/")
    assert again.status_code == 409 and again.json()["error"]["code"] == "job.final"
