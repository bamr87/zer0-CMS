"""An ABC book's export after an edit (books/abc.py, exporters/jekyll.py): the
plates are planned as the Rails generator planned them, held to its golden
output (drsai's IT Alphabet, frozen in tests/fixtures/abc/); an unedited book
exports its page and its spec sidecar byte for byte; a letter whose word or
subject a person changes in the studio exports a plate planned for it — image,
prompt, status — and a sidecar that agrees, so drsai's own
`tools/import_abc_book.py --check` accepts the export; and the write-back
indexes, guards and records the sidecar as it does the page."""

import json
import posixpath
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from books import abc
from exporters.jekyll import export_site
from importers import frontmatter
from importers.jekyll import import_site
from importers.models import ImportedSource
from jobs.models import Job
from sites import writer
from sites.models import ManagedSite
from tests.api.test_pages import PAGES, post, save, signed_in
from tests.sites.test_sites import admin, api, start  # noqa: F401 — shared fixtures

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "abc"
BOOK = "pages/_books/it-alphabet/index.md"
SIDECAR = "_data/abc_books/it-alphabet.json"
DRSAI_CHECK = Path(settings.REPO_ROOT) / "sites" / "drsai" / "tools" / "import_abc_book.py"
GOLDEN_PAGE, _ = frontmatter.split((FIXTURE / BOOK).read_text(encoding="utf-8"))
GOLDEN_SPEC = json.loads((FIXTURE / SIDECAR).read_text(encoding="utf-8"))


@pytest.fixture
def imported(db):
    report = import_site(FIXTURE, "abc")
    assert report.created == [BOOK] and not report.errors and not report.conflicts
    return ImportedSource.objects.get(site_key="abc", legacy_path=BOOK)


def edit_letter(person, page, letter, **values):
    """Change one letter block through the studio's API, and publish."""
    client = signed_in(person)
    body = client.get(f"{PAGES}{page.pk}/").json()["body"]
    for block in body:
        if block["type"] == "letter" and block["value"]["letter"] == letter:
            block["value"].update(values)
    saved = save(client, page, {"body": body})
    assert saved.status_code == 200, saved.json()
    assert post(client, f"{PAGES}{page.pk}/publish/").json()["status"] == "live"


def drsai_check(site: Path) -> subprocess.CompletedProcess:
    """drsai's CI check ("ABC books match their spec") over `site`: the tool
    reads the Jekyll root its tools/ directory sits in."""
    tool = site / "tools" / DRSAI_CHECK.name
    tool.parent.mkdir(exist_ok=True)
    shutil.copy(DRSAI_CHECK, tool)
    return subprocess.run([sys.executable, str(tool), "--check"], capture_output=True, text=True, check=False)


def exported(out: Path) -> tuple[dict, dict]:
    page, _ = frontmatter.split((out / BOOK).read_text(encoding="utf-8"))
    return page, json.loads((out / SIDECAR).read_text(encoding="utf-8"))


def planned(letter, word, subject) -> str:
    return abc.render_prompt(letter, word, subject, "isometric-tech-toy", "cool-tech", "plain", "playful")


def book_keys(data: dict) -> dict:
    return {key: value for key, value in data.items() if key != "alphabet"}


def test_the_prompts_images_and_sidecar_are_the_rails_generators():
    spec = GOLDEN_SPEC
    for entry in spec["alphabet"]:
        args = (entry["letter"], entry["word"], entry["subject"], spec["art_style"], spec["palette"])
        assert abc.render_prompt(*args, spec["background"], spec["mood"]) == entry["prompt"], entry["letter"]
        folder = posixpath.dirname(entry["image"])
        assert abc.image_path(folder, entry["letter"], entry["word"]) == entry["image"], entry["letter"]
    cover, first = spec["cover"], spec["alphabet"][0]["word"]
    args = ("A", first, cover["subject"], spec["art_style"], spec["palette"])
    assert abc.render_prompt(*args, "scene", spec["mood"]) == cover["prompt"]
    assert abc.dumps(spec) == (FIXTURE / SIDECAR).read_text(encoding="utf-8")
    with pytest.raises(abc.UnknownStyle):
        abc.render_prompt("A", "Automation", "a robot", "no-such-style")


def test_an_unedited_abc_book_exports_its_page_and_sidecar_byte_for_byte(imported, tmp_path, capsys):
    assert list(imported.sidecars) == [SIDECAR]
    report = export_site("abc", tmp_path)
    assert report.verbatim == [BOOK, SIDECAR] and report.rendered == []
    for rel in (BOOK, SIDECAR):
        assert (tmp_path / rel).read_bytes() == (FIXTURE / rel).read_bytes(), rel
    call_command("roundtrip_jekyll", "--path", str(FIXTURE), "--site", "abc-roundtrip")
    assert "2/2 file(s) identical after the round trip" in capsys.readouterr().out


def test_an_edited_word_exports_a_plate_planned_for_it_and_a_sidecar_that_agrees(imported, editor, tmp_path):
    edit_letter(editor, imported.page, "A", word="Robotics")
    report = export_site("abc", tmp_path)
    assert report.rendered == [BOOK, SIDECAR]
    page, spec = exported(tmp_path)
    subject = GOLDEN_SPEC["alphabet"][0]["subject"]
    plate = {
        **GOLDEN_PAGE["alphabet"][0],
        "word": "Robotics",
        "image": "/assets/images/books/it-alphabet/a-robotics.png",
        "prompt": planned("A", "Robotics", subject),
        "status": "planned",  # the image no longer matches its word: it needs drawing (generate_illustrations.py)
    }
    assert page["alphabet"][0] == plate and "standing for the word ROBOTICS (letter A)" in plate["prompt"]
    assert "AUTOMATION" not in plate["prompt"]
    assert page["alphabet"][1:] == GOLDEN_PAGE["alphabet"][1:], "the other 25 letters are unchanged"
    assert book_keys(page) == book_keys(GOLDEN_PAGE)
    entry = spec["alphabet"][0]
    assert list(entry) == list(abc.ENTRY_KEYS) and entry == {**GOLDEN_SPEC["alphabet"][0], **plate}
    assert spec["alphabet"][1:] == GOLDEN_SPEC["alphabet"][1:]
    assert book_keys(spec) == book_keys(GOLDEN_SPEC)
    assert (tmp_path / SIDECAR).read_text(encoding="utf-8") == abc.dumps(spec), "written as the Rails exporter wrote it"
    check = drsai_check(tmp_path)
    assert check.returncode == 0 and "it-alphabet: 26 letters consistent with its spec" in check.stdout, check.stdout


def test_an_edited_subject_recomposes_the_prompt_and_the_sidecar_keeps_it(imported, editor, tmp_path):
    edit_letter(editor, imported.page, "B", subject="a little toy safe holding a spare copy of a picture")
    export_site("abc", tmp_path)
    page, spec = exported(tmp_path)
    prompt = planned("B", "Backup", "a little toy safe holding a spare copy of a picture")
    golden = GOLDEN_PAGE["alphabet"][1]
    assert page["alphabet"][1] == {**golden, "prompt": prompt, "status": "planned"}, "the image is named for the word"
    assert spec["alphabet"][1]["subject"] == "a little toy safe holding a spare copy of a picture"
    assert page["alphabet"][0] == GOLDEN_PAGE["alphabet"][0] and spec["alphabet"][2:] == GOLDEN_SPEC["alphabet"][2:]
    assert drsai_check(tmp_path).returncode == 0


def test_a_sync_reads_the_sidecar_of_a_book_imported_without_one(imported):
    ImportedSource.objects.filter(pk=imported.pk).update(sidecars={})  # a row from before the platform read sidecars
    again = import_site(FIXTURE, "abc")
    assert again.unchanged == [BOOK]
    assert ImportedSource.objects.get(pk=imported.pk).sidecars == {SIDECAR: (FIXTURE / SIDECAR).read_text()}


@pytest.fixture
def checkout(tmp_path, settings):
    settings.SITES_DIR = str(tmp_path)
    root = tmp_path / "abc-site"
    shutil.copytree(FIXTURE, root)
    return root


@pytest.fixture
def registered(api, checkout, django_capture_on_commit_callbacks):  # noqa: F811 — `api` is the shared fixture
    with django_capture_on_commit_callbacks(execute=True):
        response = api.post("/api/v2/sites/", {"checkout": str(checkout), "key": "abc"}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()["site"]["id"]


@pytest.mark.django_db
def test_the_write_back_writes_records_and_keeps_the_sidecar_with_its_page(
    api,  # noqa: F811
    registered,
    checkout,
    editor,
    django_capture_on_commit_callbacks,
):
    sidecar = (checkout / SIDECAR).read_text(encoding="utf-8")
    assert ManagedSite.objects.get(key="abc").digests[SIDECAR] == writer.sha256(sidecar), "a sync indexes it"
    source = ImportedSource.objects.get(site_key="abc", legacy_path=BOOK)
    edit_letter(editor, source.page, "A", word="Robotics")
    job = start(api, registered, "export", django_capture_on_commit_callbacks)
    assert job.status == Job.Status.SUCCEEDED and job.result == {"written": 2}
    page_text, sidecar_text = (checkout / BOOK).read_text(), (checkout / SIDECAR).read_text()
    source.refresh_from_db()
    assert source.source_text == page_text and source.sidecars == {SIDECAR: sidecar_text}, "each recorded as itself"
    assert ManagedSite.objects.get(key="abc").digests[SIDECAR] == writer.sha256(sidecar_text)
    assert '"word": "Robotics"' in sidecar_text and drsai_check(checkout).returncode == 0
    assert start(api, registered, "export", django_capture_on_commit_callbacks).result == {"unchanged": 2}
    assert start(api, registered, "sync", django_capture_on_commit_callbacks).result["updated"] == 0

    # A sidecar changed by hand since is never overwritten; an unpublished book's files both stay.
    (checkout / SIDECAR).write_text(sidecar_text.replace("Robotics", "Robots"), encoding="utf-8")
    edit_letter(editor, source.page, "B", word="Bytes")
    guarded = start(api, registered, "export", django_capture_on_commit_callbacks)
    assert guarded.result == {"written": 1, "conflict": 1} and '"Robots"' in (checkout / SIDECAR).read_text()
    client = signed_in(editor)
    assert post(client, f"{PAGES}{source.page.pk}/unpublish/").json()["status"] == "draft"
    kept = start(api, registered, "export", django_capture_on_commit_callbacks)
    assert "removed" not in kept.result and (checkout / BOOK).exists() and (checkout / SIDECAR).exists()
