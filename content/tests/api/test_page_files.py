"""A page's file through the studio's API (cms/files.py): a person authors a
complete Jekyll post — its file path and its raw front matter beside the typed
fields — and the exporter writes it there, typed keys first; an imported page's
raw front matter and path edit without losing its file's layout, and an edit
the content hash cannot see (a reorder, a move) is never exported as the old
file; what a file could not hold, or another page already has, is refused by
field, in the envelope."""

import json
import shutil
from pathlib import Path

import pytest

from cms.models import ArticlePage, Category, CollectionPage, SiteRootPage
from exporters.jekyll import export_site
from importers import frontmatter
from importers.jekyll import import_site
from importers.models import ImportedSource
from tests.api.test_pages import PAGES, post, save, signed_in

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "jekyll" / "site"
HELLO = "pages/_posts/2026-07-31-hello.md"
WIRE = "pages/_posts/wire/2026-10-28-example.md"


@pytest.fixture
def imported(db):
    report = import_site(FIXTURE, "fixture")
    assert not report.errors and not report.conflicts, report.errors + report.conflicts
    return SiteRootPage.objects.get(site_key="fixture")


@pytest.fixture
def posts(imported):
    return CollectionPage.objects.child_of(imported).get(collection="posts")


def page_at(rel):
    return ImportedSource.objects.get(site_key="fixture", legacy_path=rel).page.specific


def errors(response) -> dict:
    assert response.status_code == 422, response.content
    found = {}
    for detail in response.json()["error"]["details"]:
        found.setdefault(detail["field"], []).append(detail["message"])
    return found


def wire_post(posts, **fields):
    return {
        "parent": posts.pk,
        "type": "cms.ArticlePage",
        "fields": {
            "title": "Example dispatch",
            "search_description": "One sourced paragraph about an example.",
            "date": "2026-10-28T09:00:00Z",
            "author": "rhea",
            "tags": ["ai", "news"],
            "categories": [str(Category.objects.get(slug="guides").pk)],
            "file_path": WIRE,
            "front_matter": {
                "excerpt": "The example, in one line.",
                "permalink": "/wire/example/",
                "sources": ["https://example.com/a", "https://example.com/b"],
                "claims": [{"claim": "Example shipped", "source": "https://example.com/a"}],
            },
            **fields,
        },
        "body": [{"type": "markdown", "value": "SAN FRANCISCO (The Wire) — An example shipped."}],
    }


@pytest.mark.django_db
def test_a_person_authors_a_complete_post_and_it_exports_at_its_path(posts, editor, tmp_path):
    client = signed_in(editor)
    created = post(client, PAGES, wire_post(posts))
    assert created.status_code == 201, created.json()
    page = created.json()
    assert page["fields"]["file_path"] == WIRE
    assert list(page["fields"]["front_matter"]) == ["excerpt", "permalink", "sources", "claims"]
    specs = {s["name"]: s for s in page["field_specs"]}
    assert (specs["file_path"]["group"], specs["file_path"]["kind"], specs["file_path"]["label"]) == (
        "file",
        "text",
        "File path",
    )
    assert specs["front_matter"]["kind"] == "json" and "categories" in specs["front_matter"]["help_text"]
    assert post(client, f"{PAGES}{page['id']}/publish/").json()["status"] == "live"

    report = export_site("fixture", tmp_path)
    assert report.rendered == [WIRE] and report.moved == []  # the imported site still exports verbatim
    data, body = frontmatter.split((tmp_path / WIRE).read_text())
    assert list(data) == [
        *("title", "description", "date", "author", "tags", "categories"),  # the typed fields lead …
        *("excerpt", "permalink", "sources", "claims"),  # … then the raw keys, in the order given
    ]
    assert data["title"] == "Example dispatch" and data["date"] == "2026-10-28 09:00:00 +0000"
    assert (data["author"], data["tags"], data["categories"]) == ("rhea", ["ai", "news"], ["guides"])
    assert data["description"] == "One sourced paragraph about an example."
    assert data["permalink"] == "/wire/example/" and data["sources"][1] == "https://example.com/b"
    assert data["claims"] == [{"claim": "Example shipped", "source": "https://example.com/a"}]
    assert body.strip() == "SAN FRANCISCO (The Wire) — An example shipped."

    # The exported file is the platform's page, not a new one, when the site is imported again.
    copy = tmp_path / "copy"
    shutil.copytree(FIXTURE, copy)
    (copy / WIRE).parent.mkdir(parents=True)
    shutil.copy(tmp_path / WIRE, copy / WIRE)
    again = import_site(copy, "fixture")
    assert again.created == [] and WIRE in again.unchanged and not again.conflicts
    assert ArticlePage.objects.filter(title="Example dispatch").count() == 1


@pytest.mark.django_db
def test_raw_front_matter_never_sets_a_typed_key_and_holds_only_what_yaml_can(posts, editor):
    client = signed_in(editor)
    owned = {key: "x" for key in ("title", "description", "seo_title", "date", "author", "tags", "categories")}
    refused = errors(post(client, PAGES, wire_post(posts, front_matter={**owned, "authors": [], "excerpt": "ok"})))
    assert set(refused) == {f"front_matter.{key}" for key in [*owned, "authors"]}
    assert "search_description" in refused["front_matter.description"][0]  # names the field to use instead
    assert "Newsroom" in refused["front_matter.authors"][0]
    assert set(errors(post(client, PAGES, wire_post(posts, front_matter=["excerpt"])))) == {"front_matter"}

    raw = json.dumps(wire_post(posts, front_matter={"note": "SURROGATE"})).replace("SURROGATE", "\\ud800")
    assert set(errors(client.post(PAGES, raw, content_type="application/json"))) == {"front_matter.note"}
    huge = json.dumps(wire_post(posts, front_matter={"weight": "INF"})).replace('"INF"', "1e999")
    assert set(errors(client.post(PAGES, huge, content_type="application/json"))) == {"fields.front_matter"}  # DRF's
    assert not ArticlePage.objects.filter(title="Example dispatch").exists()


@pytest.mark.django_db
def test_a_file_path_is_a_page_file_of_the_site_that_no_other_page_has(posts, site_root, editor):
    client = signed_in(editor)
    for bad in ("/abs.md", "../up.md", "pages//twice.md", "pages/./here.md", "back\\slash.md", "notes.txt", ".md"):
        assert set(errors(post(client, PAGES, wire_post(posts, file_path=bad)))) == {"file_path"}, bad
    taken = errors(post(client, PAGES, wire_post(posts, file_path=HELLO, date="2026-07-31T15:00:00Z")))
    assert "another page of this site" in taken["file_path"][0]
    elsewhere = wire_post(posts, file_path=HELLO, date="2026-07-31T15:00:00Z") | {"parent": site_root.pk}
    assert post(client, PAGES, elsewhere).status_code == 201  # another site's file of that name is its own

    # A dated file name is the date's day in UTC — the day the exporter writes in `date:`.
    late = errors(post(client, PAGES, wire_post(posts, date="2026-10-28T22:00:00-05:00")))
    assert "dated 2026-10-28" in late["file_path"][0] and "2026-10-29 (UTC)" in late["file_path"][0]
    undated = post(client, PAGES, wire_post(posts, date=None)).json()
    assert errors(save(client, ArticlePage.objects.get(pk=undated["id"]), {"fields": {"date": "2026-10-30"}}))["date"]


@pytest.mark.django_db
def test_an_imported_pages_raw_front_matter_edits_in_place_and_a_reorder_is_never_lost(imported, editor, tmp_path):
    client = signed_in(editor)
    hello = page_at(HELLO)
    fields = client.get(f"{PAGES}{hello.pk}/").json()["fields"]
    assert fields["file_path"] == HELLO
    assert fields["front_matter"] == {"preview": "/assets/images/hello.png", "comments": True}  # only the raw keys

    # Sent back as read, nothing changes: the page still exports as its file, byte for byte.
    assert save(client, hello, {"fields": {"front_matter": fields["front_matter"]}}).status_code == 200
    post(client, f"{PAGES}{hello.pk}/publish/")
    assert HELLO in export_site("fixture", tmp_path / "same").verbatim
    assert (tmp_path / "same" / HELLO).read_bytes() == (FIXTURE / HELLO).read_bytes()

    # A reorder alone leaves the content hash as it was; the export still writes the new order.
    reordered = {"comments": True, "preview": "/assets/images/hello.png"}
    assert save(client, hello, {"fields": {"front_matter": reordered}}).status_code == 200
    post(client, f"{PAGES}{hello.pk}/publish/")
    assert ArticlePage.objects.get(pk=hello.pk).content_hash == hello.content_hash
    report = export_site("fixture", tmp_path / "reordered")
    assert report.rendered == [HELLO]
    data, _ = frontmatter.split((tmp_path / "reordered" / HELLO).read_text())
    assert list(data) == ["title", "date", "author", "description", "tags", "categories", "comments", "preview"]

    # A new key lands after the others; the typed keys keep their places in the file.
    added = save(client, hello, {"fields": {"front_matter": {**reordered, "excerpt": "Nightly copies."}}}).json()
    assert list(added["fields"]["front_matter"]) == ["comments", "preview", "excerpt"]
    stored = ArticlePage.objects.get(pk=hello.pk).get_latest_revision_as_object().front_matter
    assert list(stored)[:6] == ["title", "date", "author", "description", "tags", "categories"]


@pytest.mark.django_db
def test_moving_an_imported_page_exports_it_at_its_new_path_and_a_reimport_never_moves_it_back(posts, editor, tmp_path):
    client = signed_in(editor)
    hello = page_at(HELLO)
    moved_to = "pages/_posts/archive/2026-07-31-hello.md"
    refused = errors(save(client, hello, {"fields": {"date": "2026-08-05T10:00:00Z"}}))
    assert "dated 2026-07-31" in refused["date"][0]  # the file name and the date move together
    assert save(client, hello, {"fields": {"file_path": moved_to}}).status_code == 200
    post(client, f"{PAGES}{hello.pk}/publish/")

    report = export_site("fixture", tmp_path)
    assert report.rendered == [moved_to] and report.moved == [(HELLO, moved_to)]
    assert not (tmp_path / HELLO).exists()  # the old file is left where it is, for whoever commits to delete
    data, _ = frontmatter.split((tmp_path / moved_to).read_text())
    assert data["title"] == "Hello, backups" and data["date"] == "2026-07-31 10:00:00 -0500"
    new = errors(post(client, PAGES, wire_post(posts, file_path=HELLO)))
    assert "another page of this site" in new["file_path"][0]  # still the file it was imported from

    copy = tmp_path / "copy"
    shutil.copytree(FIXTURE, copy)
    (copy / moved_to).parent.mkdir(parents=True)
    shutil.copy(tmp_path / moved_to, copy / moved_to)
    (copy / HELLO).write_text((copy / HELLO).read_text().replace("Every night", "Each night"))
    again = import_site(copy, "fixture")
    assert again.created == [] and moved_to in again.unchanged
    assert again.conflicts == [f"{HELLO}: changed in Wagtail since the last import (pass --force to overwrite)"]
    assert ArticlePage.objects.get(pk=hello.pk).legacy_path == moved_to


@pytest.mark.django_db
def test_a_standard_page_has_a_file_too_and_a_section_does_not(imported, posts, editor):
    client = signed_in(editor)
    about = page_at("about.md")
    detail = client.get(f"{PAGES}{about.pk}/").json()
    assert detail["fields"]["file_path"] == "about.md" and detail["fields"]["front_matter"] == {}
    saved = save(client, about, {"fields": {"front_matter": {"layout": "page", "permalink": "/about/"}}})
    assert saved.json()["fields"]["front_matter"] == {"layout": "page", "permalink": "/about/"}
    assert "front_matter.title" in errors(save(client, about, {"fields": {"front_matter": {"title": "x"}}}))
    section = client.get(f"{PAGES}{posts.pk}/").json()
    assert "file_path" not in section["fields"] and "file" not in {s["group"] for s in section["field_specs"]}
    assert "file_path" in errors(save(client, posts, {"fields": {"file_path": "x.md"}}))
