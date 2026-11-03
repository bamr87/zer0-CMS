"""A sync and a write-back as jobs that run for minutes (W1-6: SITES-02,
CONTENT-04, OPS-06, SITES-18, ADMIN-10): every document commits on its own,
so a sync cancelled or crashed part way keeps what it committed and the next
one picks up the rest; the job's log grows while it runs (progress, then the
time each phase took); cancel is honoured between documents, and by the
doctor; and a write-back reads the site's index once, so one with nothing to
write costs the same at any size."""

import pytest
from django.db import OperationalError, connection
from django.test.utils import CaptureQueriesContext

from importers import jekyll
from importers.models import ImportedSource
from jobs import services as jobs
from jobs.models import Job
from sites import services
from sites.models import ManagedSite

from .test_sync_perf import make_site


@pytest.fixture
def sites_dir(tmp_path, settings):
    settings.SITES_DIR = str(tmp_path)
    return tmp_path


def run(kind, managed, **params):
    return jobs.execute(services.start(kind, managed, params=params, enqueue=False).pk)


def lines(job) -> list[str]:
    return [line.text for line in Job.objects.get(pk=job.pk).lines.all()]


@pytest.mark.django_db
def test_a_cancelled_sync_keeps_what_it_committed_and_the_next_sync_creates_the_rest(sites_dir, monkeypatch):
    checkout = make_site(sites_dir / "generated", 30)  # 31 files
    managed, first = services.register(str(checkout), key="gen")  # queued: nothing commits here, so it waits
    seen = {}
    importing = services.import_site

    def watched(*args, progress, **kwargs):
        def watching(n, total):
            progress(n, total)
            if n == 26:  # someone presses Cancel while the job runs
                job = Job.objects.get(pk=first.pk)
                seen["status"], seen["lines"] = job.status, lines(job)
                jobs.cancel(job)

        return importing(*args, progress=watching, **kwargs)

    monkeypatch.setattr(services, "import_site", watched)
    cancelled = jobs.execute(first.pk)
    assert cancelled.status == Job.Status.CANCELLED
    assert seen["status"] == Job.Status.RUNNING
    assert seen["lines"][:3] == [f"Reading {managed.checkout} the way Jekyll 4.4 reads it …", "31 file(s) …", "25/31"]
    assert ImportedSource.objects.filter(site_key="gen").count() == 26
    log = lines(cancelled)
    assert sum(text.startswith("new page from ") for text in log) == 26 and log[-1] == "Cancelled."
    assert len(ManagedSite.objects.get(key="gen").digests) == 26, "what it read is recorded, though it stopped"
    monkeypatch.undo()
    again = run("sync", managed)
    assert again.status == Job.Status.SUCCEEDED
    assert (again.result["created"], again.result["unchanged"]) == (5, 26)


@pytest.mark.django_db(transaction=True)
def test_a_sync_that_crashes_on_document_40_keeps_the_39_before_it_and_fails(sites_dir, monkeypatch):
    """Real commits: no transaction wraps the test. The database going away
    (Postgres in recovery) stops the run instead of failing every file left."""
    checkout = make_site(sites_dir / "generated", 44)  # 45 files
    calls = []
    importing = jekyll._import_document

    def crashing(doc, run):
        calls.append(doc.rel)
        if len(calls) == 40:
            raise OperationalError("the database system is in recovery mode")
        return importing(doc, run)

    monkeypatch.setattr(jekyll, "_import_document", crashing)
    managed, job = services.register(str(checkout), key="gen")  # it commits, so the (eager) worker runs it now
    job.refresh_from_db()
    assert job.status == Job.Status.FAILED and job.error == "OperationalError: the database system is in recovery mode"
    assert len(calls) == 40 and not connection.in_atomic_block
    assert ImportedSource.objects.filter(site_key="gen").count() == 39
    monkeypatch.undo()
    again = run("sync", managed)
    assert (again.result["created"], again.result["unchanged"]) == (6, 39)


@pytest.mark.django_db
def test_the_sync_log_says_what_each_phase_took(sites_dir):
    managed, job = services.register(str(make_site(sites_dir / "generated", 3)), key="gen")
    log = lines(jobs.execute(job.pk))
    took = next(text for text in log if text.startswith("Took "))
    for phase in ("scan", "images", "documents", "index"):
        assert f"{phase} " in took, took


@pytest.mark.django_db
def test_the_doctor_honours_a_cancel_before_it_records_anything(sites_dir, monkeypatch):
    managed, sync = services.register(str(make_site(sites_dir / "generated", 3)), key="gen")
    jobs.execute(sync.pk)
    job = services.start("doctor", managed, enqueue=False)
    checking = services.doctor.run

    def slow(root):
        report = checking(root)
        jobs.cancel(Job.objects.get(pk=job.pk))  # Cancel pressed while it checked
        return report

    monkeypatch.setattr(services.doctor, "run", slow)
    assert jobs.execute(job.pk).status == Job.Status.CANCELLED
    managed.refresh_from_db()
    assert managed.last_doctor_at is None and not Job.objects.get(pk=job.pk).artifacts.exists()


# ── a write-back's cost ────────────────────────────────────────────────────


def synced(sites_dir, n):
    managed, job = services.register(str(make_site(sites_dir / f"generated-{n}", n)), key=f"gen-{n}")
    assert jobs.execute(job.pk).status == Job.Status.SUCCEEDED
    return managed


def export_queries(managed) -> tuple[int, dict]:
    """The queries of a write-back but its cancel check before each file (one row read, so Cancel stops it there)."""
    with CaptureQueriesContext(connection) as queries:
        job = run("export", managed)
    assert job.status == Job.Status.SUCCEEDED, job.error
    return sum('"cancel_requested"' not in q["sql"] for q in queries.captured_queries), job.result


@pytest.mark.django_db
def test_a_write_back_with_nothing_to_write_costs_the_same_at_any_size(sites_dir):
    """Before, each file asked whether another page owned its path, and each
    remembered path asked twice whether a page still had it."""
    small, big = synced(sites_dir, 10), synced(sites_dir, 30)
    small_queries, small_result = export_queries(small)
    big_queries, big_result = export_queries(big)
    assert small_result == {"unchanged": 11} and big_result == {"unchanged": 31}
    assert big_queries == small_queries, (small_queries, big_queries)


@pytest.mark.django_db
def test_a_write_back_that_rewrites_every_page_stays_within_its_budget(sites_dir):
    managed = synced(sites_dir, 30)
    for source in ImportedSource.objects.filter(site_key="gen-30").select_related("page"):
        page = source.page.specific
        page.title = f"{page.title}, again"
        page.save_revision().publish()
    queries, result = export_queries(managed)
    assert result == {"written": 31}
    assert queries <= 31 * 5, queries  # 175 before: a lookup and an update for each file
    assert run("export", managed).result == {"unchanged": 31}, "what it wrote is the platform's own now"
