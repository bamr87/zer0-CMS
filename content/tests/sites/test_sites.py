"""The site registry and its jobs (sites/, PLAN G4), through the API the
studio's Sites area uses: registering a checkout (its first sync runs), the
list and a site's overview, the registry fields and the per-site settings, sync,
the write-back under the stale-write guard, the doctor's findings, and who may
do what."""

import shutil
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from wagtail.models import Page

from importers.models import ImportedSource
from jobs.models import Job
from sites import writer
from sites.models import ManagedSite, SiteSettings

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "jekyll" / "site"
HELLO = "pages/_posts/2026-07-31-hello.md"

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(db):
    return get_user_model().objects.create_superuser("admin", password="pw")


@pytest.fixture
def api(admin):
    client = APIClient()
    client.force_authenticate(admin)
    return client


@pytest.fixture
def checkout(tmp_path, settings):
    settings.SITES_DIR = str(tmp_path)
    root = tmp_path / "fixture-site"
    shutil.copytree(FIXTURE, root)
    return root


@pytest.fixture
def registered(api, checkout, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = api.post("/api/v2/sites/", {"checkout": str(checkout), "key": "fixture"}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def start(api, site_id, kind, capture, body=None, **headers):
    with capture(execute=True):
        response = api.post(f"/api/v2/sites/{site_id}/{kind}/", body or {}, format="json", **headers)
    assert response.status_code == 202, response.json()
    return Job.objects.get(public_id=response.json()["job"]["id"])


def page_at(rel):
    return ImportedSource.objects.get(site_key="fixture", legacy_path=rel).page.specific


# ── the registry ───────────────────────────────────────────────────────────


def test_registering_a_checkout_makes_the_site_and_syncs_it(registered, checkout):
    site, job = registered["site"], registered["job"]
    assert site["managed"]["key"] == "fixture" and site["managed"]["checkout"] == str(checkout.resolve())
    assert site["can_manage"] and job["kind"] == "sync"
    synced = Job.objects.get(public_id=job["id"])
    assert synced.status == Job.Status.SUCCEEDED and synced.result["created"] == 8
    managed = ManagedSite.objects.get(key="fixture")
    assert managed.last_synced_at and managed.digests[HELLO] == writer.sha256((checkout / HELLO).read_bytes())
    assert "new page from pages/_posts/2026-07-31-hello.md" in [line.text for line in synced.lines.all()]


def test_a_checkout_must_be_a_jekyll_site_inside_the_repository_or_sites_dir(api, checkout, tmp_path, settings):
    settings.SITES_DIR = str(checkout / "pages")  # the checkout itself is now outside it
    refused = api.post("/api/v2/sites/", {"checkout": str(checkout)}, format="json")
    assert refused.status_code == 422 and "outside" in refused.json()["error"]["message"]
    not_jekyll = api.post("/api/v2/sites/", {"checkout": "content"}, format="json")
    assert not_jekyll.status_code == 422 and "_config.yml" in not_jekyll.json()["error"]["message"]


def test_the_list_carries_what_the_platform_manages(api, registered):
    listed = {s["id"]: s for s in api.get("/api/v2/sites/").json()}
    mine = listed[registered["site"]["id"]]
    assert mine["managed"]["render"] == "react" and mine["managed"]["content_source"] == "files"
    detail = api.get(f"/api/v2/sites/{mine['id']}/").json()
    assert detail["pages"]["total"] >= 8 and detail["files"] == 8 and detail["jobs"][0]["kind"] == "sync"


def test_discover_lists_the_workspace_sites_not_yet_registered(api, registered):
    found = {c["checkout"]: c for c in api.get("/api/v2/sites/discover/").json()}
    drsai = found["sites/drsai"]
    assert drsai["render"] == "jekyll-theme" and drsai["theme_tag"] and drsai["server"] == "github-pages"
    assert drsai["deploy_target"] == "/drsai/"
    assert not any(c.endswith("fixture-site") for c in found), "a registered checkout is not offered again"


def test_registry_fields_and_the_jekyll_theme_option(api, registered):
    site_id = registered["site"]["id"]
    half = api.patch(f"/api/v2/sites/{site_id}/", {"render": "jekyll-theme"}, format="json")
    assert half.status_code == 422 and "tag" in half.json()["error"]["message"]
    done = api.patch(
        f"/api/v2/sites/{site_id}/",
        {
            "render": "jekyll-theme",
            "theme_tag": "v1.31.3",
            "server": "jekyll-4",
            "domains": ["Fixture.Example", "fixture.example"],
        },
        format="json",
    )
    assert done.status_code == 200, done.json()
    assert done.json()["managed"]["render"] == "jekyll-theme" and done.json()["managed"]["domains"] == [
        "fixture.example"
    ]
    bad = api.patch(f"/api/v2/sites/{site_id}/", {"domains": ["not a host"]}, format="json")
    assert bad.status_code == 422


def test_per_site_settings(api, registered):
    site_id = registered["site"]["id"]
    assert api.get(f"/api/v2/sites/{site_id}/settings/").json()["navigation"] == []
    changed = api.patch(
        f"/api/v2/sites/{site_id}/settings/",
        {
            "seo_title_suffix": " · Fixture",
            "ga4_measurement_id": "G-ABC1234",
            "navigation": [{"label": "Docs", "url": "/docs/"}],
            "brand_voice": "Plain and calm.",
            "skin": "dark",
            "design_tokens": {"accent": "#0af"},
            "monthly_budget_usd": "12.50",
        },
        format="json",
    )
    assert changed.status_code == 200, changed.json()
    settings_row = SiteSettings.objects.get(site_id=site_id)
    assert (
        settings_row.navigation == [{"label": "Docs", "url": "/docs/"}]
        and str(settings_row.monthly_budget_usd) == "12.50"
    )
    assert (
        api.patch(f"/api/v2/sites/{site_id}/settings/", {"ga4_measurement_id": "UA-1"}, format="json").status_code
        == 422
    )


def test_seeing_a_site_is_not_managing_it(registered, editor):
    client = APIClient()
    client.force_authenticate(editor)
    site_id = registered["site"]["id"]
    seen = {s["id"]: s for s in client.get("/api/v2/sites/").json()}[site_id]
    assert seen["can_manage"] is False
    assert client.patch(f"/api/v2/sites/{site_id}/", {"deploy_target": "/x/"}, format="json").status_code == 403
    assert client.post(f"/api/v2/sites/{site_id}/sync/", {}, format="json").status_code == 403
    assert client.post("/api/v2/sites/", {"checkout": "sites/drsai"}, format="json").status_code == 403
    assert client.get(f"/api/v2/sites/{site_id}/settings/").status_code == 200


# ── sync and write-back ────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["jekyll-site", "jekyll-site-src"])
def test_the_rails_fixture_sites_sync_and_export_byte_for_byte(name, capsys):
    """PLAN G4's gate: the fixture sites the Rails catalog was proven on come
    through a sync and an export unchanged, every file the catalog reads."""
    from django.core.management import call_command

    from sites import catalog

    root = FIXTURE.parent.parent / name
    call_command("roundtrip_jekyll", "--path", str(root), "--site", name)
    out = capsys.readouterr().out
    read = len(catalog.scan(root).entries)
    assert f"{read}/{read} file(s) identical after the round trip" in out, out


def test_a_second_sync_reads_nothing_new_and_a_hand_edit_comes_in(
    api, registered, checkout, django_capture_on_commit_callbacks
):
    site_id = registered["site"]["id"]
    again = start(api, site_id, "sync", django_capture_on_commit_callbacks)
    assert again.result["unchanged"] == 8 and again.result["created"] == again.result["updated"] == 0
    about = checkout / "about.md"
    about.write_text(about.read_text().replace("Who writes this site.", "Who writes here."))
    edited = start(api, site_id, "sync", django_capture_on_commit_callbacks)
    assert edited.result["updated"] == 1 and page_at("about.md").search_description == "Who writes here."


def test_a_write_back_rewrites_only_what_changed_and_an_unchanged_one_writes_nothing(
    api, registered, checkout, django_capture_on_commit_callbacks
):
    site_id = registered["site"]["id"]
    hello = page_at(HELLO)
    hello.title = "Hello again, backups"
    hello.save_revision().publish()
    before = (checkout / HELLO).read_text()
    job = start(api, site_id, "export", django_capture_on_commit_callbacks)
    assert job.status == Job.Status.SUCCEEDED and job.result == {"written": 1, "unchanged": 6}
    after = (checkout / HELLO).read_text()
    assert after == before.replace('title: "Hello, backups"', 'title: "Hello again, backups"'), "line surgery"
    assert ManagedSite.objects.get(key="fixture").digests[HELLO] == writer.sha256(after)
    mtimes = {p: p.stat().st_mtime_ns for p in checkout.rglob("*.md")}
    unchanged = start(api, site_id, "export", django_capture_on_commit_callbacks)
    assert unchanged.result == {"unchanged": 7}
    assert {p: p.stat().st_mtime_ns for p in checkout.rglob("*.md")} == mtimes, "an unchanged save writes nothing"
    # The platform now calls that file its own: a sync reads nothing new.
    assert start(api, site_id, "sync", django_capture_on_commit_callbacks).result["updated"] == 0


def test_a_file_changed_by_hand_since_the_last_sync_is_never_overwritten(
    api, registered, checkout, django_capture_on_commit_callbacks
):
    site_id = registered["site"]["id"]
    about = checkout / "about.md"
    hand = about.read_text().replace("Who writes this site.", "Edited by hand.")
    about.write_text(hand)
    page = page_at("about.md")
    page.title = "About (edited here)"
    page.save_revision().publish()
    job = start(api, site_id, "export", django_capture_on_commit_callbacks)
    assert job.result["conflict"] == 1 and about.read_text() == hand
    line = next(line for line in job.lines.all() if line.text.startswith("about.md:"))
    assert line.level == "warning" and "changed on disk since the platform last read or wrote it" in line.text
    # Syncing brings the conflict to the person instead: the page changed here too.
    synced = start(api, site_id, "sync", django_capture_on_commit_callbacks)
    assert synced.result["conflicts"] == 1


def test_a_base_digest_the_index_moved_past_is_refused(api, registered, checkout, django_capture_on_commit_callbacks):
    site_id = registered["site"]["id"]
    page = page_at(HELLO)
    page.title = "Changed"
    page.save_revision().publish()
    stale = start(api, site_id, "export", django_capture_on_commit_callbacks, {"base": {HELLO: "0" * 64}})
    assert stale.result == {"conflict": 1, "unchanged": 6}
    assert 'title: "Hello, backups"' in (checkout / HELLO).read_text()
    current = {HELLO: ManagedSite.objects.get(key="fixture").digests[HELLO]}
    fresh = start(api, site_id, "export", django_capture_on_commit_callbacks, {"base": current})
    assert fresh.result == {"written": 1, "unchanged": 6}


def test_the_file_of_a_page_deleted_here_goes_unless_it_changed_by_hand(
    api, registered, checkout, django_capture_on_commit_callbacks
):
    site_id = registered["site"]["id"]
    page_at("about.md").delete()
    page_at("index.md").delete()
    (checkout / "index.md").write_text("---\ntitle: Home, by hand\n---\n")
    job = start(api, site_id, "export", django_capture_on_commit_callbacks)
    assert not (checkout / "about.md").exists() and (checkout / "index.md").exists()
    assert job.result["removed"] == 1 and job.result["conflict"] == 1
    assert (checkout / "pages/_posts/2026-08-01-unfinished.md").exists(), "a draft's file is not a deleted page's"


def test_a_new_page_gets_a_file_and_the_job_says_so(api, registered, checkout, django_capture_on_commit_callbacks):
    from datetime import UTC, datetime

    from cms.models import ArticlePage, CollectionPage

    posts = CollectionPage.objects.get(collection="posts", path__startswith=Page.objects.get(slug="fixture").path)
    page = ArticlePage(title="Café notes", slug="café-notes", date=datetime(2026, 9, 1, tzinfo=UTC), body=[])
    posts.add_child(instance=page)
    page.save_revision().publish()
    job = start(api, registered["site"]["id"], "export", django_capture_on_commit_callbacks)
    assert job.result["written"] == 1
    assert (checkout / "pages/_posts/2026-09-01-cafe-notes.md").read_text().startswith("---\ntitle: Café notes\n")
    assert ImportedSource.objects.get(page=page).legacy_path == "pages/_posts/2026-09-01-cafe-notes.md"


def test_one_sync_or_write_back_at_a_time(api, registered):
    site_id = registered["site"]["id"]
    first = api.post(f"/api/v2/sites/{site_id}/sync/", {}, format="json")  # queued: no commit, so not run
    assert first.status_code == 202
    busy = api.post(f"/api/v2/sites/{site_id}/export/", {}, format="json")
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "job.busy"


def test_an_idempotency_key_replays_the_job(api, registered):
    site_id = registered["site"]["id"]
    one = api.post(f"/api/v2/sites/{site_id}/doctor/", {}, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    two = api.post(f"/api/v2/sites/{site_id}/doctor/", {}, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert one.json()["job"]["id"] == two.json()["job"]["id"] and two["Idempotent-Replayed"] == "true"


# ── the doctor ─────────────────────────────────────────────────────────────


def test_the_doctor_job_records_its_findings(api, registered, django_capture_on_commit_callbacks):
    site_id = registered["site"]["id"]
    job = start(api, site_id, "doctor", django_capture_on_commit_callbacks)
    assert job.status == Job.Status.SUCCEEDED and job.result == {"errors": 0, "warnings": 2}
    assert job.artifacts.get(name="findings.jsonl").content.count("\n") == 2
    found = api.get(f"/api/v2/sites/{site_id}/findings/?severity=warning").json()
    assert sorted(f["rule"] for f in found) == ["no-preview-images-config", "no-zer0-json"]
    assert api.get(f"/api/v2/sites/{site_id}/findings/?check=fleet").json() == []
    assert api.get(f"/api/v2/sites/{site_id}/").json()["managed"]["warnings"] == 2
