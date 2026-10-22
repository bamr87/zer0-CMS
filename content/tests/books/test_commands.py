"""The bookshelf CLI as `manage.py books …`, `import_books` and `export_books`:
the same commands and, for list, show, validate, stats and build, the same
output bookshelf printed."""

import json

import pytest
from django.core.management import call_command

from cms.models import ChapterPage


def run(capsys, *args) -> str:
    call_command(*args)
    return capsys.readouterr().out


@pytest.mark.django_db
def test_list_show_stats_and_validate(sample, capsys):
    listing = run(capsys, "books", "list")
    assert listing.splitlines()[0].split() == ["SLUG", "TITLE", "STATUS", "CH", "WORDS", "PROGRESS"]
    assert "sample  A Sample Book  drafting  2/4  26" in listing and "1 book(s), 26 words of prose." in listing
    assert json.loads(run(capsys, "books", "list", "--json"))[0]["path"] == "library/sample"
    show = run(capsys, "books", "show", "sample")
    assert show.startswith("A Sample Book  (sample)") and "  cast       Ana, Boris" in show
    stats = run(capsys, "books", "stats", "sample")
    assert "  chapters   2 (2 draft)" in stats and "  words      " in stats and " of 1,000" in stats
    assert run(capsys, "books", "validate", "sample") == "No problems found in 1 book(s).\n"
    run(capsys, "books", "add-chapter", "sample", "--title", "Later")  # no navigation yet, few keys
    validate = run(capsys, "books", "validate", "sample")
    assert "warning  sample/chapters/ch02.md  [nav-missing] no link to the next chapter" in validate
    assert "\nBy check:\n" in validate and "0 error(s)" in validate
    with pytest.raises(SystemExit):
        call_command("books", "validate", "sample", "--strict")
    capsys.readouterr()
    issues = json.loads(run(capsys, "books", "validate", "--json"))
    assert {i["code"] for i in issues} == {"nav-missing", "chapter-missing-key"}


@pytest.mark.django_db
def test_new_add_chapter_build_dashboard_and_context(sample, capsys, tmp_path):
    assert "Created library/the-quiet-part" in run(capsys, "books", "new", "--title", "The Quiet Part")
    assert "Created chapter 1: Opening" in run(capsys, "books", "add-chapter", "the-quiet-part", "--title", "Opening")
    assert ChapterPage.objects.filter(title="Opening", number=1, act=1, chapter_status="stub").exists()
    run(capsys, "books", "build", "sample", "--out", str(tmp_path))
    manuscript = (tmp_path / "sample" / "manuscript.md").read_text()
    assert manuscript.startswith("# A Sample Book") and "Ana opened the door" in manuscript
    run(capsys, "books", "dashboard", "--out", str(tmp_path))
    data = json.loads((tmp_path / "library.json").read_text())
    assert [b["slug"] for b in data["books"]] == ["sample", "the-quiet-part"]
    html = (tmp_path / "index.html").read_text()
    assert "<title>Bookshelf</title>" in html and "A Sample Book" in html and "chapter-missing-key" in html
    context = run(capsys, "books", "context", "sample", "--chapter", "2", "--task", "critique")
    assert context.startswith("# Book brief: A Sample Book") and "Give an editorial read" in context


@pytest.mark.django_db
def test_import_and_export_commands(library_dir, tmp_path, capsys):
    assert "library: 4 created, 0 updated" in run(capsys, "import_books", "--path", str(library_dir))
    out = run(capsys, "export_books", "--out", str(tmp_path))
    assert "library: 10 written, 0 unchanged" in out
    assert (tmp_path / "sample" / "book.yml").read_bytes() == (library_dir / "sample" / "book.yml").read_bytes()
    assert "0 written, 10 unchanged" in run(capsys, "export_books", "--out", str(tmp_path))
